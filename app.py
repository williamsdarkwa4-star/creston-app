from flask import Flask, render_template, redirect, url_for, request, session, flash
import os, secrets, logging
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None
    RealDictCursor = None

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.getenv("SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    MAX_CONTENT_LENGTH=5 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)
app.permanent_session_lifetime = timedelta(days=7)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "Williams")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Williams12")
PORT = int(os.getenv("PORT", "5000"))
WELCOME_BONUS = Decimal("10.00")
MIN_DEPOSIT = Decimal("90.00")
MIN_WITHDRAWAL = Decimal("30.00")
WITHDRAWAL_FEE_PERCENT = Decimal("18.00")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("joma")


def conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured.")
    if psycopg2 is None:
        raise RuntimeError("psycopg2-binary is required.")
    return psycopg2.connect(DATABASE_URL, sslmode="require")


def one(sql, params=()):
    c = conn()
    try:
        with c.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    finally:
        c.close()


def all_rows(sql, params=()):
    c = conn()
    try:
        with c.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        c.close()


def run(sql, params=(), returning=False):
    c = conn()
    try:
        with c.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            result = cur.fetchone() if returning else None
        c.commit()
        return result
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def money(value):
    try:
        return Decimal(str(value or 0)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0.00")


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    try:
        return one("SELECT * FROM users WHERE id=%s", (uid,))
    except Exception:
        return None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in first.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)
    return wrapped


