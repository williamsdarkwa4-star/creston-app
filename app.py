#!/usr/bin/env python3
"""
JOMA - Safe Flask application

This replacement keeps the JOMA user/admin structure while treating offers as
catalogue items. "Buy Now" is UI-only and does not move money, create a paid
investment, process deposits/withdrawals, or promise returns.

Designed for:
- Flask + PostgreSQL on Render
- Dynamic admin_offer catalogue
- User registration/login/logout
- Admin login/dashboard
- Admin offer CRUD
- Dashboard display of active offers
- No Flask-Login/current_user dependency
"""

from __future__ import annotations

import logging
import os
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None
    RealDictCursor = None


# ============================================================
# CONFIG
# ============================================================

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY",
    "change-this-secret-key-in-production",
)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = (
    os.environ.get("SESSION_COOKIE_SECURE", "False").lower()
    in {"1", "true", "yes"}
)
app.permanent_session_lifetime = timedelta(
    days=int(os.environ.get("SESSION_PERMANENT_DAYS", "7"))
)

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "Williams")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Williams12")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("joma.app")


# ============================================================
# DATABASE
# ============================================================

def require_database() -> None:
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not configured. Add your Render PostgreSQL "
            "DATABASE_URL environment variable."
        )
    if psycopg2 is None:
        raise RuntimeError(
            "psycopg2-binary is not installed. Add psycopg2-binary "
            "to requirements.txt."
        )


@contextmanager
def db_cursor(commit: bool = False, dict_cursor: bool = True):
    require_database()
    conn = psycopg2.connect(DATABASE_URL)
    try:
        cursor_factory = RealDictCursor if dict_cursor else None
        cur = conn.cursor(cursor_factory=cursor_factory)
        try:
            yield cur
            if commit:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
    finally:
        conn.close()


def execute(sql: str, params: tuple = ()) -> None:
    with db_cursor(commit=True) as cur:
        cur.execute(sql, params)


