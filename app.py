import os
from decimal import Decimal

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session
)

from werkzeug.security import generate_password_hash, check_password_hash

from flask_sqlalchemy import SQLAlchemy


# ============================================================
# APP CONFIGURATION
# ============================================================

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY",
    "change-this-secret-key"
)

database_url = os.environ.get("DATABASE_URL")

if not database_url:
    raise RuntimeError(
        "DATABASE_URL environment variable is missing."
    )

# Some PostgreSQL providers may return postgres://
# instead of postgresql://.
if database_url.startswith("postgres://"):
    database_url = database_url.replace(
        "postgres://",
        "postgresql://",
        1
    )

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# ============================================================
# PLANS
# ============================================================

PLANS = [
    {
        "id": 1,
        "name": "JOMA 1",
        "amount": Decimal("70"),
        "daily": Decimal("8"),
        "days": 180,
        "image": "plan1.jpg"
    },
    {
        "id": 2,
        "name": "JOMA 2",
        "amount": Decimal("120"),
        "daily": Decimal("25"),
        "days": 180,
        "image": "plan2.jpg"
    },
    {
        "id": 3,
        "name": "JOMA 3",
        "amount": Decimal("250"),
        "daily": Decimal("45"),
        "days": 180,
        "image": "plan3.jpg"
    },
    {
        "id": 4,
        "name": "JOMA 4",
        "amount": Decimal("300"),
        "daily": Decimal("55"),
        "days": 180,
        "image": "plan4.jpg"
    },
    {
        "id": 5,
        "name": "JOMA 5",
        "amount": Decimal("450"),
        "daily": Decimal("85"),
        "days": 180,
        "image": "plan5.jpg"
    },
    {
        "id": 6,
        "name": "JOMA 6",
        "amount": Decimal("600"),
        "daily": Decimal("100"),
        "days": 180,
        "image": "plan6.jpg"
    },
    {
        "id": 7,
        "name": "JOMA 7",
        "amount": Decimal("850"),
        "daily": Decimal("188"),
        "days": 180,
        "image": "plan7.jpg"
    },
    {
        "id": 8,
        "name": "JOMA 8",
        "amount": Decimal("1000"),
        "daily": Decimal("300"),
        "days": 180,
        "image": "plan8.jpg"
    },
    {
        "id": 9,
        "name": "JOMA 9",
        "amount": Decimal("1600"),
        "daily": Decimal("450"),
        "days": 180,
        "image": "plan9.jpg"
    },
    {
        "id": 10,
        "name": "JOMA 10",
        "amount": Decimal("2000"),
        "daily": Decimal("600"),
        "days": 180,
        "image": "plan10.jpg"
    }
]


# ============================================================
# DATABASE MODELS
# ============================================================

class User(db.Model):

    __tablename__ = "users"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    phone = db.Column(
        db.String(30),
        unique=True,
        nullable=False
    )

    password_hash = db.Column(
        db.String(255),
        nullable=False
    )

    balance = db.Column(
        db.Numeric(12, 2),
        default=0,
        nullable=False
    )

    total_deposit = db.Column(
        db.Numeric(12, 2),
        default=0,
        nullable=False
    )

    total_income = db.Column(
        db.Numeric(12, 2),
        default=0,
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        server_default=db.func.now()
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(
            password
        )

    def check_password(self, password):
        return check_password_hash(
            self.password_hash,
            password
        )


class UserPlan(db.Model):

    __tablename__ = "user_plans"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False
    )

    plan_id = db.Column(
        db.Integer,
        nullable=False
    )

    plan_name = db.Column(
        db.String(100),
        nullable=False
    )

    amount = db.Column(
        db.Numeric(12, 2),
        nullable=False
    )

    daily_amount = db.Column(
        db.Numeric(12, 2),
        nullable=False
    )

    duration_days = db.Column(
        db.Integer,
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        server_default=db.func.now()
    )


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

with app.app_context():
    db.create_all()


# ============================================================
# LOGIN HELPER
# ============================================================

def get_current_user():

    user_id = session.get("user_id")

    if not user_id:
        return None

    return db.session.get(User, user_id)


# ============================================================
# HOME
# ============================================================

@app.route("/")
def index():

    if session.get("user_id"):
        return redirect(url_for("dashboard"))

    return redirect(url_for("login"))


