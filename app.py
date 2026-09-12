#!/usr/bin/env python3
from __future__ import annotations

"""JOMA Flask application."""

import logging
import os
import uuid
import secrets
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user

try:
    from pydantic_settings import BaseSettings
    from pydantic import Field
except ImportError:
    from pydantic import BaseSettings, Field
from werkzeug.security import check_password_hash, generate_password_hash

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except Exception:
    psycopg2 = None
    RealDictCursor = None

# ============================================================
# CONFIGURATION
# ============================================================

class Settings(BaseSettings):
    SECRET_KEY: str = Field("change-this-secret-key", env="SECRET_KEY")
    DATABASE_URL: Optional[str] = Field(None, env="DATABASE_URL")
    ADMIN_USERNAME: str = Field("Williams", env="ADMIN_USERNAME")
    ADMIN_PASSWORD: str = Field("Williams12", env="ADMIN_PASSWORD")
    PORT: int = Field(5000, env="PORT")
    FLASK_DEBUG: bool = Field(False, env="FLASK_DEBUG")
    MAX_CONTENT_LENGTH: int = Field(5 * 1024 * 1024)
    SESSION_PERMANENT_DAYS: int = Field(7, env="SESSION_PERMANENT_DAYS")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()

# ============================================================
# FLASK APP & LOGGING
# ============================================================

app = Flask(__name__)
app.secret_key = settings.SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = settings.MAX_CONTENT_LENGTH
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "False").lower() in ("1","true","yes")
app.permanent_session_lifetime = timedelta(days=settings.SESSION_PERMANENT_DAYS)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("zenith.app")

# ============================================================
# LOGIN MANAGER - FIXED FOR YOUR PSYCOPG2 DB
# ============================================================

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# User class that works with Flask-Login + your postgres DB
class User(UserMixin):
    def __init__(self, id, username, email=None, password_hash=None, data=None):
        self.id = str(id)
        self.username = username
        self.email = email
        self.password_hash = password_hash
        self._data = data or {}

    def get_id(self):
        return str(self.id)

@login_manager.user_loader
def load_user(user_id):
    try:
        # Load user from your users table
        row = query_one("SELECT * FROM users WHERE id = %s", (int(user_id),))
        if not row:
            return None
        return User(
            id=row.get('id'),
            username=row.get('username') or row.get('phone') or f"user{row.get('id')}",
            email=row.get('email'),
            password_hash=row.get('password_hash') or row.get('password'),
            data=row
        )
    except Exception as e:
        logger.error(f"load_user error: {e}")
        return None

# ============================================================
# PLATFORM SETTINGS & PLANS
# ============================================================

MIN_DEPOSIT = Decimal("100.00")
MIN_WITHDRAWAL = Decimal("32.00")
STARTING_DEPOSIT_BALANCE = Decimal("0")
CLAIM_INTERVAL_HOURS = 24

REFERRAL_PERCENTS: List[Decimal] = [Decimal("0.20"), Decimal("0.03"), Decimal("0.01")]

PLANS = {
    1: {"name": "JOMA VIP 1", "investment": Decimal("100.00"), "daily": Decimal("20.00"), "duration": 180, "image_url": "images/Screenshot_20260826_034656_Google.jpg"},
    2: {"name": "JOMA VIP 2", "investment": Decimal("250.00"), "daily": Decimal("45.00"), "duration": 180,"image_url":"images/Screenshot_20260901_041628_Chrome.jpg"},
    3: {"name": "JOMA VIP 3", "investment": Decimal("600.00"), "daily": Decimal("120.00"), "duration": 180},
    4: {"name": "JOMA VIP 4", "investment": Decimal("1000.00"), "daily": Decimal("120.00"), "duration": 180},
    5: {"name": "INFINIX 5", "investment": Decimal("2500.00"), "daily": Decimal("500.00"), "duration": 180},
    6: {"name": "INFINIX 6", "investment": Decimal("5000.00"), "daily": Decimal("1000.00"), "duration": 180},
    7: {"name": "INFINIX 7", "investment": Decimal("8000.00"), "daily": Decimal("1600.00"), "duration": 180},
    8: {"name": "INFINIX 8", "investment": Decimal("10000.00"), "daily": Decimal("2000.00"), "duration": 180},
    9: {"name": "JOMA VIP 9", "investment": Decimal("20000.00"), "daily": Decimal("3600.00"), "duration": 180},
}

# ============================================================
# UTILITIES
# ============================================================


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def money(value: Any) -> Decimal:
    if value is None:
        return Decimal("0.00")
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except Exception:
        return Decimal("0.00")