def query_one(sql: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
    with db_cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None


def query_all(sql: str, params: tuple = ()) -> list[Dict[str, Any]]:
    with db_cursor() as cur:
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def init_db() -> None:
    """
    Creates only the tables needed by this safe JOMA application.

    Existing unrelated tables are not deleted or modified.
    """
    require_database()

    statements = [
        """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(80) NOT NULL,
            fullname VARCHAR(150) DEFAULT '',
            phone VARCHAR(40) NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            referral_code VARCHAR(40) NOT NULL UNIQUE,
            referred_by VARCHAR(40),
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS accounts (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
            deposit_account NUMERIC(14,2) NOT NULL DEFAULT 0,
            income_account NUMERIC(14,2) NOT NULL DEFAULT 0,
            referral_account NUMERIC(14,2) NOT NULL DEFAULT 0,
            withdraw_account NUMERIC(14,2) NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS admin_offer (
            id SERIAL PRIMARY KEY,
            name VARCHAR(150) NOT NULL,
            price NUMERIC(14,2) NOT NULL DEFAULT 0,
            daily_amount NUMERIC(14,2) NOT NULL DEFAULT 0,
            duration INTEGER NOT NULL DEFAULT 0,
            image_url TEXT DEFAULT '',
            description TEXT DEFAULT '',
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_admin_offer_active
        ON admin_offer(active)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_admin_offer_created
        ON admin_offer(created_at DESC)
        """,
    ]

    with db_cursor(commit=True) as cur:
        for sql in statements:
            cur.execute(sql)

    logger.info("JOMA database initialization completed.")


# ============================================================
# HELPERS
# ============================================================

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def money(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0.00")


def parse_amount(value: Any) -> Optional[Decimal]:
    try:
        amount = Decimal(str(value).strip())
        if amount < 0:
            return None
        return amount.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError, AttributeError):
        return None


def generate_referral_code() -> str:
    while True:
        code = "JOMA" + secrets.token_hex(4).upper()
        if not query_one(
            "SELECT id FROM users WHERE referral_code=%s",
            (code,),
        ):
            return code


def current_user() -> Optional[Dict[str, Any]]:
    user_id = session.get("user_id")
    if not user_id:
        return None

    return query_one(
        """
        SELECT id, username, fullname, phone, referral_code,
               referred_by, created_at
        FROM users
        WHERE id=%s
        """,
        (user_id,),
    )


def current_account(user_id: int) -> Dict[str, Any]:
    account = query_one(
        """
        SELECT id, user_id, deposit_account, income_account,
               referral_account, withdraw_account
        FROM accounts
        WHERE user_id=%s
        """,
        (user_id,),
    )

    if account:
        return account

    execute(
        """
        INSERT INTO accounts
            (user_id, deposit_account, income_account,
             referral_account, withdraw_account)
        VALUES (%s, 0, 0, 0, 0)
        ON CONFLICT (user_id) DO NOTHING
        """,
        (user_id,),
    )

    return query_one(
        """
        SELECT id, user_id, deposit_account, income_account,
               referral_account, withdraw_account
        FROM accounts
        WHERE user_id=%s
        """,
        (user_id,),
    ) or {
        "user_id": user_id,
        "deposit_account": Decimal("0.00"),
        "income_account": Decimal("0.00"),
        "referral_account": Decimal("0.00"),
        "withdraw_account": Decimal("0.00"),
    }


def admin_required() -> bool:
    return bool(session.get("admin_logged_in"))


def admin_guard():
    if not admin_required():
        return redirect(url_for("admin_login"))
    return None


# ============================================================
# BASIC ROUTES
# ============================================================

@app.route("/")
def index():
    user = current_user()
    if user:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        fullname = request.form.get("fullname", "").strip()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        referral_code = request.form.get("referral_code", "").strip().upper()

        if not username or not phone or not password:
            flash("Please complete all required fields.", "error")
            return render_template(
                "register.html",
                invite_code=referral_code,
            )

        if len(password) < 6:
            flash("Password must contain at least 6 characters.", "error")
            return render_template(
                "register.html",
                invite_code=referral_code,
            )

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template(
                "register.html",
                invite_code=referral_code,
            )

        if query_one("SELECT id FROM users WHERE phone=%s", (phone,)):
            flash("That phone number is already registered.", "error")
            return render_template(
                "register.html",
                invite_code=referral_code,
            )

        if query_one(
            "SELECT id FROM users WHERE LOWER(username)=LOWER(%s)",
            (username,),
        ):
            flash("That username is already in use.", "error")
            return render_template(
                "register.html",
                invite_code=referral_code,
            )

        referred_by = None
        if referral_code:
            owner = query_one(
                "SELECT referral_code FROM users WHERE referral_code=%s",
                (referral_code,),
            )
            if owner:
                referred_by = owner["referral_code"]

        new_referral_code = generate_referral_code()

        try:
            with db_cursor(commit=True) as cur:
                cur.execute(
                    """
                    INSERT INTO users
                        (username, fullname, phone, password_hash,
                         referral_code, referred_by)
                    VALUES (%s,%s,%s,%s,%s,%s)
                    RETURNING id
                    """,
                    (
                        username,
                        fullname,
                        phone,
                        generate_password_hash(password),
                        new_referral_code,
                        referred_by,
                    ),
                )
                user_row = cur.fetchone()
                user_id = user_row["id"]

                cur.execute(
                    """
                    INSERT INTO accounts
                        (user_id, deposit_account, income_account,
                         referral_account, withdraw_account)
                    VALUES (%s,0,0,0,0)
                    ON CONFLICT (user_id) DO NOTHING
                    """,
                    (user_id,),
                )

            flash("Registration successful. Please log in.", "success")
            return redirect(url_for("login"))

        except Exception:
            logger.exception("Registration failed.")
            flash("Unable to register at this time.", "error")

    invite_code = request.args.get("ref", "").strip().upper()
    return render_template("register.html", invite_code=invite_code)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")

        if not phone or not password:
            flash("Please enter your phone number and password.", "error")
            return render_template("login.html")

        user = query_one(
            """
            SELECT id, username, password_hash
            FROM users
            WHERE phone=%s
            """,
            (phone,),
        )

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session.permanent = True
            session["user_id"] = user["id"]
            return redirect(url_for("dashboard"))

        flash("Invalid phone number or password.", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ============================================================
# USER DASHBOARD
# ============================================================

@app.route("/dashboard")
def dashboard():
    user = current_user()
    if not user:
        return redirect(url_for("login"))

    account = current_account(user["id"])

    offers = query_all(
        """
        SELECT id, name, price, daily_amount, duration,
               image_url, description, active, created_at
        FROM admin_offer
        WHERE active=TRUE
        ORDER BY id DESC
        """
    )

    return render_template(
        "dashboard.html",
        user=user,
        account=account,
        offers=offers,
    )


# ============================================================
# SAFE "BUY NOW" UI ACTION
# ============================================================

@app.route("/buy_offer/<int:offer_id>")
def buy_offer(offer_id: int):
    """
    UI-only action.

    It does NOT:
    - charge an account
    - deduct a balance
    - create an investment
    - create a financial contract
    - promise daily income
    """
    user = current_user()
    if not user:
        return redirect(url_for("login"))

    offer = query_one(
        """
        SELECT id, name, price, daily_amount, duration,
               image_url, description
        FROM admin_offer
        WHERE id=%s AND active=TRUE
        """,
        (offer_id,),
    )

    if not offer:
        flash("Offer is no longer available.", "error")
        return redirect(url_for("dashboard"))

    return render_template(
        "offer_selected.html",
        user=user,
        offer=offer,
    )


# ============================================================
# PROFILE
# ============================================================

@app.route("/profile", methods=["GET", "POST"])
def profile():
    user = current_user()
    if not user:
        return redirect(url_for("login"))

    if request.method == "POST":
        fullname = request.form.get("fullname", "").strip()
        username = request.form.get("username", "").strip()

        if not username:
            flash("Username cannot be empty.", "error")
            return redirect(url_for("profile"))

        duplicate = query_one(
            """
            SELECT id FROM users
            WHERE LOWER(username)=LOWER(%s) AND id<>%s
            """,
            (username, user["id"]),
        )

        if duplicate:
            flash("That username is already in use.", "error")
            return redirect(url_for("profile"))

        execute(
            """
            UPDATE users
            SET username=%s, fullname=%s
            WHERE id=%s
            """,
            (username, fullname, user["id"]),
        )

        flash("Profile updated successfully.", "success")
        return redirect(url_for("profile"))

    user = current_user()
    return render_template("profile.html", user=user)


@app.route("/change-password", methods=["GET", "POST"])
def change_password():
    user = current_user()
    if not user:
        return redirect(url_for("login"))

    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        row = query_one(
            "SELECT password_hash FROM users WHERE id=%s",
            (user["id"],),
        )

        if not row or not check_password_hash(
            row["password_hash"],
            current_password,
        ):
            flash("Current password is incorrect.", "error")
            return redirect(url_for("change_password"))

        if len(new_password) < 6:
            flash("New password must contain at least 6 characters.", "error")
            return redirect(url_for("change_password"))

        if new_password != confirm_password:
            flash("New passwords do not match.", "error")
            return redirect(url_for("change_password"))

        execute(
            """
            UPDATE users
            SET password_hash=%s
            WHERE id=%s
            """,
            (generate_password_hash(new_password), user["id"]),
        )

        flash("Password changed successfully.", "success")
        return redirect(url_for("profile"))

    return render_template("change_password.html")


# ============================================================
# REFERRAL / TEAM INFORMATION
# ============================================================

@app.route("/team")
def team():
    user = current_user()
    if not user:
        return redirect(url_for("login"))

    members = query_all(
        """
        SELECT id, username, fullname, created_at
        FROM users
        WHERE referred_by=%s
        ORDER BY id DESC
        """,
        (user["referral_code"],),
    )

    referral_link = (
        request.url_root.rstrip("/")
        + url_for("register")
        + "?ref="
        + user["referral_code"]
    )

    account = current_account(user["id"])

    return render_template(
        "team.html",
        user=user,
        members=members,
        referral_link=referral_link,
        account=account,
    )


# ============================================================
# SUPPORT
# ============================================================

@app.route("/service/support")
@app.route("/support")
def support():
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    return render_template("support.html", user=user)


@app.route("/service/support/team")
def support_team():
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    return render_template("support_team.html", user=user)


# ============================================================
# ADMIN AUTH
# ============================================================

@app.route("/admin")
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if admin_required():
        return redirect(url_for("admin_dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if (
            secrets.compare_digest(username, ADMIN_USERNAME)
            and secrets.compare_digest(password, ADMIN_PASSWORD)
        ):
            session.clear()
            session.permanent = True
            session["admin_logged_in"] = True
            session["admin_username"] = username
            return redirect(url_for("admin_dashboard"))

        flash("Invalid administrator credentials.", "error")

    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


# ============================================================
# ADMIN DASHBOARD
# ============================================================

@app.route("/admin/dashboard")
def admin_dashboard():
    guard = admin_guard()
    if guard:
        return guard

    total_users = query_one(
        "SELECT COUNT(*) AS count FROM users"
    )["count"]

    total_offers = query_one(
        "SELECT COUNT(*) AS count FROM admin_offer"
    )["count"]

    active_offers = query_one(
        "SELECT COUNT(*) AS count FROM admin_offer WHERE active=TRUE"
    )["count"]

    return render_template(
        "admin_dashboard.html",
        total_users=total_users,
        total_offers=total_offers,
        active_offers=active_offers,
    )


# ============================================================
# ADMIN USERS
# ============================================================

@app.route("/admin_users")
@app.route("/admin/users")
def admin_users():
    guard = admin_guard()
    if guard:
        return guard

    users = query_all(
        """
        SELECT u.id, u.username, u.fullname, u.phone,
               u.referral_code, u.referred_by, u.created_at,
               a.deposit_account, a.income_account,
               a.referral_account, a.withdraw_account
        FROM users u
        LEFT JOIN accounts a ON a.user_id=u.id
        ORDER BY u.id DESC
        """
    )

    return render_template("admin_users.html", users=users)


@app.route("/admin/user/<int:user_id>", methods=["GET", "POST"])
def admin_manage_user(user_id: int):
    guard = admin_guard()
    if guard:
        return guard

    user = query_one(
        """
        SELECT id, username, fullname, phone,
               referral_code, referred_by, created_at
        FROM users
        WHERE id=%s
        """,
        (user_id,),
    )

    if not user:
        return "User not found", 404

    if request.method == "POST":
        action = request.form.get("action", "").strip()

        if action == "update_profile":
            fullname = request.form.get("fullname", "").strip()
            username = request.form.get("username", "").strip()

            if not username:
                flash("Username is required.", "error")
            else:
                duplicate = query_one(
                    """
                    SELECT id FROM users
                    WHERE LOWER(username)=LOWER(%s) AND id<>%s
                    """,
                    (username, user_id),
                )

                if duplicate:
                    flash("Username already exists.", "error")
                else:
                    execute(
                        """
                        UPDATE users
                        SET username=%s, fullname=%s
                        WHERE id=%s
                        """,
                        (username, fullname, user_id),
                    )
                    flash("User profile updated.", "success")

        elif action == "reset_password":
            new_password = request.form.get("new_password", "")
            if len(new_password) < 6:
                flash("Password must contain at least 6 characters.", "error")
            else:
                execute(
                    """
                    UPDATE users
                    SET password_hash=%s
                    WHERE id=%s
                    """,
                    (generate_password_hash(new_password), user_id),
                )
                flash("Password reset successfully.", "success")

        else:
            flash("Unknown administrator action.", "error")

        return redirect(
            url_for("admin_manage_user", user_id=user_id)
        )

    account = current_account(user_id)

    return render_template(
        "admin_manage_user.html",
        user=user,
        account=account,
    )


# ============================================================
# ADMIN OFFER CATALOGUE
# ============================================================

@app.route("/admin/offers")
def admin_offers():
    guard = admin_guard()
    if guard:
        return guard

    offers = query_all(
        """
        SELECT id, name, price, daily_amount, duration,
               image_url, description, active,
               created_at, updated_at
        FROM admin_offer
        ORDER BY id DESC
        """
    )

    return render_template(
        "admin_offers.html",
        offers=offers,
    )


@app.route("/admin/offers/create", methods=["GET", "POST"])
def admin_create_offer():
    guard = admin_guard()
    if guard:
        return guard

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        price = parse_amount(request.form.get("price", "0"))
        daily_amount = parse_amount(
            request.form.get("daily_amount", "0")
        )
        duration_raw = request.form.get("duration", "0").strip()
        image_url = request.form.get("image_url", "").strip()
        description = request.form.get("description", "").strip()
        active = request.form.get("active") in {
            "1", "true", "on", "yes"
        }

        try:
            duration = int(duration_raw or "0")
        except ValueError:
            duration = -1

        if not name:
            flash("Offer name is required.", "error")
            return render_template("admin_offer_form.html", offer=None)

        if price is None or daily_amount is None:
            flash("Price values must be valid numbers.", "error")
            return render_template("admin_offer_form.html", offer=None)

        if duration < 0:
            flash("Duration cannot be negative.", "error")
            return render_template("admin_offer_form.html", offer=None)

        execute(
            """
            INSERT INTO admin_offer
                (name, price, daily_amount, duration,
                 image_url, description, active)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                name,
                price,
                daily_amount,
                duration,
                image_url,
                description,
                active,
            ),
        )

        flash("Offer created successfully.", "success")
        return redirect(url_for("admin_offers"))

    return render_template("admin_offer_form.html", offer=None)


@app.route("/admin/offers/edit/<int:offer_id>", methods=["GET", "POST"])
def admin_edit_offer(offer_id: int):
    guard = admin_guard()
    if guard:
        return guard

    offer = query_one(
        """
        SELECT id, name, price, daily_amount, duration,
               image_url, description, active
        FROM admin_offer
        WHERE id=%s
        """,
        (offer_id,),
    )

    if not offer:
        return "Offer not found", 404

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        price = parse_amount(request.form.get("price", "0"))
        daily_amount = parse_amount(
            request.form.get("daily_amount", "0")
        )
        duration_raw = request.form.get("duration", "0").strip()
        image_url = request.form.get("image_url", "").strip()
        description = request.form.get("description", "").strip()
        active = request.form.get("active") in {
            "1", "true", "on", "yes"
        }

        try:
            duration = int(duration_raw or "0")
        except ValueError:
            duration = -1

        if not name:
            flash("Offer name is required.", "error")
            return render_template(
                "admin_offer_form.html",
                offer=offer,
            )

        if price is None or daily_amount is None:
            flash("Price values must be valid numbers.", "error")
            return render_template(
                "admin_offer_form.html",
                offer=offer,
            )

        if duration < 0:
            flash("Duration cannot be negative.", "error")
            return render_template(
                "admin_offer_form.html",
                offer=offer,
            )

        execute(
            """
            UPDATE admin_offer
            SET name=%s,
                price=%s,
                daily_amount=%s,
                duration=%s,
                image_url=%s,
                description=%s,
                active=%s,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=%s
            """,
            (
                name,
                price,
                daily_amount,
                duration,
                image_url,
                description,
                active,
                offer_id,
            ),
        )

        flash("Offer updated successfully.", "success")
        return redirect(url_for("admin_offers"))

    return render_template(
        "admin_offer_form.html",
        offer=offer,
    )


@app.route("/admin/offers/toggle/<int:offer_id>", methods=["POST"])
def admin_toggle_offer(offer_id: int):
    guard = admin_guard()
    if guard:
        return guard

    offer = query_one(
        "SELECT id, active FROM admin_offer WHERE id=%s",
        (offer_id,),
    )

    if not offer:
        flash("Offer not found.", "error")
        return redirect(url_for("admin_offers"))

    execute(
        """
        UPDATE admin_offer
        SET active=NOT active,
            updated_at=CURRENT_TIMESTAMP
        WHERE id=%s
        """,
        (offer_id,),
    )

    flash("Offer status updated.", "success")
    return redirect(url_for("admin_offers"))


@app.route("/admin/offers/delete/<int:offer_id>", methods=["POST"])
def admin_delete_offer(offer_id: int):
    guard = admin_guard()
    if guard:
        return guard

    offer = query_one(
        "SELECT id, name FROM admin_offer WHERE id=%s",
        (offer_id,),
    )

    if not offer:
        flash("Offer not found.", "error")
        return redirect(url_for("admin_offers"))

    execute(
        "DELETE FROM admin_offer WHERE id=%s",
        (offer_id,),
    )

    flash(f"{offer['name']} deleted successfully.", "success")
    return redirect(url_for("admin_offers"))


# ============================================================
# OPTIONAL COMPATIBILITY ROUTES
# ============================================================

@app.route("/offers")
def offers():
    user = current_user()
    if not user:
        return redirect(url_for("login"))

    active_offers = query_all(
        """
        SELECT id, name, price, daily_amount, duration,
               image_url, description
        FROM admin_offer
        WHERE active=TRUE
        ORDER BY id DESC
        """
    )

    return render_template(
        "offers.html",
        user=user,
        offers=active_offers,
    )


@app.route("/my_plan")
def my_plan():
    """
    Compatibility page only.

    The safe replacement does not create or activate financial plans.
    """
    user = current_user()
    if not user:
        return redirect(url_for("login"))

    return render_template(
        "my_plan.html",
        user=user,
        plans=[],
    )


@app.route("/transaction_history")
def transaction_history():
    """
    Compatibility page only.

    This safe replacement does not create financial transactions.
    """
    user = current_user()
    if not user:
        return redirect(url_for("login"))

    return render_template(
        "transaction_history.html",
        transactions=[],
    )


# ============================================================
# ERROR HANDLERS
# ============================================================

@app.errorhandler(413)
def request_too_large(error):
    return "Uploaded file is too large.", 413


@app.errorhandler(404)
def not_found(error):
    return render_template("404.html"), 404


@app.errorhandler(500)
def internal_error(error):
    logger.exception("Unhandled application error.")
    return render_template("500.html"), 500


# ============================================================
# STARTUP
# ============================================================

@app.before_request
def initialize_database_once():
    """
    Initialize tables on the first request.

    This avoids making deployment fail merely because the database is
    temporarily unavailable during process startup.
    """
    if getattr(app, "_joma_db_initialized", False):
        return

    try:
        init_db()
        app._joma_db_initialized = True
    except Exception:
        logger.exception("Database initialization failed.")
        # Let the individual request surface the database configuration
        # problem rather than crashing the Gunicorn worker at import time.


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "False").lower() in {
        "1", "true", "yes"
    }
    app.run(host="0.0.0.0", port=port, debug=debug)