# ============================================================
# REGISTER
# ============================================================

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        phone = request.form.get(
            "phone",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        confirm_password = request.form.get(
            "confirm_password",
            ""
        )

        if not phone:
            flash(
                "Please enter your phone number.",
                "error"
            )
            return redirect(url_for("register"))

        if len(password) < 6:
            flash(
                "Password must contain at least 6 characters.",
                "error"
            )
            return redirect(url_for("register"))

        if password != confirm_password:
            flash(
                "Passwords do not match.",
                "error"
            )
            return redirect(url_for("register"))

        existing_user = User.query.filter_by(
            phone=phone
        ).first()

        if existing_user:
            flash(
                "An account with this phone number already exists.",
                "error"
            )
            return redirect(url_for("login"))

        user = User(
            phone=phone,
            balance=0,
            total_deposit=0,
            total_income=0
        )

        user.set_password(password)

        db.session.add(user)
        db.session.commit()

        flash(
            "Account created successfully. Please login.",
            "success"
        )

        return redirect(url_for("login"))

    return render_template(
        "register.html"
    )


# ============================================================
# LOGIN
# ============================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        phone = request.form.get(
            "phone",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        user = User.query.filter_by(
            phone=phone
        ).first()

        if not user or not user.check_password(password):

            flash(
                "Invalid phone number or password.",
                "error"
            )

            return redirect(
                url_for("login")
            )

        session.clear()

        session["user_id"] = user.id

        return redirect(
            url_for("dashboard")
        )

    return render_template(
        "login.html"
    )


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("login")
    )


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/dashboard")
def dashboard():

    user = get_current_user()

    if not user:
        return redirect(
            url_for("login")
        )

    user_plans = UserPlan.query.filter_by(
        user_id=user.id
    ).order_by(
        UserPlan.created_at.desc()
    ).all()

    return render_template(
        "dashboard.html",
        user=user,
        plans=PLANS,
        user_plans=user_plans
    )


# ============================================================
# PLAN DETAILS
# ============================================================

@app.route("/plan/<int:plan_id>")
def plan_details(plan_id):

    user = get_current_user()

    if not user:
        return redirect(
            url_for("login")
        )

    plan = next(
        (
            item for item in PLANS
            if item["id"] == plan_id
        ),
        None
    )

    if not plan:

        flash(
            "Plan not found.",
            "error"
        )

        return redirect(
            url_for("dashboard")
        )

    return render_template(
        "plan_details.html",
        user=user,
        plan=plan
    )


# ============================================================
# DEMO PLAN ACTIVATION
# ============================================================
#
# This records a selected plan in the database.
# It does NOT move real money or promise financial returns.
#
# Later we can connect a legitimate payment flow here.
# ============================================================

@app.route(
    "/plan/<int:plan_id>/activate",
    methods=["POST"]
)
def activate_plan(plan_id):

    user = get_current_user()

    if not user:
        return redirect(
            url_for("login")
        )

    plan = next(
        (
            item for item in PLANS
            if item["id"] == plan_id
        ),
        None
    )

    if not plan:

        flash(
            "Plan not found.",
            "error"
        )

        return redirect(
            url_for("dashboard")
        )

    selected_plan = UserPlan(
        user_id=user.id,
        plan_id=plan["id"],
        plan_name=plan["name"],
        amount=plan["amount"],
        daily_amount=plan["daily"],
        duration_days=plan["days"]
    )

    db.session.add(selected_plan)

    db.session.commit()

    flash(
        f'{plan["name"]} selected successfully.',
        "success"
    )

    return redirect(
        url_for("dashboard")
    )


# ============================================================
# PROFILE
# ============================================================

@app.route("/profile")
def profile():

    user = get_current_user()

    if not user:
        return redirect(
            url_for("login")
        )

    return render_template(
        "profile.html",
        user=user
    )


# ============================================================
# SIMPLE HEALTH CHECK
# ============================================================

@app.route("/health")
def health():

    return {
        "status": "ok",
        "app": "JOMA"
    }


# ============================================================
# ERROR HANDLERS
# ============================================================

@app.errorhandler(404)
def page_not_found(error):

    return render_template(
        "error.html",
        message="Page not found."
    ), 404


@app.errorhandler(500)
def server_error(error):

    db.session.rollback()

    return render_template(
        "error.html",
        message="An internal server error occurred."
    ), 500


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            5000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