def init_db():
    c = conn()
    statements = [
        """CREATE TABLE IF NOT EXISTS users(
            id SERIAL PRIMARY KEY,
            username VARCHAR(80) UNIQUE NOT NULL,
            fullname VARCHAR(150) NOT NULL DEFAULT '',
            phone VARCHAR(40) UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            referral_code VARCHAR(80) UNIQUE NOT NULL,
            referred_by VARCHAR(80),
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS accounts(
            id SERIAL PRIMARY KEY,
            user_id INTEGER UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            deposit_account NUMERIC(14,2) NOT NULL DEFAULT 0,
            income_account NUMERIC(14,2) NOT NULL DEFAULT 0,
            referral_account NUMERIC(14,2) NOT NULL DEFAULT 0,
            withdraw_account NUMERIC(14,2) NOT NULL DEFAULT 0,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS admin_offer(
            id SERIAL PRIMARY KEY,
            name VARCHAR(150) NOT NULL,
            price NUMERIC(14,2) NOT NULL DEFAULT 0,
            daily_amount NUMERIC(14,2) NOT NULL DEFAULT 0,
            duration INTEGER NOT NULL DEFAULT 0,
            image_url TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS demo_transactions(
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            kind VARCHAR(30) NOT NULL,
            amount NUMERIC(14,2) NOT NULL DEFAULT 0,
            status VARCHAR(30) NOT NULL DEFAULT 'simulated',
            note TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
    ]
    try:
        with c.cursor() as cur:
            for statement in statements:
                cur.execute(statement)
        c.commit()
    finally:
        c.close()


@app.before_request
def database_startup():
    if not app.config.get("DB_READY"):
        try:
            init_db()
            app.config["DB_READY"] = True
        except Exception:
            log.exception("Database initialisation failed")


@app.context_processor
def inject_context():
    return {
        "logged_user": current_user(),
        "is_admin": bool(session.get("admin_logged_in")),
        "welcome_bonus": WELCOME_BONUS,
        "min_deposit": MIN_DEPOSIT,
        "min_withdrawal": MIN_WITHDRAWAL,
        "withdrawal_fee_percent": WITHDRAWAL_FEE_PERCENT,
    }


@app.route("/health")
def health():
    try:
        one("SELECT 1")
        return {"status": "ok", "database": "connected"}
    except Exception as exc:
        return {"status": "error", "database": "unavailable", "message": str(exc)}, 503


@app.route("/")
def index():
    if session.get("admin_logged_in"):
        return redirect(url_for("admin_dashboard"))
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    ref = request.args.get("ref", "").strip() or request.form.get("referral_code", "").strip()
    if request.method == "POST":
        fullname = request.form.get("fullname", "").strip()
        username = request.form.get("username", "").strip()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", password)

        if not fullname or not username or not phone or not password:
            flash("Please complete all required fields.", "error")
            return render_template("register.html", invite_code=ref)
        if len(password) < 6:
            flash("Password must contain at least 6 characters.", "error")
            return render_template("register.html", invite_code=ref)
        if password != confirm:
            flash("Passwords do not match.", "error")
            return render_template("register.html", invite_code=ref)

        try:
            if one("SELECT id FROM users WHERE username=%s OR phone=%s", (username, phone)):
                flash("Username or phone number already exists.", "error")
                return render_template("register.html", invite_code=ref)

            if ref and not one("SELECT id FROM users WHERE referral_code=%s", (ref,)):
                ref = ""

            code = "JOMA-" + secrets.token_hex(6).upper()
            new_user = run(
                """INSERT INTO users(username,fullname,phone,password_hash,referral_code,referred_by)
                   VALUES(%s,%s,%s,%s,%s,%s) RETURNING id""",
                (username, fullname, phone, generate_password_hash(password), code, ref or None),
                returning=True,
            )
            run("INSERT INTO accounts(user_id, withdraw_account) VALUES(%s,%s)", (new_user["id"], WELCOME_BONUS))
            flash("Account created successfully. Your welcome bonus is GHS 10.00. Please log in.", "success")
            return redirect(url_for("login"))
        except Exception:
            log.exception("register")
            flash("Registration failed. Check your database settings.", "error")

    return render_template("register.html", invite_code=ref)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        try:
            u = one("SELECT * FROM users WHERE phone=%s", (phone,))
            if u and check_password_hash(u["password_hash"], password):
                session.clear()
                session.permanent = True
                session["user_id"] = u["id"]
                return redirect(url_for("dashboard"))
            flash("Invalid phone number or password.", "error")
        except Exception:
            log.exception("login")
            flash("Login is temporarily unavailable.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    u = current_user()
    try:
        account = one("SELECT * FROM accounts WHERE user_id=%s", (u["id"],))
        if not account:
            run("INSERT INTO accounts(user_id,withdraw_account) VALUES(%s,%s)", (u["id"], WELCOME_BONUS))
            account = one("SELECT * FROM accounts WHERE user_id=%s", (u["id"],))
        offers = all_rows("SELECT * FROM admin_offer WHERE active=TRUE ORDER BY id")
        return render_template("dashboard.html", user=u, account=account, offers=offers)
    except Exception:
        log.exception("dashboard")
        flash("Dashboard could not load.", "error")
        return render_template(
            "dashboard.html",
            user=u,
            account={"deposit_account": 0, "income_account": 0, "referral_account": 0, "withdraw_account": WELCOME_BONUS},
            offers=[],
        )


@app.route("/offers")
@login_required
def offers():
    try:
        return render_template("offers.html", offers=all_rows("SELECT * FROM admin_offer WHERE active=TRUE ORDER BY id"))
    except Exception:
        flash("Offers are unavailable.", "error")
        return redirect(url_for("dashboard"))


@app.route("/buy_offer/<int:offer_id>", methods=["GET", "POST"])
@login_required
def buy_offer(offer_id):
    try:
        offer = one("SELECT * FROM admin_offer WHERE id=%s AND active=TRUE", (offer_id,))
        if not offer:
            flash("Offer not found.", "error")
            return redirect(url_for("offers"))
        # UI-only selection. No real payment, investment, or money transfer occurs.
        return render_template("offer_selected.html", offer=offer)
    except Exception:
        log.exception("offer")
        flash("Unable to open offer.", "error")
        return redirect(url_for("offers"))


@app.route("/deposit", methods=["GET", "POST"])
@login_required
def deposit():
    u = current_user()
    if request.method == "POST":
        amount = money(request.form.get("amount"))
        if amount < MIN_DEPOSIT:
            flash(f"The minimum simulated deposit is GHS {MIN_DEPOSIT:.2f}.", "error")
        else:
            try:
                run(
                    "INSERT INTO demo_transactions(user_id,kind,amount,status,note) VALUES(%s,%s,%s,%s,%s)",
                    (u["id"], "deposit", amount, "simulated", "No real funds were transferred."),
                )
                flash(f"Deposit simulation recorded: GHS {amount:.2f}. No real payment was processed.", "success")
                return redirect(url_for("transaction_history"))
            except Exception:
                log.exception("deposit")
                flash("Deposit simulation could not be recorded.", "error")
    return render_template("deposit.html", min_deposit=MIN_DEPOSIT)


@app.route("/withdraw", methods=["GET", "POST"])
@login_required
def withdraw():
    u = current_user()
    if request.method == "POST":
        amount = money(request.form.get("amount"))
        method = request.form.get("method", "").strip()
        account_number = request.form.get("account_number", "").strip()
        if amount < MIN_WITHDRAWAL:
            flash(f"The minimum simulated withdrawal is GHS {MIN_WITHDRAWAL:.2f}.", "error")
        elif not method or not account_number:
            flash("Enter a withdrawal method and account reference for the simulation.", "error")
        else:
            fee = (amount * WITHDRAWAL_FEE_PERCENT / Decimal("100")).quantize(Decimal("0.01"))
            net = amount - fee
            try:
                run(
                    "INSERT INTO demo_transactions(user_id,kind,amount,status,note) VALUES(%s,%s,%s,%s,%s)",
                    (u["id"], "withdrawal", amount, "simulated", f"Simulation only. Fee shown: GHS {fee:.2f}; simulated net: GHS {net:.2f}. No money was sent."),
                )
                flash("Withdrawal simulation recorded. No real money was transferred.", "success")
                return redirect(url_for("transaction_history"))
            except Exception:
                log.exception("withdraw")
                flash("Withdrawal simulation could not be recorded.", "error")
    return render_template("withdraw.html", min_withdrawal=MIN_WITHDRAWAL, fee_percent=WITHDRAWAL_FEE_PERCENT)


@app.route("/profile")
@login_required
def profile():
    return render_template("profile.html", user=current_user())


@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    u = current_user()
    if request.method == "POST":
        old = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        if not check_password_hash(u["password_hash"], old):
            flash("Current password is incorrect.", "error")
        elif len(new) < 6:
            flash("New password must contain at least 6 characters.", "error")
        elif new != confirm:
            flash("New passwords do not match.", "error")
        else:
            try:
                run("UPDATE users SET password_hash=%s WHERE id=%s", (generate_password_hash(new), u["id"]))
                flash("Password updated successfully.", "success")
                return redirect(url_for("profile"))
            except Exception:
                log.exception("password")
                flash("Password update failed.", "error")
    return render_template("change_password.html")


@app.route("/team")
@app.route("/service/support/team")
@login_required
def team():
    return render_template("team.html", user=current_user())


@app.route("/support")
@app.route("/service/support")
@login_required
def support():
    return render_template("support.html", user=current_user())


@app.route("/my_plan")
@login_required
def my_plan():
    return render_template("my_plan.html", plans=[])


@app.route("/transaction_history")
@login_required
def transaction_history():
    try:
        transactions = all_rows(
            "SELECT * FROM demo_transactions WHERE user_id=%s ORDER BY id DESC LIMIT 100",
            (current_user()["id"],),
        )
    except Exception:
        transactions = []
        flash("Transaction history is temporarily unavailable.", "error")
    return render_template("transaction_history.html", transactions=transactions)


@app.route("/admin")
def admin_index():
    return redirect(url_for("admin_dashboard" if session.get("admin_logged_in") else "admin_login"))


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if secrets.compare_digest(username, ADMIN_USERNAME) and secrets.compare_digest(password, ADMIN_PASSWORD):
            session.clear()
            session.permanent = True
            session["admin_logged_in"] = True
            session["admin_username"] = ADMIN_USERNAME
            return redirect(url_for("admin_dashboard"))
        flash("Invalid administrator credentials.", "error")
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


@app.route("/admin/dashboard")
@app.route("/admin_dashboard")
@admin_required
def admin_dashboard():
    try:
        users_count = one("SELECT COUNT(*) AS count FROM users")["count"]
        offers_count = one("SELECT COUNT(*) AS count FROM admin_offer")["count"]
        active_offers_count = one("SELECT COUNT(*) AS count FROM admin_offer WHERE active=TRUE")["count"]
        demo_count = one("SELECT COUNT(*) AS count FROM demo_transactions")["count"]
        recent = all_rows("SELECT id,username,fullname,phone,referral_code,created_at FROM users ORDER BY id DESC LIMIT 20")
        return render_template(
            "admin_dashboard.html",
            users_count=users_count,
            offers_count=offers_count,
            active_offers_count=active_offers_count,
            demo_transactions_count=demo_count,
            recent_users=recent,
        )
    except Exception:
        log.exception("admin dashboard")
        flash("Admin dashboard could not load.", "error")
        return render_template("admin_dashboard.html", users_count=0, offers_count=0, active_offers_count=0, demo_transactions_count=0, recent_users=[])


@app.route("/admin/users")
@app.route("/admin_users")
@admin_required
def admin_users():
    try:
        users = all_rows(
            """SELECT u.*,a.deposit_account,a.income_account,a.referral_account,a.withdraw_account
               FROM users u LEFT JOIN accounts a ON a.user_id=u.id ORDER BY u.id DESC"""
        )
        return render_template("admin_users.html", users=users)
    except Exception:
        flash("Users could not be loaded.", "error")
        return redirect(url_for("admin_dashboard"))


@app.route("/admin/user/<int:user_id>")
@admin_required
def admin_user(user_id):
    try:
        u = one(
            """SELECT u.*,a.deposit_account,a.income_account,a.referral_account,a.withdraw_account
               FROM users u LEFT JOIN accounts a ON a.user_id=u.id WHERE u.id=%s""",
            (user_id,),
        )
        if not u:
            flash("User not found.", "error")
            return redirect(url_for("admin_users"))
        transactions = all_rows("SELECT * FROM demo_transactions WHERE user_id=%s ORDER BY id DESC LIMIT 50", (user_id,))
        return render_template("admin_user.html", user=u, transactions=transactions)
    except Exception:
        flash("User could not be loaded.", "error")
        return redirect(url_for("admin_users"))


@app.route("/admin/offers")
@admin_required
def admin_offers():
    try:
        return render_template("admin_offers.html", offers=all_rows("SELECT * FROM admin_offer ORDER BY id"))
    except Exception:
        flash("Offers could not be loaded.", "error")
        return redirect(url_for("admin_dashboard"))


@app.route("/admin/offers/create", methods=["GET", "POST"])
@admin_required
def admin_create_offer():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        price = money(request.form.get("price"))
        daily = money(request.form.get("daily_amount"))
        image = request.form.get("image_url", "").strip()
        description = request.form.get("description", "").strip()
        try:
            duration = int(request.form.get("duration", "0"))
            if not name or price < 0 or daily < 0 or duration < 0:
                raise ValueError
            run(
                """INSERT INTO admin_offer(name,price,daily_amount,duration,image_url,description,active)
                   VALUES(%s,%s,%s,%s,%s,%s,TRUE)""",
                (name, price, daily, duration, image, description),
            )
            flash("Offer created successfully.", "success")
            return redirect(url_for("admin_offers"))
        except Exception:
            log.exception("create offer")
            flash("Offer could not be created.", "error")
    return render_template("admin_offer_form.html", offer=None)


@app.route("/admin/offers/edit/<int:offer_id>", methods=["GET", "POST"])
@admin_required
def admin_edit_offer(offer_id):
    try:
        offer = one("SELECT * FROM admin_offer WHERE id=%s", (offer_id,))
    except Exception:
        offer = None
    if not offer:
        flash("Offer not found.", "error")
        return redirect(url_for("admin_offers"))

    if request.method == "POST":
        try:
            name = request.form.get("name", "").strip()
            price = money(request.form.get("price"))
            daily = money(request.form.get("daily_amount"))
            duration = int(request.form.get("duration", "0"))
            image = request.form.get("image_url", "").strip()
            description = request.form.get("description", "").strip()
            if not name or price < 0 or daily < 0 or duration < 0:
                raise ValueError
            run(
                """UPDATE admin_offer SET name=%s,price=%s,daily_amount=%s,duration=%s,
                   image_url=%s,description=%s,updated_at=CURRENT_TIMESTAMP WHERE id=%s""",
                (name, price, daily, duration, image, description, offer_id),
            )
            flash("Offer updated successfully.", "success")
            return redirect(url_for("admin_offers"))
        except Exception:
            log.exception("edit offer")
            flash("Offer could not be updated.", "error")
    return render_template("admin_offer_form.html", offer=offer)


@app.route("/admin/offers/toggle/<int:offer_id>", methods=["POST"])
@admin_required
def admin_toggle_offer(offer_id):
    try:
        run("UPDATE admin_offer SET active=NOT active,updated_at=CURRENT_TIMESTAMP WHERE id=%s", (offer_id,))
        flash("Offer status updated.", "success")
    except Exception:
        log.exception("toggle offer")
        flash("Offer status could not be changed.", "error")
    return redirect(url_for("admin_offers"))


@app.route("/admin/offers/delete/<int:offer_id>", methods=["POST"])
@admin_required
def admin_delete_offer(offer_id):
    try:
        run("DELETE FROM admin_offer WHERE id=%s", (offer_id,))
        flash("Offer deleted.", "success")
    except Exception:
        log.exception("delete offer")
        flash("Offer could not be deleted.", "error")
    return redirect(url_for("admin_offers"))


@app.errorhandler(413)
def too_large(error):
    return render_template("error.html", code=413, message="The submitted request is too large."), 413


@app.errorhandler(404)
def not_found(error):
    return render_template("error.html", code=404, message="The page was not found."), 404


@app.errorhandler(500)
def internal(error):
    log.exception("Unhandled error")
    return render_template("error.html", code=500, message="An internal server error occurred."), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