def parse_amount(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not amount.is_finite() or amount <= 0:
        return None
    return amount.quantize(Decimal("0.01"))


def generate_referral_code() -> str:
    return "JOMA978" + uuid.uuid4().hex[:12].upper()


def generate_reference(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


def fetch_id(row: Optional[Any], key: str = "id"):
    """
    Safely extract an 'id' (or other single value) from a DB cursor.fetchone() row.

    - If row is None -> None
    - If row is mapping/dict -> return row.get(key) or (if single-column mapping) the single value
    - If row is sequence/tuple -> return row[0]
    """
    if row is None:
        return None
    try:
        if isinstance(row, dict):
            if key in row:
                return row.get(key)
            # fallback: if only one column present return it
            if len(row) == 1:
                return next(iter(row.values()))
            return None
        # sequence/tuple-like
        if isinstance(row, (list, tuple, Sequence)):
            return row[0]
        # last-resort: try attribute access
        return getattr(row, key, None)
    except Exception:
        return None


# ============================================================
# DATABASE: connection & helpers
# ============================================================


def _ensure_psycopg2_available():
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is required but not installed. Set up DATABASE_URL only after installing dependencies.")


def get_conn():
    if not settings.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured.")
    _ensure_psycopg2_available()
    return psycopg2.connect(settings.DATABASE_URL, sslmode="require")


@contextmanager
def db_cursor(commit: bool = False, dict_cursor: bool = True):
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor if dict_cursor else None)
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


def query_one(sql: str, params: Iterable = ()) -> Optional[Dict[str, Any]]:
    with db_cursor(commit=False, dict_cursor=True) as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def query_all(sql: str, params: Iterable = ()) -> List[Dict[str, Any]]:
    with db_cursor(commit=False, dict_cursor=True) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
        return rows or []


def execute(sql: str, params: Iterable = ()):
    with db_cursor(commit=True, dict_cursor=False) as cur:
        cur.execute(sql, params)
        return True


# ============================================================
# ACCOUNT HELPERS
# ============================================================


def ensure_account(cur, user_id: int, starting_balance: Decimal = Decimal("0.00")) -> None:
    cur.execute("SELECT user_id FROM accounts WHERE user_id=%s FOR UPDATE", (user_id,))
    if cur.fetchone():
        return
    cur.execute(
        """
        INSERT INTO accounts (
            user_id, deposit_account, income_account, referral_account, withdraw_account
        )
        VALUES (%s, %s, 0, 0, %s)
        ON CONFLICT (user_id) DO NOTHING
        """,
        (user_id, starting_balance, MIN_WITHDRAWAL),
    )


# ============================================================
# DATABASE INITIALIZATION
# ============================================================


def init_db():
    _ensure_psycopg2_available()
    conn = get_conn()
    cur = conn.cursor()
    try:
        # users
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(120),
                fullname VARCHAR(200) DEFAULT '',
                phone VARCHAR(50),
                password_hash TEXT,
                withdraw_password_hash TEXT,
                password TEXT,
                withdraw_password TEXT,
                referral_code VARCHAR(120),
                referred_by VARCHAR(120),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )"""
        )

        # accounts
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                deposit_account NUMERIC(14,2) NOT NULL DEFAULT 0,
                income_account NUMERIC(14,2) NOT NULL DEFAULT 0,
                referral_account NUMERIC(14,2) NOT NULL DEFAULT 0,
                withdraw_account NUMERIC(14,2) NOT NULL DEFAULT 10.00
            )"""
        )

        # plans
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS plans (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                plan_id INTEGER NOT NULL,
                plan_name VARCHAR(120) NOT NULL,
                investment_amount NUMERIC(14,2) NOT NULL,
                daily_income NUMERIC(14,2) NOT NULL,
                duration INTEGER NOT NULL,
                started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_claim_at TIMESTAMP,
                active BOOLEAN NOT NULL DEFAULT TRUE
            )"""
        )

        # transactions
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                transaction_type VARCHAR(60) NOT NULL,
                amount NUMERIC(14,2) NOT NULL,
                status VARCHAR(40) NOT NULL,
                reference VARCHAR(200),
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )"""
        )

        # withdrawal_accounts
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS withdrawal_accounts (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                account_name VARCHAR(150) NOT NULL,
                phone VARCHAR(50) NOT NULL,
                network VARCHAR(60) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )"""
        )

        # deposit_requests
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS deposit_requests (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                amount NUMERIC(14,2) NOT NULL,
                payment_number VARCHAR(80),
                screenshot TEXT,
                screenshot_data BYTEA,
                screenshot_mime VARCHAR(100),
                reference VARCHAR(200),
                status VARCHAR(40) NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )"""
        )

        # withdrawal_requests
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS withdrawal_requests (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                amount NUMERIC(14,2) NOT NULL,
                account_id INTEGER REFERENCES withdrawal_accounts(id) ON DELETE SET NULL,
                status VARCHAR(40) NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )"""
        )

        # admins
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS admins (
                id SERIAL PRIMARY KEY,
                username VARCHAR(120) UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            )"""
        )

        # invites
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS invites (
                id SERIAL PRIMARY KEY,
                token VARCHAR(120) UNIQUE NOT NULL,
                owner_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                amount NUMERIC(14,2) NOT NULL DEFAULT 0,
                approved BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )"""
        )

        # Gift-code promotional balance (kept separate from withdrawable funds)
        cur.execute("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS gift_balance NUMERIC(14,2) NOT NULL DEFAULT 0")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS gift_codes (
                id SERIAL PRIMARY KEY,
                code VARCHAR(120) UNIQUE NOT NULL,
                reward NUMERIC(14,2) NOT NULL,
                max_claims INTEGER NOT NULL CHECK (max_claims > 0),
                claims_count INTEGER NOT NULL DEFAULT 0,
                active BOOLEAN NOT NULL DEFAULT TRUE,
                created_by INTEGER REFERENCES admins(id) ON DELETE SET NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                deactivated_at TIMESTAMP
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS gift_code_claims (
                id SERIAL PRIMARY KEY,
                gift_code_id INTEGER NOT NULL REFERENCES gift_codes(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                reward NUMERIC(14,2) NOT NULL,
                claimed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(gift_code_id, user_id)
            )
            """
        )

        # Admin-created offers
        # This table is required by the existing /admin/offers routes and
        # lets active offers be loaded by the dashboard without hard-coding them.
        cur.execute(
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
            """
        )

        # Backfill missing referral codes
        cur.execute("SELECT id FROM users WHERE referral_code IS NULL OR referral_code=''")
        rows = cur.fetchall() or []
        for (uid,) in rows:
            cur.execute("UPDATE users SET referral_code=%s WHERE id=%s", (generate_referral_code(), uid))

        # Ensure every user has an account
        cur.execute(
            """
            SELECT u.id FROM users u
            LEFT JOIN accounts a ON a.user_id=u.id
            WHERE a.user_id IS NULL
            """
        )
        rows = cur.fetchall() or []
        for (uid,) in rows:
            cur.execute(
                """
                INSERT INTO accounts (user_id, deposit_account, income_account, referral_account, withdraw_account)
                VALUES (%s, %s, 0, 0, %s)
                ON CONFLICT (user_id) DO NOTHING
                """,
                (uid, STARTING_DEPOSIT_BALANCE, MIN_WITHDRAWAL),
            )

        # Ensure admin account
        admin_hash = generate_password_hash(settings.ADMIN_PASSWORD)
        cur.execute("SELECT id FROM admins WHERE username=%s", (settings.ADMIN_USERNAME,))
        if cur.fetchone():
            cur.execute("UPDATE admins SET password_hash=%s WHERE username=%s", (admin_hash, settings.ADMIN_USERNAME))
        else:
            cur.execute("INSERT INTO admins (username, password_hash) VALUES (%s, %s)", (settings.ADMIN_USERNAME, admin_hash))

        # Indexes
        indices = [
            "CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone)",
            "CREATE INDEX IF NOT EXISTS idx_users_referral ON users(referral_code)",
            "CREATE INDEX IF NOT EXISTS idx_users_referred_by ON users(referred_by)",
            "CREATE INDEX IF NOT EXISTS idx_plans_user_active ON plans(user_id,active)",
            "CREATE INDEX IF NOT EXISTS idx_deposit_requests_status ON deposit_requests(status)",
            "CREATE INDEX IF NOT EXISTS idx_withdrawals_status ON withdrawal_requests(status)",
            "CREATE INDEX IF NOT EXISTS idx_invites_token ON invites(token)",
        ]
        for stmt in indices:
            cur.execute(stmt)

        cur.execute("CREATE INDEX IF NOT EXISTS idx_gift_codes_active ON gift_codes(active)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_gift_claims_user ON gift_code_claims(user_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_gift_claims_code ON gift_code_claims(gift_code_id)")

        conn.commit()
        logger.info("Database initialized successfully.")
    except Exception:
        conn.rollback()
        logger.exception("DATABASE INITIALIZATION ERROR")
        raise
    finally:
        cur.close()
        conn.close()


# ============================================================
# AUTH & CURRENT USER HELPERS
# ============================================================


def current_user() -> Optional[Dict[str, Any]]:
    uid = session.get("user_id")
    if not uid:
        return None
    return query_one("SELECT * FROM users WHERE id=%s", (uid,))


def current_account(user_id: int) -> Dict[str, Any]:
    acc = query_one("SELECT * FROM accounts WHERE user_id=%s", (user_id,))
    if acc:
        return acc
    execute(
        """
        INSERT INTO accounts (user_id, deposit_account, income_account, referral_account, withdraw_account)
        VALUES (%s, %s, 0, 0, %s) ON CONFLICT (user_id) DO NOTHING
        """,
        (user_id, STARTING_DEPOSIT_BALANCE, MIN_WITHDRAWAL),
    )
    return query_one("SELECT * FROM accounts WHERE user_id=%s", (user_id,))


def withdrawable_balance(account: Optional[Dict[str, Any]]) -> Decimal:
    if not account:
        return Decimal("0.00")
    return money(account.get("withdraw_account")) + money(account.get("referral_account"))


def account_for_display(account: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not account:
        return account
    res = dict(account)
    res["withdraw_account"] = withdrawable_balance(account)
    res["withdrawable_balance"] = res["withdraw_account"]
    return res


@app.context_processor
def inject_user():
    return {"logged_user": current_user()}


# ============================================================
# ROUTES (kept names and behavior)
# ============================================================


@app.route("/")
def index():
    if session.get("admin_logged_in"):
        return redirect(url_for("admin_dashboard"))
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


# ---------------------------
# Registration
# ---------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    invite_code = (
        request.args.get("ref", "").strip()
        or request.form.get("referred_by", "").strip()
        or request.form.get("referral_code", "").strip()
    )
    referred_user = None
    if invite_code:
        referred_user = query_one("SELECT id, username, referral_code FROM users WHERE referral_code=%s", (invite_code,))

    if request.method == "POST":
        fullname = request.form.get("fullname", "").strip()
        username = request.form.get("username", "").strip()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        withdraw_password = request.form.get("withdraw_password", "")

        if not fullname or not username or not phone:
            flash("Please complete all required fields.", "error")
            return render_template("register.html", invite_code=invite_code)

        if len(password) < 6:
            flash("Password must contain at least 6 characters.", "error")
            return render_template("register.html", invite_code=invite_code)

        if len(withdraw_password) < 4:
            flash("Withdrawal password must contain at least 4 characters.", "error")
            return render_template("register.html", invite_code=invite_code)

        existing = query_one("SELECT id FROM users WHERE username=%s OR phone=%s", (username, phone))
        if existing:
            flash("Username or phone number already exists.", "error")
            return render_template("register.html", invite_code=invite_code)

        if invite_code and not referred_user:
            flash("Invalid referral code.", "error")
            return render_template("register.html", invite_code=invite_code)

        referral_code = generate_referral_code()
        try:
            with db_cursor(commit=True, dict_cursor=True) as cur:
                cur.execute(
                    """
                    INSERT INTO users (
                        username, fullname, phone,
                        password_hash, withdraw_password_hash,
                        referral_code, referred_by
                    )
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    RETURNING id
                    """,
                    (
                        username,
                        fullname,
                        phone,
                        generate_password_hash(password),
                        generate_password_hash(withdraw_password),
                        referral_code,
                        referred_user["referral_code"] if referred_user else None,
                    ),
                )
                row = cur.fetchone()
                new_user_id = fetch_id(row, "id")
                if not new_user_id:
                    # Defensive: if DB didn't return id, try to find inserted user by phone/username
                    logger.warning("INSERT returned no id when registering user; attempting lookup by phone/username.")
                    maybe = query_one("SELECT id FROM users WHERE phone=%s OR username=%s ORDER BY id DESC LIMIT 1", (phone, username))
                    new_user_id = fetch_id(maybe, "id")
                    if not new_user_id:
                        raise RuntimeError("Could not determine new user id after insert.")
                cur.execute(
                    """
                    INSERT INTO accounts (
                        user_id, deposit_account, income_account, referral_account, withdraw_account
                    ) VALUES (%s,%s,0,0,%s) ON CONFLICT (user_id) DO NOTHING
                    """,
                    (new_user_id, STARTING_DEPOSIT_BALANCE, MIN_WITHDRAWAL),
                )
        except Exception:
            logger.exception("REGISTRATION ERROR")
            flash("Unable to register at this time.", "error")
            return render_template("register.html", invite_code=invite_code)

        # Keep user experience: after registering, redirect to login page
        flash("Registration successful. Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html", invite_code=invite_code)


# ---------------------------
# Login / Logout
# ---------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")

        if not phone or not password:
            flash("Please enter your phone number and password.", "error")
            return render_template("login.html")

        user = query_one("SELECT * FROM users WHERE phone=%s", (phone,))
        valid = False
        used_legacy_password = False

        if user:
            stored_hash = user.get("password_hash")
            if stored_hash:
                try:
                    valid = check_password_hash(stored_hash, password)
                except Exception:
                    valid = False
            elif user.get("password") is not None:
                valid = user.get("password") == password
                used_legacy_password = valid

        if valid:
            # Upgrade legacy plaintext password to hashed password on first login
            if used_legacy_password:
                execute("UPDATE users SET password_hash=%s, password=NULL WHERE id=%s", (generate_password_hash(password), user["id"]))
            session.clear()
            session["user_id"] = user["id"]
            return redirect(url_for("dashboard"))

        flash("Invalid phone number or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------
# Dashboard
# ---------------------------
@app.route("/dashboard")
def dashboard():
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    account = account_for_display(current_account(user["id"]))
    try:
        offers = query_all(
            "SELECT * FROM admin_offer WHERE active=TRUE ORDER BY id DESC"
        )
    except Exception:
        # Keep the dashboard available even if an older database has not yet
        # created the admin_offer table; init_db will create it on startup.
        logger.exception("DASHBOARD OFFERS QUERY ERROR")
        offers = []
    return render_template(
        "dashboard.html",
        user=user,
        account=account,
        plans=PLANS,
        offers=offers,
    )


@app.route('/buy_plan/<int:plan_id>', methods=['GET', 'POST'])
@login_required
def buy_plan(plan_id):
    user_id = int(current_user.get_id())
    plan = PLANS.get(plan_id)
    if not plan:
        abort(404)

    account = query_one("SELECT * FROM accounts WHERE user_id = %s", (user_id,))
    
    if request.method == 'POST':
        # check balance
        deposit = money(account.get('deposit_account') if account else 0)
        if deposit < plan['investment']:
            return render_template('insufficient_balance.html', plan=plan, account=account)

        # Deduct balance
        execute("UPDATE accounts SET deposit_account = deposit_account - %s WHERE user_id = %s", (str(plan['investment']), user_id))
        
        # SAVE IT - This was missing before!
        execute("""
            CREATE TABLE IF NOT EXISTS user_plans (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                plan_id INTEGER NOT NULL,
                investment DECIMAL(12,2),
                daily DECIMAL(12,2),
                status VARCHAR(20) DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        execute("INSERT INTO user_plans (user_id, plan_id, investment, daily, status) VALUES (%s, %s, %s, %s, 'active')",
                (user_id, plan_id, str(plan['investment']), str(plan['daily'])))

        flash(f"Successfully bought {plan['name']}!")
        return redirect(url_for('my_plan'))

    return render_template('confirm_plan.html', plan=plan, account=account, plan_id=plan_id)

@app.route('/confirm_offer/<int:offer_id>', methods=['GET', 'POST'])
@login_required
def confirm_offer(offer_id):
    user_id = int(current_user.get_id())
    offer = PLANS.get(offer_id)  # you use same PLANS dict for offers
    if not offer:
        abort(404)

    account = query_one("SELECT * FROM accounts WHERE user_id = %s", (user_id,))

    if request.method == 'POST':
        deposit = money(account.get('deposit_account') if account else 0)
        if deposit < offer['investment']:
            return render_template('insufficient_balance.html', offer=offer, account=account)

        execute("UPDATE accounts SET deposit_account = deposit_account - %s WHERE user_id = %s", (str(offer['investment']), user_id))

        # SAVE OFFER - This was missing!
        execute("""
            CREATE TABLE IF NOT EXISTS user_offers (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                offer_id INTEGER NOT NULL,
                investment DECIMAL(12,2),
                daily DECIMAL(12,2),
                status VARCHAR(20) DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        execute("INSERT INTO user_offers (user_id, offer_id, investment, daily, status) VALUES (%s, %s, %s, %s, 'active')",
                (user_id, offer_id, str(offer['investment']), str(offer['daily'])))

        flash(f"Successfully bought {offer['name']}!")
        return redirect(url_for('my_plan'))

    return render_template('confirm_offer.html', offer=offer, account=account, offer_id=offer_id)

@app.route('/my_plan')
@login_required
def my_plan():
    user_id = int(current_user.get_id())
    account = query_one("SELECT * FROM accounts WHERE user_id = %s", (user_id,))

    # Ensure tables exist
    execute("CREATE TABLE IF NOT EXISTS user_plans (id SERIAL PRIMARY KEY, user_id INTEGER, plan_id INTEGER, investment DECIMAL(12,2), daily DECIMAL(12,2), status VARCHAR(20) DEFAULT 'active', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    execute("CREATE TABLE IF NOT EXISTS user_offers (id SERIAL PRIMARY KEY, user_id INTEGER, offer_id INTEGER, investment DECIMAL(12,2), daily DECIMAL(12,2), status VARCHAR(20) DEFAULT 'active', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")

    user_plans = query_all("SELECT * FROM user_plans WHERE user_id = %s ORDER BY created_at DESC", (user_id,))
    user_offers = query_all("SELECT * FROM user_offers WHERE user_id = %s ORDER BY created_at DESC", (user_id,))

    investments = []
    for p in user_plans or []:
        info = PLANS.get(int(p['plan_id'])) if p.get('plan_id') in PLANS else None
        investments.append({
            'type': 'PLAN',
            'name': info['name'] if info else f"VIP {p['plan_id']}",
            'investment': p['investment'],
            'daily': p['daily'],
            'duration': info['duration'] if info else 180,
            'status': p['status'],
            'bought_at': p['created_at']
        })
    for o in user_offers or []:
        info = PLANS.get(int(o['offer_id'])) if o.get('offer_id') in PLANS else None
        investments.append({
            'type': 'OFFER',
            'name': info['name'] if info else f"Offer {o['offer_id']}",
            'investment': o['investment'],
            'daily': o['daily'],
            'duration': info['duration'] if info else 180,
            'status': o['status'],
            'bought_at': o['created_at']
        })

    investments.sort(key=lambda x: str(x['bought_at']), reverse=True)
    total_invested = sum([money(i['investment']) for i in investments])
    total_daily = sum([money(i['daily']) for i in investments])

    return render_template('my_plan.html', investments=investments, account=account, total_invested=total_invested, total_daily=total_daily)


                
# ---------------------------
# Deposit
# ---------------------------
ALLOWED_IMAGE_MIMES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


@app.route("/deposit", methods=["GET", "POST"])
def deposit():
    user = current_user()
    if not user:
        return redirect(url_for("login"))

    if request.method == "POST":
        amount = parse_amount(request.form.get("amount", "0"))
        phone = request.form.get("phone", "").strip()
        payment_number = request.form.get("payment_number", "0257425844").strip()
        screenshot = request.files.get("screenshot")
        if amount is None:
            flash("Please enter a valid deposit amount.", "error")
            return render_template("deposit.html")
        if amount < MIN_DEPOSIT:
            flash(f"Minimum demo deposit is GHS {MIN_DEPOSIT:.2f}.", "error")
            return render_template("deposit.html")
        if not phone:
            flash("Please enter your phone number.", "error")
            return render_template("deposit.html")
        if not screenshot or not screenshot.filename:
            flash("Please upload your payment screenshot.", "error")
            return render_template("deposit.html")

        filename = screenshot.filename.lower()
        mime_type = next((m for ext, m in ALLOWED_IMAGE_MIMES.items() if filename.endswith(ext)), None)
        if not mime_type:
            flash("Only PNG/JPG/JPEG/WEBP allowed.", "error")
            return render_template("deposit.html")

        data = screenshot.read()
        if not data:
            flash("Uploaded screenshot is empty.", "error")
            return render_template("deposit.html")
        if len(data) > app.config["MAX_CONTENT_LENGTH"]:
            flash("Screenshot is too large. Maximum 5MB.", "error")
            return render_template("deposit.html")

        reference = generate_reference("DEP")
        try:
            with db_cursor(commit=True, dict_cursor=True) as cur:
                cur.execute(
                    """
                    INSERT INTO deposit_requests (
                        user_id, amount, payment_number, screenshot, screenshot_data, screenshot_mime, reference, status
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,'pending') RETURNING id
                    """,
                    (user["id"], amount, payment_number, screenshot.filename, psycopg2.Binary(data) if psycopg2 else None, mime_type, reference),
                )
                dep_row = cur.fetchone()
                dep_id = fetch_id(dep_row, "id")
                if not dep_id:
                    logger.warning("Deposit insert returned no id; continuing but admin will need to inspect.")
                cur.execute(
                    """
                    INSERT INTO transactions (user_id, transaction_type, amount, status, reference, description)
                    VALUES (%s,'deposit',%s,'pending',%s,%s)
                    """,
                    (user["id"], amount, reference, f"Demo deposit request #{dep_id}"),
                )
            flash("Deposit request submitted successfully. Please wait for admin review.", "success")
        except Exception:
            logger.exception("DEPOSIT SUBMISSION ERROR")
            flash("Could not submit deposit request.", "error")
            return render_template("deposit.html")
        return redirect(url_for("transaction_history"))

    return render_template("deposit.html")


@app.route("/admin/deposit-image/<int:deposit_id>")
def admin_deposit_image(deposit_id: int):
    if not admin_required():
        return redirect(url_for("admin_login"))
    deposit = query_one("SELECT screenshot_data, screenshot_mime FROM deposit_requests WHERE id=%s", (deposit_id,))
    if not deposit or not deposit.get("screenshot_data"):
        abort(404)
    return send_file(BytesIO(bytes(deposit["screenshot_data"])), mimetype=deposit.get("screenshot_mime") or "image/jpeg", as_attachment=False, download_name=f"deposit_{deposit_id}.jpg")


@app.route("/uploads/deposits/<path:filename>")
def uploaded_deposit_image(filename: str):
    if not admin_required():
        return redirect(url_for("admin_login"))
    deposit = query_one(
        "SELECT screenshot_data, screenshot_mime FROM deposit_requests WHERE screenshot=%s ORDER BY id DESC LIMIT 1",
        (filename,),
    )
    if not deposit or not deposit.get("screenshot_data"):
        abort(404)
    return send_file(BytesIO(bytes(deposit["screenshot_data"])), mimetype=deposit.get("screenshot_mime") or "image/jpeg", as_attachment=False, download_name=filename)


# ---------------------------
# Withdraw & Bind
# ---------------------------
@app.route("/withdraw")
def withdraw():
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    account = account_for_display(current_account(user["id"]))
    accounts = query_all("SELECT * FROM withdrawal_accounts WHERE user_id=%s ORDER BY id DESC", (user["id"],))
    return render_template("withdraw.html", account=account, accounts=accounts)


@app.route("/bind_account", methods=["GET", "POST"])
def bind_account():
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    if request.method == "POST":
        account_name = request.form.get("account_name", "").strip()
        phone = request.form.get("phone", "").strip()
        network = request.form.get("network", "").strip()
        if not account_name or not phone or not network:
            flash("Please complete all account details.", "error")
        else:
            execute("INSERT INTO withdrawal_accounts (user_id, account_name, phone, network) VALUES (%s,%s,%s,%s)", (user["id"], account_name, phone, network))
            flash("Withdrawal account saved.", "success")
    accounts = query_all("SELECT * FROM withdrawal_accounts WHERE user_id=%s ORDER BY id DESC", (user["id"],))
    return render_template("bind_account.html", accounts=accounts)


@app.route("/request_withdrawal", methods=["POST"])
def request_withdrawal():
    """
    Rules enforced:
    - User must be logged in.
    - The requested amount must be >= MIN_WITHDRAWAL.
    - User must have at least one active plan to request a withdrawal.
    - Withdrawal password must be correct.
    - A bound withdrawal account must exist.
    - Balance is deducted (withdraw_account first, then referral_account).
    """
    user = current_user()
    if not user:
        return redirect(url_for("login"))

    # Require user to have at least one active plan
    active_plan_row = query_one("SELECT COUNT(*) AS count FROM plans WHERE user_id=%s AND active=TRUE", (user["id"],))
    active_plan_count = int(active_plan_row["count"]) if active_plan_row and active_plan_row.get("count") is not None else 0
    if active_plan_count == 0:
        flash("You must have at least one active plan to request a withdrawal.", "error")
        return redirect(url_for("withdraw"))

    amount = parse_amount(request.form.get("amount", "0"))
    password = request.form.get("password", "")
    account_id = request.form.get("account_id")
    if amount is None or amount < MIN_WITHDRAWAL:
        flash(f"Minimum demo withdrawal is GHS {MIN_WITHDRAWAL:.2f}.", "error")
        return redirect(url_for("withdraw"))

    stored_hash = user.get("withdraw_password_hash")
    valid = False
    if stored_hash:
        try:
            valid = check_password_hash(stored_hash, password)
        except Exception:
            valid = False
    elif user.get("withdraw_password") is not None:
        valid = user.get("withdraw_password") == password

    if not valid:
        flash("Invalid withdrawal password.", "error")
        return redirect(url_for("withdraw"))

    if account_id:
        selected = query_one("SELECT id FROM withdrawal_accounts WHERE id=%s AND user_id=%s", (account_id, user["id"]))
    else:
        selected = query_one("SELECT id FROM withdrawal_accounts WHERE user_id=%s ORDER BY id DESC LIMIT 1", (user["id"],))

    if not selected:
        flash("Please bind a withdrawal account first.", "error")
        return redirect(url_for("bind_account"))

    try:
        with db_cursor(commit=True, dict_cursor=True) as cur:
            ensure_account(cur, user["id"], STARTING_DEPOSIT_BALANCE)
            cur.execute("SELECT withdraw_account, referral_account FROM accounts WHERE user_id=%s FOR UPDATE", (user["id"],))
            row = cur.fetchone() or {}
            withdraw_balance = money(row.get("withdraw_account"))
            referral_balance = money(row.get("referral_account"))
            total_available = withdraw_balance + referral_balance
            if total_available < amount:
                raise ValueError("Insufficient withdrawal/referral balance.")

            from_withdraw = min(withdraw_balance, amount)
            from_referral = amount - from_withdraw

            cur.execute(
                "UPDATE accounts SET withdraw_account = COALESCE(withdraw_account,0) - %s, referral_account = COALESCE(referral_account,0) - %s WHERE user_id = %s",
                (from_withdraw, from_referral, user["id"]),
            )

            cur.execute(
                "INSERT INTO withdrawal_requests (user_id, amount, account_id, status) VALUES (%s, %s, %s, 'pending') RETURNING id",
                (user["id"], amount, selected["id"]),
            )
            withdrawal_row = cur.fetchone()
            withdrawal_id = fetch_id(withdrawal_row, "id")

            reference = generate_reference("WDR")
            cur.execute(
                "INSERT INTO transactions (user_id, transaction_type, amount, status, reference, description) VALUES (%s, %s, %s, %s, %s, %s)",
                (user["id"], "withdrawal", amount, "pending", reference, f"Withdrawal request #{withdrawal_id}"),
            )

        flash("Withdrawal request submitted successfully.", "success")
    except ValueError as ve:
        flash(str(ve), "error")
    except Exception:
        logger.exception("WITHDRAWAL REQUEST ERROR")
        flash("Unable to submit the withdrawal.", "error")
    return redirect(url_for("transaction_history"))


# ---------------------------
# Transactions & Team
# ---------------------------
@app.route("/transaction_history")
def transaction_history():
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    transactions = query_all("SELECT * FROM transactions WHERE user_id=%s ORDER BY created_at DESC, id DESC", (user["id"],))
    return render_template("transaction_history.html", transactions=transactions)


@app.route("/team")
def team():
    user = current_user()

    if not user:
        return redirect(url_for("login"))

    account = current_account(user["id"])

    referral_income = money(
        account["referral_account"]
        if account
        else Decimal("0.00")
    )

    # ==========================================
    # SITE / REFERRAL LINK
    # ==========================================

    site_url = "https://infinix-3afi.onrender.com"

    referral_link = (
        f"{site_url}/register?ref={user['referral_code']}"
    )

    # ==========================================
    # TEAM RULES
    # ==========================================

    LEVEL1_LIMIT = 5
    LEVEL2_PER_LEVEL1 = 2
    LEVEL3_LIMIT = 300

    LEVEL1_RATE = 20
    LEVEL2_RATE = 3
    LEVEL3_RATE = 1

    # ==========================================
    # LEVEL 1
    # Direct referrals
    # ==========================================

    level1_users = query_all(
        """
        SELECT
            id,
            username,
            fullname,
            phone,
            referral_code,
            referred_by,
            created_at
        FROM users
        WHERE referred_by=%s
        ORDER BY created_at ASC, id ASC
        LIMIT %s
        """,
        (
            user["referral_code"],
            LEVEL1_LIMIT
        )
    )

    # ==========================================
    # LEVEL 2
    # Maximum 2 members per Level 1 member
    # ==========================================

    level1_codes = [
        member["referral_code"]
        for member in level1_users
        if member.get("referral_code")
    ]

    level2_users = []

    if level1_codes:

        level2_users = query_all(
            """
            SELECT
                id,
                username,
                fullname,
                phone,
                referral_code,
                referred_by,
                created_at
            FROM users
            WHERE referred_by = ANY(%s)
            ORDER BY created_at ASC, id ASC
            """,
            (level1_codes,)
        )

        # Maximum 2 Level 2 members for each Level 1 member
        limited_level2 = []

        for level1_code in level1_codes:

            count = 0

            for member in level2_users:

                if member["referred_by"] == level1_code:

                    if count < LEVEL2_PER_LEVEL1:

                        member["referral_level"] = 2
                        limited_level2.append(member)

                        count += 1

        level2_users = limited_level2

    # ==========================================
    # LEVEL 3
    # Maximum 300 members
    # ==========================================

    level2_codes = [
        member["referral_code"]
        for member in level2_users
        if member.get("referral_code")
    ]

    level3_users = []

    if level2_codes:

        level3_users = query_all(
            """
            SELECT
                id,
                username,
                fullname,
                phone,
                referral_code,
                referred_by,
                created_at
            FROM users
            WHERE referred_by = ANY(%s)
            ORDER BY created_at ASC, id ASC
            LIMIT %s
            """,
            (
                level2_codes,
                LEVEL3_LIMIT
            )
        )

    # ==========================================
    # ADD LEVEL INFORMATION
    # ==========================================

    members = []

    for member in level1_users:

        member["referral_level"] = 1

        members.append(member)

    for member in level2_users:

        member["referral_level"] = 2

        members.append(member)

    for member in level3_users:

        member["referral_level"] = 3

        members.append(member)

    # ==========================================
    # CALCULATE INVESTMENT FOR EACH MEMBER
    # ==========================================

    for member in members:

        inv = query_one(
            """
            SELECT
                COALESCE(
                    SUM(investment_amount),
                    0
                ) AS total_investment
            FROM plans
            WHERE user_id=%s
            """,
            (member["id"],)
        )

        member["invest_amount"] = money(
            inv["total_investment"]
            if inv
            else Decimal("0.00")
        )

    # ==========================================
    # TEAM COUNTS
    # ==========================================

    level1_count = len(level1_users)
    level2_count = len(level2_users)
    level3_count = len(level3_users)

    total_team = (
        level1_count
        + level2_count
        + level3_count
    )

    # ==========================================
    # SEND DATA TO TEMPLATE
    # ==========================================

    return render_template(
        "team.html",
        user=user,
        members=members,

        total_team=total_team,

        referral_income=referral_income,

        referral_code=user["referral_code"],
        referral_link=referral_link,
        site_url=site_url,

        level1_count=level1_count,
        level2_count=level2_count,
        level3_count=level3_count,

        level1_limit=LEVEL1_LIMIT,
        level2_per_level1=LEVEL2_PER_LEVEL1,
        level3_limit=LEVEL3_LIMIT,

        level1_rate=LEVEL1_RATE,
        level2_rate=LEVEL2_RATE,
        level3_rate=LEVEL3_RATE
    )


@app.route("/team_members")
def team_members():
    user = current_user()

    if not user:
        return redirect(url_for("login"))


    # ==========================================
    # LEVEL 1
    # ==========================================

    level1_users = query_all(
        """
        SELECT
            id,
            username,
            fullname,
            phone,
            referral_code,
            referred_by,
            created_at
        FROM users
        WHERE referred_by=%s
        ORDER BY created_at ASC, id ASC
        LIMIT 5
        """,
        (user["referral_code"],)
    )

    for member in level1_users:
        member["referral_level"] = 1


    # ==========================================
    # LEVEL 2
    # ==========================================

    level2_users = []

    for level1_member in level1_users:

        children = query_all(
            """
            SELECT
                id,
                username,
                fullname,
                phone,
                referral_code,
                referred_by,
                created_at
            FROM users
            WHERE referred_by=%s
            ORDER BY created_at ASC, id ASC
            LIMIT 2
            """,
            (level1_member["referral_code"],)
        )

        for member in children:
            member["referral_level"] = 2
            level2_users.append(member)


    # ==========================================
    # LEVEL 3
    # ==========================================

    level2_codes = [
        member["referral_code"]
        for member in level2_users
        if member.get("referral_code")
    ]

    level3_users = []

    if level2_codes:

        level3_users = query_all(
            """
            SELECT
                id,
                username,
                fullname,
                phone,
                referral_code,
                referred_by,
                created_at
            FROM users
            WHERE referred_by = ANY(%s)
            ORDER BY created_at ASC, id ASC
            LIMIT 300
            """,
            (level2_codes,)
        )

        for member in level3_users:
            member["referral_level"] = 3


    # ==========================================
    # COMBINE ALL MEMBERS
    # ==========================================

    members = []

    members.extend(level1_users)
    members.extend(level2_users)
    members.extend(level3_users)


    # ==========================================
    # GET INVESTMENT TOTAL FOR EACH MEMBER
    # ==========================================

    for member in members:

        investment = query_one(
            """
            SELECT
                COALESCE(
                    SUM(investment_amount),
                    0
                ) AS total_investment
            FROM plans
            WHERE user_id=%s
            """,
            (member["id"],)
        )

        member["invest_amount"] = money(
            investment["total_investment"]
            if investment
            else Decimal("0.00")
        )


    # ==========================================
    # COUNTS
    # ==========================================

    level1_count = len(level1_users)
    level2_count = len(level2_users)
    level3_count = len(level3_users)

    total_team = (
        level1_count
        + level2_count
        + level3_count
    )


    # ==========================================
    # RENDER SEPARATE PAGE
    # ==========================================

    return render_template(
        "team_members.html",

        user=user,

        members=members,

        total_team=total_team,

        level1_count=level1_count,
        level2_count=level2_count,
        level3_count=level3_count,

        level1_limit=5,
        level2_limit=2,
        level3_limit=300
    )





# ---------------------------
# Support/Profile/Passwords
# ---------------------------
@app.route("/support")
@app.route("/service")
def support():
    return render_template("support.html")


@app.route("/profile")
def profile():
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    account = current_account(user["id"])
    return render_template(
        "profile.html",
        user=user,
        deposit_balance=account["deposit_account"],
        withdraw_balance=withdrawable_balance(account),
        income_balance=account["income_account"],
        referral_balance=account["referral_account"],
    )


@app.route("/admin_change_password", methods=["GET", "POST"])
@app.route("/change_login_password", methods=["GET", "POST"])
def admin_change_password():
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        valid = False
        if user.get("password_hash"):
            try:
                valid = check_password_hash(user["password_hash"], current_password)
            except Exception:
                valid = False
        else:
            valid = user.get("password") == current_password
        if not valid:
            flash("Current password is incorrect.", "error")
            return render_template("change_login_password.html")
        if len(new_password) < 6:
            flash("New password must contain at least 6 characters.", "error")
            return render_template("change_login_password.html")
        if new_password != confirm_password:
            flash("New passwords do not match.", "error")
            return render_template("change_login_password.html")
        execute("UPDATE users SET password_hash=%s, password=NULL WHERE id=%s", (generate_password_hash(new_password), user["id"]))
        flash("Login password changed successfully.", "success")
        return redirect(url_for("profile"))
    return render_template("change_login_password.html")


@app.route("/admin_withdraw_password", methods=["GET", "POST"])
@app.route("/change_withdraw_password", methods=["GET", "POST"])
def admin_change_withdraw_password():
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        valid = False
        if user.get("withdraw_password_hash"):
            try:
                valid = check_password_hash(user["withdraw_password_hash"], current_password)
            except Exception:
                valid = False
        else:
            valid = user.get("withdraw_password") == current_password
        if not valid:
            flash("Current withdrawal password is incorrect.", "error")
            return render_template("change_withdraw_password.html")
        if len(new_password) < 4:
            flash("New withdrawal password must contain at least 4 characters.", "error")
            return render_template("change_withdraw_password.html")
        if new_password != confirm_password:
            flash("New passwords do not match.", "error")
            return render_template("change_withdraw_password.html")
        execute("UPDATE users SET withdraw_password_hash=%s, withdraw_password=NULL WHERE id=%s", (generate_password_hash(new_password), user["id"]))
        flash("Withdrawal password changed successfully.", "success")
        return redirect(url_for("profile"))
    return render_template("change_withdraw_password.html")


# ---------------------------
# Admin auth & helpers
# ---------------------------
def admin_required() -> bool:
    return session.get("admin_logged_in") is True


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        admin = query_one("SELECT * FROM admins WHERE username=%s", (username,))
        valid = False
        if admin:
            try:
                valid = check_password_hash(admin["password_hash"], password)
            except Exception:
                valid = False
        if valid:
            session.clear()
            session["admin_logged_in"] = True
            session["admin_id"] = admin["id"]
            # Removed success flash for admin login per earlier change.
            return redirect(url_for("admin_dashboard"))
        # keep error feedback for bad credentials
        flash("Invalid administrator credentials.", "error")
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


# ---------------------------
# Admin dashboard & management
# ---------------------------
@app.route("/admin/dashboard")
def admin_dashboard():
    if not admin_required():
        return redirect(url_for("admin_login"))
    total_users = query_one("SELECT COUNT(*) AS count FROM users")["count"]
    pending_deposits = query_one("SELECT COUNT(*) AS count FROM deposit_requests WHERE status='pending'")["count"]
    pending_withdrawals = query_one("SELECT COUNT(*) AS count FROM withdrawal_requests WHERE status='pending'")["count"]
    invites = query_all(
        """
        SELECT i.*, u.username AS owner_username
        FROM invites i
        LEFT JOIN users u ON u.id=i.owner_id
        ORDER BY i.created_at DESC
        LIMIT 100
        """
    )
    return render_template("admin_dashboard.html", total_users=total_users, pending_deposits=pending_deposits, pending_withdrawals=pending_withdrawals, invites=invites)


@app.route("/admin_users")
@app.route("/admin/users")
def admin_users():
    if not admin_required():
        return redirect(url_for("admin_login"))
    users = query_all(
        """
        SELECT u.*, a.deposit_account, a.income_account, a.referral_account, a.withdraw_account
        FROM users u LEFT JOIN accounts a ON a.user_id=u.id
        ORDER BY u.id DESC
        """
    )
    return render_template("admin_users.html", users=users)


@app.route("/admin/user/<int:user_id>", methods=["GET", "POST"])
def admin_manage_user(user_id: int):
    if not admin_required():
        return redirect(url_for("admin_login"))
    user = query_one("SELECT * FROM users WHERE id=%s", (user_id,))
    if not user:
        return "User not found", 404

    if request.method == "POST":
        action = request.form.get("action", "")
        # Map template action names to existing operations
        # Template uses 'update_password' and 'update_withdraw_password'
        if action == "update_password":
            action = "change_login_password"
        if action == "update_withdraw_password":
            action = "change_withdraw_password"

        balance_actions = {
            "add_deposit": "deposit_account",
            "deduct_deposit": "deposit_account",
            "add_withdraw": "withdraw_account",
            "deduct_withdraw": "withdraw_account",
            "add_income": "income_account",
            "deduct_income": "income_account",
            "add_referral": "referral_account",
            "deduct_referral": "referral_account",
        }
        if action in balance_actions:
            amount = parse_amount(request.form.get("amount", "0"))
            if amount is None:
                # keep error feedback
                flash("Amount must be greater than zero.", "error")
                return redirect(url_for("admin_manage_user", user_id=user_id))
            column = balance_actions[action]
            is_add = action.startswith("add_")
            try:
                with db_cursor(commit=True, dict_cursor=True) as cur:
                    ensure_account(cur, user_id, STARTING_DEPOSIT_BALANCE)
                    if is_add:
                        cur.execute(f"UPDATE accounts SET {column} = COALESCE({column}, 0) + %s WHERE user_id=%s", (amount, user_id))
                    else:
                        cur.execute(f"UPDATE accounts SET {column} = GREATEST(0, COALESCE({column}, 0) - %s) WHERE user_id=%s", (amount, user_id))
                    cur.execute(
                        """
                        INSERT INTO transactions (user_id, transaction_type, amount, status, reference, description)
                        VALUES (%s, 'admin_balance_adjustment', %s, 'successful', %s, %s)
                        """,
                        (user_id, amount, generate_reference("ADM"), "Admin adjustment: " + action),
                    )
                # Remove success flash for admin action per request; log instead
                logger.info("Admin %s adjusted %s for user %s by %s", session.get("admin_id"), column, user_id, amount)
            except Exception:
                logger.exception("ADMIN BALANCE ACTION FAILED")
                flash("Unable to update balance.", "error")
            return redirect(url_for("admin_manage_user", user_id=user_id))

        if action == "change_login_password":
            new_password = request.form.get("new_password", "")
            if len(new_password) < 6:
                flash("Login password must contain at least 6 characters.", "error")
            else:
                new_hash = generate_password_hash(new_password)
                execute("UPDATE users SET password_hash=%s, password=NULL WHERE id=%s", (new_hash, user_id))
                logger.info("Admin %s set login password for user %s", session.get("admin_id"), user_id)
                # Removed flash success
            return redirect(url_for("admin_manage_user", user_id=user_id))

        if action == "change_withdraw_password":
            new_password = request.form.get("new_password", "")
            if len(new_password) < 4:
                flash("Withdrawal password must contain at least 4 characters.", "error")
            else:
                new_hash = generate_password_hash(new_password)
                execute("UPDATE users SET withdraw_password_hash=%s, withdraw_password=NULL WHERE id=%s", (new_hash, user_id))
                logger.info("Admin %s set withdrawal password for user %s", session.get("admin_id"), user_id)
                # Removed flash success
            return redirect(url_for("admin_manage_user", user_id=user_id))

        if action == "update_account":
            account_id = request.form.get("account_id")
            account_name = request.form.get("account_name", "").strip()
            phone = request.form.get("phone", "").strip()
            network = request.form.get("network", "").strip()
            if not account_id or not account_name or not phone or not network:
                flash("Please complete all withdrawal account details.", "error")
            else:
                execute("UPDATE withdrawal_accounts SET account_name=%s, phone=%s, network=%s WHERE id=%s AND user_id=%s", (account_name, phone, network, account_id, user_id))
                logger.info("Admin %s updated withdrawal account %s for user %s", session.get("admin_id"), account_id, user_id)
                # Removed flash success
            return redirect(url_for("admin_manage_user", user_id=user_id))

        if action == "delete_account":
            execute("DELETE FROM withdrawal_accounts WHERE id=%s AND user_id=%s", (request.form.get("account_id"), user_id))
            logger.info("Admin %s deleted withdrawal account %s for user %s", session.get("admin_id"), request.form.get("account_id"), user_id)
            # Removed flash success
            return redirect(url_for("admin_manage_user", user_id=user_id))

        flash("Unknown admin action.", "error")
        return redirect(url_for("admin_manage_user", user_id=user_id))

    account = current_account(user_id)
    withdrawal_accounts = query_all("SELECT * FROM withdrawal_accounts WHERE user_id=%s ORDER BY id DESC", (user_id,))
    return render_template("admin_manage_user.html", user=user, account=account, withdrawal_accounts=withdrawal_accounts)


@app.route("/admin/bind_accounts")
@app.route("/admin_bind_accounts")
def admin_bind_accounts():
    if not admin_required():
        return redirect(url_for("admin_login"))
    accounts = query_all(
        """
        SELECT wa.*, u.username, u.phone AS user_phone
        FROM withdrawal_accounts wa JOIN users u ON u.id=wa.user_id
        ORDER BY wa.created_at DESC, wa.id DESC
        """
    )
    return render_template("admin_bind_accounts.html", accounts=accounts)


@app.route("/admin/deposits")
def admin_deposits():
    if not admin_required():
        return redirect(url_for("admin_login"))
    deposits = query_all(
        """
        SELECT d.id, d.user_id, d.amount, d.payment_number, d.screenshot, d.screenshot_mime, d.reference, d.status, d.created_at,
               u.username, u.fullname, u.phone
        FROM deposit_requests d JOIN users u ON u.id=d.user_id
        ORDER BY d.created_at DESC, d.id DESC
        """
    )
    return render_template("admin_deposit.html", deposits=deposits)


@app.route("/admin/deposit/<int:deposit_id>/<action>", methods=["POST"])
def admin_deposit_action(deposit_id: int, action: str):
    if not admin_required():
        return redirect(url_for("admin_login"))
    if action not in {"approve", "reject"}:
        flash("Invalid deposit action.", "error")
        return redirect(url_for("admin_deposits"))
    try:
        with db_cursor(commit=True, dict_cursor=True) as cur:
            cur.execute("SELECT id, user_id, amount, reference, status FROM deposit_requests WHERE id=%s FOR UPDATE", (deposit_id,))
            deposit = cur.fetchone()
            if not deposit:
                flash("Deposit request not found.", "error")
                return redirect(url_for("admin_deposits"))
            if deposit["status"] != "pending":
                flash("This deposit has already been reviewed.", "error")
                return redirect(url_for("admin_deposits"))
            user_id = deposit["user_id"]
            amount = money(deposit["amount"])
            reference = deposit.get("reference")
            if action == "approve":
                ensure_account(cur, user_id, Decimal("0.00"))
                cur.execute("UPDATE accounts SET deposit_account = COALESCE(deposit_account,0) + %s WHERE user_id=%s", (amount, user_id))
                cur.execute("UPDATE deposit_requests SET status='approved' WHERE id=%s", (deposit_id,))
                cur.execute("UPDATE transactions SET status='successful' WHERE user_id=%s AND transaction_type='deposit' AND reference=%s AND status='pending'", (user_id, reference))
                message = f"Demo deposit of GHS {amount:.2f} approved successfully."
            else:
                cur.execute("UPDATE deposit_requests SET status='rejected' WHERE id=%s", (deposit_id,))
                cur.execute("UPDATE transactions SET status='failed' WHERE user_id=%s AND transaction_type='deposit' AND reference=%s AND status='pending'", (user_id, reference))
                message = f"Demo deposit of GHS {amount:.2f} rejected."
        # Do not flash success to admin UI; just log action
        logger.info("Admin %s processed deposit %s: %s", session.get("admin_id"), deposit_id, message)
    except Exception:
        logger.exception("ADMIN DEPOSIT ACTION ERROR")
        flash("Unable to process the deposit.", "error")
    return redirect(url_for("admin_deposits"))


@app.route("/admin/withdrawals")
def admin_withdrawals():
    if not admin_required():
        return redirect(url_for("admin_login"))
    withdrawals = query_all(
        """
        SELECT w.*, u.username, u.fullname, u.phone, wa.account_name, wa.phone AS account_phone, wa.network
        FROM withdrawal_requests w JOIN users u ON u.id=w.user_id LEFT JOIN withdrawal_accounts wa ON wa.id=w.account_id
        ORDER BY w.created_at DESC, w.id DESC
        """
    )
    return render_template("admin_withdraw.html", withdrawals=withdrawals)


@app.route("/admin/withdraw/<int:withdrawal_id>/<action>", methods=["POST"])
def admin_withdraw_action(withdrawal_id: int, action: str):
    if not admin_required():
        return redirect(url_for("admin_login"))
    if action not in {"approve", "reject"}:
        flash("Invalid withdrawal action.", "error")
        return redirect(url_for("admin_withdrawals"))
    try:
        with db_cursor(commit=True, dict_cursor=True) as cur:
            cur.execute("SELECT * FROM withdrawal_requests WHERE id=%s FOR UPDATE", (withdrawal_id,))
            withdrawal = cur.fetchone()
            if not withdrawal:
                flash("Withdrawal request not found.", "error")
                return redirect(url_for("admin_withdrawals"))
            if withdrawal["status"] != "pending":
                flash("Withdrawal request is no longer pending.", "error")
                return redirect(url_for("admin_withdrawals"))
            user_id = withdrawal["user_id"]
            amount = money(withdrawal["amount"])
            if action == "approve":
                cur.execute("UPDATE withdrawal_requests SET status='approved' WHERE id=%s", (withdrawal_id,))
                cur.execute(
                    """
                    UPDATE transactions
                    SET status='successful'
                    WHERE id = (
                        SELECT id FROM transactions
                        WHERE user_id=%s AND transaction_type='withdrawal' AND amount=%s AND status='pending'
                        ORDER BY created_at DESC, id DESC LIMIT 1
                    )
                    """,
                    (user_id, amount),
                )
                message = "Withdrawal approved successfully."
            else:
                ensure_account(cur, user_id, Decimal("0.00"))
                cur.execute("UPDATE accounts SET withdraw_account = COALESCE(withdraw_account,0) + %s WHERE user_id=%s", (amount, user_id))
                cur.execute("UPDATE withdrawal_requests SET status='rejected' WHERE id=%s", (withdrawal_id,))
                cur.execute(
                    """
                    UPDATE transactions
                    SET status='failed'
                    WHERE id = (
                        SELECT id FROM transactions
                        WHERE user_id=%s AND transaction_type='withdrawal' AND amount=%s AND status='pending'
                        ORDER BY created_at DESC, id DESC LIMIT 1
                    )
                    """,
                    (user_id, amount),
                )
                message = "Withdrawal rejected and balance restored."
        # Do not flash success to admin UI; log instead
        logger.info("Admin %s processed withdrawal %s: %s", session.get("admin_id"), withdrawal_id, message)
    except Exception:
        logger.exception("ADMIN WITHDRAWAL ACTION ERROR")
        flash("Unable to process the withdrawal.", "error")
    return redirect(url_for("admin_withdrawals"))


@app.route("/admin/approve_invite/<token>", methods=["GET", "POST"])
def admin_approve_invite(token: str):
    if not admin_required():
        return redirect(url_for("admin_login"))
    try:
        with db_cursor(commit=True, dict_cursor=True) as cur:
            cur.execute("SELECT * FROM invites WHERE token=%s FOR UPDATE", (token,))
            invite = cur.fetchone()
            if not invite:
                flash("Invite not found.", "error")
                return redirect(url_for("admin_dashboard"))
            if invite.get("approved"):
                # keep info feedback for admin if needed
                return redirect(url_for("admin_dashboard"))
            owner_id = invite["owner_id"]
            amount = money(invite.get("amount") or 0)
            ensure_account(cur, owner_id, STARTING_DEPOSIT_BALANCE)
            cur.execute("UPDATE accounts SET referral_account = COALESCE(referral_account,0) + %s WHERE user_id=%s", (amount, owner_id))
            cur.execute("UPDATE invites SET approved=TRUE WHERE id=%s", (invite["id"],))
            cur.execute(
                """
                INSERT INTO transactions (user_id, transaction_type, amount, status, reference, description)
                VALUES (%s, 'invite_credit', %s, 'successful', %s, %s)
                """,
                (owner_id, amount, generate_reference("INV"), "Admin approved invite " + token),
            )
        logger.info("Admin %s approved invite %s for owner %s (amount %s)", session.get("admin_id"), token, owner_id, amount)
    except Exception:
        logger.exception("APPROVE INVITE ERROR")
        flash("Unable to approve invite.", "error")
    return redirect(url_for("admin_dashboard"))

# ============================================================
# ADMIN PLAN MANAGEMENT
# ============================================================

@app.route("/admin/plans", methods=["GET"])
def admin_plans():
    if not admin_required():
        return redirect(url_for("admin_login"))

    users = query_all(
        """
        SELECT id, username, fullname, phone
        FROM users
        ORDER BY id DESC
        """
    )

    user_plans = query_all(
        """
        SELECT
            p.id,
            p.user_id,
            p.plan_id,
            p.plan_name,
            p.investment_amount,
            p.daily_income,
            p.duration,
            p.started_at,
            p.last_claim_at,
            p.active,
            u.username,
            u.fullname,
            u.phone
        FROM plans p
        JOIN users u ON u.id = p.user_id
        ORDER BY p.id DESC
        """
    )

    available_plans = [
        {
            "id": plan_id,
            "plan_name": data["name"],
            "investment_amount": data["investment"],
            "daily_income": data["daily"],
            "duration": data["duration"],
        }
        for plan_id, data in PLANS.items()
    ]

    return render_template(
        "admin_plans.html",
        users=users,
        user_plans=user_plans,
        available_plans=available_plans,
    )


@app.route("/admin/plans/assign", methods=["POST"])
def admin_assign_plan():
    if not admin_required():
        return redirect(url_for("admin_login"))

    try:
        user_id = int(request.form.get("user_id", "0"))
        plan_id = int(request.form.get("plan_id", "0"))
    except (TypeError, ValueError):
        flash("Please select a valid user and plan.", "error")
        return redirect(url_for("admin_plans"))

    user = query_one(
        "SELECT id, username FROM users WHERE id=%s",
        (user_id,)
    )

    if not user:
        flash("User not found.", "error")
        return redirect(url_for("admin_plans"))

    if plan_id not in PLANS:
        flash("Plan not found.", "error")
        return redirect(url_for("admin_plans"))

    plan = PLANS[plan_id]

    try:
        with db_cursor(commit=True, dict_cursor=True) as cur:

            # Make sure the user's account exists.
            ensure_account(
                cur,
                user_id,
                Decimal("0.00")
            )

            # Give the plan directly to the user.
            # IMPORTANT:
            # No deposit balance is deducted here.
            started_at = utcnow()

            cur.execute(
                """
                INSERT INTO plans (
                    user_id,
                    plan_id,
                    plan_name,
                    investment_amount,
                    daily_income,
                    duration,
                    started_at,
                    last_claim_at,
                    active
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    NULL,
                    TRUE
                )
                RETURNING id
                """,
                (
                    user_id,
                    plan_id,
                    plan["name"],
                    plan["investment"],
                    plan["daily"],
                    plan["duration"],
                    started_at,
                )
            )

            new_plan = cur.fetchone()
            new_plan_id = fetch_id(new_plan, "id")

            # Audit record only.
            # This does NOT create a normal plan purchase.
            cur.execute(
                """
                INSERT INTO transactions (
                    user_id,
                    transaction_type,
                    amount,
                    status,
                    reference,
                    description
                )
                VALUES (
                    %s,
                    'admin_plan_grant',
                    %s,
                    'successful',
                    %s,
                    %s
                )
                """,
                (
                    user_id,
                    plan["investment"],
                    generate_reference("AGR"),
                    (
                        f"Admin granted {plan['name']} "
                        f"to user {user['username']} "
                        f"(plan #{new_plan_id})"
                    ),
                )
            )

        logger.info(
            "Admin %s granted plan %s to user %s",
            session.get("admin_id"),
            plan_id,
            user_id
        )

        flash(
            f"{plan['name']} assigned to {user['username']} successfully.",
            "success"
        )

    except Exception:
        logger.exception("ADMIN PLAN ASSIGN ERROR")
        flash("Unable to assign the plan.", "error")

    return redirect(url_for("admin_plans"))


@app.route("/admin/plans/delete/<int:plan_record_id>", methods=["POST"])
def admin_delete_plan(plan_record_id: int):
    if not admin_required():
        return redirect(url_for("admin_login"))

    try:
        with db_cursor(commit=True, dict_cursor=True) as cur:

            cur.execute(
                """
                SELECT
                    p.id,
                    p.user_id,
                    p.plan_name,
                    p.investment_amount,
                    u.username
                FROM plans p
                JOIN users u ON u.id = p.user_id
                WHERE p.id=%s
                FOR UPDATE
                """,
                (plan_record_id,)
            )

            plan = cur.fetchone()

            if not plan:
                flash("Plan record not found.", "error")
                return redirect(url_for("admin_plans"))

            # Permanently remove this plan record.
            cur.execute(
                "DELETE FROM plans WHERE id=%s",
                (plan_record_id,)
            )

            # Keep an audit trail in transactions.
            cur.execute(
                """
                INSERT INTO transactions (
                    user_id,
                    transaction_type,
                    amount,
                    status,
                    reference,
                    description
                )
                VALUES (
                    %s,
                    'admin_plan_delete',
                    %s,
                    'successful',
                    %s,
                    %s
                )
                """,
                (
                    plan["user_id"],
                    plan["investment_amount"],
                    generate_reference("ADL"),
                    (
                        f"Admin removed {plan['plan_name']} "
                        f"(plan #{plan_record_id})"
                    ),
                )
            )

        logger.info(
            "Admin %s deleted plan record %s from user %s",
            session.get("admin_id"),
            plan_record_id,
            plan["user_id"]
        )

        flash(
            f"{plan['plan_name']} removed from {plan['username']}.",
            "success"
        )

    except Exception:
        logger.exception("ADMIN PLAN DELETE ERROR")
        flash("Unable to delete the plan.", "error")

    return redirect(url_for("admin_plans"))
# ============================================================
# GIFT CODE SYSTEM
# ============================================================

def _normalize_gift_code(value: str) -> str:
    return "".join((value or "").strip().upper().split())


@app.route("/gift-code", methods=["GET", "POST"])
def gift_code():
    user = current_user()
    if not user:
        return redirect(url_for("login"))

    if request.method == "POST":
        code = _normalize_gift_code(request.form.get("code", ""))
        if not code:
            flash("Enter a gift code.", "error")
            return redirect(url_for("gift_code"))

        try:
            with db_cursor(commit=True, dict_cursor=True) as cur:
                cur.execute(
                    """
                    SELECT id, code, reward, max_claims, claims_count, active
                    FROM gift_codes
                    WHERE code=%s
                    FOR UPDATE
                    """,
                    (code,),
                )
                gift = cur.fetchone()

                if not gift:
                    flash("Gift code not found.", "error")
                    return redirect(url_for("gift_code"))
                if not gift["active"]:
                    flash("This gift code is no longer active.", "error")
                    return redirect(url_for("gift_code"))
                if gift["claims_count"] >= gift["max_claims"]:
                    flash("This gift code has reached its claim limit.", "error")
                    return redirect(url_for("gift_code"))

                cur.execute(
                    "SELECT id FROM gift_code_claims WHERE gift_code_id=%s AND user_id=%s",
                    (gift["id"], user["id"]),
                )
                if cur.fetchone():
                    flash("You have already claimed this gift code.", "error")
                    return redirect(url_for("gift_code"))

                # Gift-code rewards are immediately added to the user's
                # withdraw account so the reward appears in the normal
                # withdrawable balance. Keep gift_balance in sync for
                # backwards compatibility with existing accounts/templates.
                cur.execute(
                    """
                    UPDATE accounts
                    SET gift_balance = COALESCE(gift_balance, 0) + %s,
                        withdraw_account = COALESCE(withdraw_account, 0) + %s
                    WHERE user_id=%s
                    """,
                    (gift["reward"], gift["reward"], user["id"]),
                )
                cur.execute(
                    """
                    INSERT INTO gift_code_claims (gift_code_id, user_id, reward)
                    VALUES (%s, %s, %s)
                    """,
                    (gift["id"], user["id"], gift["reward"]),
                )
                cur.execute(
                    "UPDATE gift_codes SET claims_count=claims_count+1 WHERE id=%s",
                    (gift["id"],),
                )

                # Record the reward in transaction history as a successful
                # credit so the user can see exactly when and why the
                # withdraw account increased.
                reward_reference = generate_reference("GIFT")
                cur.execute(
                    """
                    INSERT INTO transactions
                        (user_id, transaction_type, amount, status, reference, description)
                    VALUES
                        (%s, 'gift_code_reward', %s, 'successful', %s, %s)
                    """,
                    (
                        user["id"],
                        gift["reward"],
                        reward_reference,
                        f"Gift code reward: {gift['code']} credited to withdraw account",
                    ),
                )

            flash(
                f"Gift code claimed successfully. You have successfully been rewarded GHS {money(gift['reward']):,.2f}.",
                "success",
            )
        except Exception:
            logger.exception("GIFT CODE CLAIM ERROR")
            flash("Unable to claim the gift code. Please try again.", "error")

        return redirect(url_for("gift_code"))

    account = current_account(user["id"])
    claims = query_all(
        """
        SELECT g.code, c.reward, c.claimed_at
        FROM gift_code_claims c
        JOIN gift_codes g ON g.id=c.gift_code_id
        WHERE c.user_id=%s
        ORDER BY c.claimed_at DESC
        LIMIT 50
        """,
        (user["id"],),
    )
    return render_template("gift_code.html", user=user, account=account, claims=claims)


@app.route("/admin/gift-codes", methods=["GET", "POST"])
def admin_gift_codes():
    if not admin_required():
        return redirect(url_for("admin_login"))

    if request.method == "POST":
        code = _normalize_gift_code(request.form.get("code", ""))
        reward_raw = request.form.get("reward", "0")
        max_claims_raw = request.form.get("max_claims", "0")

        try:
            reward = Decimal(reward_raw).quantize(Decimal("0.01"))
            max_claims = int(max_claims_raw)
        except (InvalidOperation, ValueError):
            flash("Enter a valid reward and claim limit.", "error")
            return redirect(url_for("admin_gift_codes"))

        if not code or len(code) < 3:
            flash("Gift code must contain at least 3 characters.", "error")
            return redirect(url_for("admin_gift_codes"))
        if reward <= 0:
            flash("Reward must be greater than zero.", "error")
            return redirect(url_for("admin_gift_codes"))
        if max_claims < 1:
            flash("Claim limit must be at least 1 user.", "error")
            return redirect(url_for("admin_gift_codes"))

        try:
            execute(
                """
                INSERT INTO gift_codes (code, reward, max_claims, created_by)
                VALUES (%s, %s, %s, %s)
                """,
                (code, reward, max_claims, session.get("admin_id")),
            )
            flash("Gift code created and activated.", "success")
        except Exception as exc:
            logger.exception("CREATE GIFT CODE ERROR")
            if "unique" in str(exc).lower():
                flash("That gift code already exists.", "error")
            else:
                flash("Unable to create the gift code.", "error")

        return redirect(url_for("admin_gift_codes"))

    gift_codes = query_all(
        """
        SELECT g.*, a.username AS created_by_username
        FROM gift_codes g
        LEFT JOIN admins a ON a.id=g.created_by
        ORDER BY g.created_at DESC, g.id DESC
        """
    )
    return render_template("admin_gift_codes.html", gift_codes=gift_codes)


@app.route("/admin/gift-codes/<int:gift_id>/toggle", methods=["POST"])
def admin_toggle_gift_code(gift_id: int):
    if not admin_required():
        return redirect(url_for("admin_login"))

    gift = query_one("SELECT id, active FROM gift_codes WHERE id=%s", (gift_id,))
    if not gift:
        flash("Gift code not found.", "error")
        return redirect(url_for("admin_gift_codes"))

    if gift["active"]:
        execute(
            "UPDATE gift_codes SET active=FALSE, deactivated_at=CURRENT_TIMESTAMP WHERE id=%s",
            (gift_id,),
        )
        flash("Gift code deactivated.", "success")
    else:
        execute(
            "UPDATE gift_codes SET active=TRUE, deactivated_at=NULL WHERE id=%s",
            (gift_id,),
        )
        flash("Gift code activated.", "success")

    return redirect(url_for("admin_gift_codes"))


@app.route("/admin/gift-codes/<int:gift_id>/claims")
def admin_gift_code_claims(gift_id: int):
    if not admin_required():
        return redirect(url_for("admin_login"))

    gift = query_one("SELECT * FROM gift_codes WHERE id=%s", (gift_id,))
    if not gift:
        flash("Gift code not found.", "error")
        return redirect(url_for("admin_gift_codes"))

    claims = query_all(
        """
        SELECT c.reward, c.claimed_at, u.username, u.fullname, u.phone
        FROM gift_code_claims c
        JOIN users u ON u.id=c.user_id
        WHERE c.gift_code_id=%s
        ORDER BY c.claimed_at DESC
        """,
        (gift_id,),
    )
    return render_template("admin_gift_claims.html", gift=gift, claims=claims)

@app.route("/admin/offers")
def admin_offers():
    if not admin_required():
        return redirect(url_for("admin_login"))

    offers = query_all("""
        SELECT *
        FROM admin_offer
        ORDER BY id DESC
    """)

    return render_template(
        "admin_offers.html",
        offers=offers
    )


@app.route("/admin/offers/create", methods=["GET", "POST"])
def admin_create_offer():
    if not admin_required():
        return redirect(url_for("admin_login"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        price = request.form.get("price", "0").strip()
        daily_amount = request.form.get("daily_amount", "0").strip()
        duration = request.form.get("duration", "0").strip()
        image_url = request.form.get("image_url", "").strip()
        description = request.form.get("description", "").strip()

        if not name:
            flash("Offer name is required.", "error")
            return redirect(url_for("admin_create_offer"))

        try:
            price = Decimal(price)
            daily_amount = Decimal(daily_amount)
            duration = int(duration)
        except (InvalidOperation, ValueError):
            flash("Please enter valid offer details.", "error")
            return redirect(url_for("admin_create_offer"))

        execute("""
            INSERT INTO admin_offer
            (name, price, daily_amount, duration, image_url, description, active)
            VALUES (%s, %s, %s, %s, %s, %s, TRUE)
        """, (
            name,
            price,
            daily_amount,
            duration,
            image_url,
            description
        ))

        flash("Offer created successfully.", "success")
        return redirect(url_for("admin_offers"))

    return render_template("admin_offer_form.html", offer=None)


@app.route("/admin/offers/edit/<int:offer_id>", methods=["GET", "POST"])
def admin_edit_offer(offer_id):
    if not admin_required():
        return redirect(url_for("admin_login"))

    offer = query_one(
        "SELECT * FROM admin_offer WHERE id=%s",
        (offer_id,)
    )

    if not offer:
        flash("Offer not found.", "error")
        return redirect(url_for("admin_offers"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        price = request.form.get("price", "0").strip()
        daily_amount = request.form.get("daily_amount", "0").strip()
        duration = request.form.get("duration", "0").strip()
        image_url = request.form.get("image_url", "").strip()
        description = request.form.get("description", "").strip()

        try:
            price = Decimal(price)
            daily_amount = Decimal(daily_amount)
            duration = int(duration)
        except (InvalidOperation, ValueError):
            flash("Invalid offer details.", "error")
            return redirect(
                url_for("admin_edit_offer", offer_id=offer_id)
            )

        execute("""
            UPDATE admin_offer
            SET name=%s,
                price=%s,
                daily_amount=%s,
                duration=%s,
                image_url=%s,
                description=%s,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=%s
        """, (
            name,
            price,
            daily_amount,
            duration,
            image_url,
            description,
            offer_id
        ))

        flash("Offer updated successfully.", "success")
        return redirect(url_for("admin_offers"))

    return render_template(
        "admin_offer_form.html",
        offer=offer
    )


@app.route("/admin/offers/toggle/<int:offer_id>", methods=["POST"])
def admin_toggle_offer(offer_id):
    if not admin_required():
        return redirect(url_for("admin_login"))

    offer = query_one(
        "SELECT id, active FROM admin_offer WHERE id=%s",
        (offer_id,)
    )

    if not offer:
        flash("Offer not found.", "error")
        return redirect(url_for("admin_offers"))

    execute("""
        UPDATE admin_offer
        SET active = NOT active,
            updated_at = CURRENT_TIMESTAMP
        WHERE id=%s
    """, (offer_id,))

    return redirect(url_for("admin_offers"))


@app.route("/admin/offers/delete/<int:offer_id>", methods=["POST"])
def admin_delete_offer(offer_id):
    if not admin_required():
        return redirect(url_for("admin_login"))

    execute(
        "DELETE FROM admin_offer WHERE id=%s",
        (offer_id,)
    )

    flash("Offer deleted.", "success")
    return redirect(url_for("admin_offers"))
# ============================================================
# Error handlers
# ============================================================
@app.errorhandler(413)
def file_too_large(error):
    flash("Screenshot is too large. Maximum size is 5 MB.", "error")
    return redirect(url_for("deposit"))


@app.errorhandler(404)
def not_found(error):
    return "Page not found", 404


@app.errorhandler(500)
def server_error(error):
    logger.exception("INTERNAL SERVER ERROR")
    return "An internal server error occurred.", 500


# ============================================================
# Application startup
# ============================================================
with app.app_context():
    try:
        if settings.DATABASE_URL:
            init_db()
    except Exception:
        logger.exception("Failed to initialize DB at startup (continuing).")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", str(settings.PORT)))
    debug = os.environ.get("FLASK_DEBUG", str(settings.FLASK_DEBUG)).lower() in ("1", "true", "yes")
    app.run(host="0.0.0.0", port=port, debug=debug)
