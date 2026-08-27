# app.py â€” main Flask application
import os
from flask import Flask, render_template, redirect, url_for, flash, request
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from flask_wtf.csrf import CSRFProtect
from models import db, User, Transaction, Investment, GiftCode, GiftClaim, Referral
from forms import RegisterForm, LoginForm, DepositForm, InvestForm, GiftClaimForm, ProfileForm
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()  # loads .env if present

def create_app():
    app = Flask(__name__, static_folder='static', template_folder='templates')
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///joma_dev.sqlite3')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)
    csrf = CSRFProtect(app)

    login_manager = LoginManager()
    login_manager.login_view = 'login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Routes
    @app.route('/')
    def index():
        return render_template('index.html')

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        form = RegisterForm()
        if form.validate_on_submit():
            username = form.username.data.strip()
            phone = form.phone.data.strip()
            password = form.password.data
            referral = form.referral.data.strip() or None
            if User.query.filter_by(username=username).first():
                flash('Username already taken', 'warning')
            else:
                user = User(username=username, phone=phone)
                user.set_password(password)
                user.generate_referral_code()
                # handle referral link
                if referral:
                    ref_user = User.query.filter_by(referral_code=referral).first()
                    if ref_user:
                        user.referred_by = ref_user.id
                db.session.add(user)
                db.session.commit()
                # credit referral if applicable
                if referral and ref_user:
                    ref_user.referral_balance += 5.0
                    db.session.add(ref_user)
                    db.session.add(Transaction(user_id=ref_user.id, type='referral', amount=5.0, note='Referral bonus'))
                    db.session.commit()
                login_user(user)
                flash('Welcome, ' + username, 'success')
                return redirect(url_for('dashboard'))
        return render_template('register.html', form=form)

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        form = LoginForm()
        if form.validate_on_submit():
            user = User.query.filter_by(username=form.username.data).first()
            if user and user.check_password(form.password.data):
                login_user(user)
                flash('Signed in', 'success')
                next_page = request.args.get('next') or url_for('dashboard')
                return redirect(next_page)
            flash('Invalid credentials', 'danger')
        return render_template('login.html', form=form)

    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        flash('Signed out', 'info')
        return redirect(url_for('index'))

    @app.route('/dashboard')
    @login_required
    def dashboard():
        # fetch recent transactions and investments
        tx = Transaction.query.filter_by(user_id=current_user.id).order_by(Transaction.created_at.desc()).limit(10).all()
        invs = Investment.query.filter_by(user_id=current_user.id).order_by(Investment.start_at.desc()).all()
        # compute accrual for display (simple linear accrual)
        def inv_status(inv):
            elapsed_days = (datetime.utcnow() - inv.start_at).days
            accrued = (inv.amount * (inv.apy/100.0)) * (min(elapsed_days, inv.duration_days)/365.0)
            matured = elapsed_days >= inv.duration_days
            return {'elapsed_days': elapsed_days, 'accrued': accrued, 'matured': matured}
        invs_with_status = [(inv, inv_status(inv)) for inv in invs]
        return render_template('dashboard.html', tx=tx, invs=invs_with_status)

    @app.route('/deposit', methods=['GET', 'POST'])
    @login_required
    def deposit():
        form = DepositForm()
        if form.validate_on_submit():
            amt = form.amount.data
            current_user.deposit_balance += float(amt)
            db.session.add(current_user)
            db.session.add(Transaction(user_id=current_user.id, type='deposit', amount=amt, note='Simulated deposit'))
            db.session.commit()
            flash('Deposit credited: $' + f"{amt:.2f}", 'success')
            return redirect(url_for('dashboard'))
        return render_template('deposit.html', form=form)

    @app.route('/invest', methods=['GET', 'POST'])
    @login_required
    def invest():
        # demo static plans
        plans = [
            ('Starter 30d', 30, 5.0, 10.0),
            ('Growth 90d', 90, 12.0, 50.0),
            ('Pro 180d', 180, 25.0, 100.0)
        ]
        form = InvestForm()
        form.plan.choices = [(i, f"{p[0]} â€” {p[2]}% â€¢ {p[1]}d (min ${p[3]})") for i,p in enumerate(plans)]
        if form.validate_on_submit():
            idx = int(form.plan.data)
            amount = float(form.amount.data)
            plan = plans[idx]
            if amount > current_user.deposit_balance:
                flash('Insufficient deposit balance', 'danger')
            elif amount < plan[3]:
                flash(f"Minimum for this plan is ${plan[3]}", 'warning')
            else:
                current_user.deposit_balance -= amount
                inv = Investment(user_id=current_user.id, plan_name=plan[0], amount=amount, apy=plan[2], duration_days=plan[1], start_at=datetime.utcnow())
                db.session.add(inv)
                db.session.add(Transaction(user_id=current_user.id, type='investment', amount=amount, note=f"Invested in {plan[0]}"))
                db.session.commit()
                flash('Investment created', 'success')
                return redirect(url_for('dashboard'))
        return render_template('invest.html', form=form)

    @app.route('/redeem/<int:inv_id>', methods=['POST'])
    @login_required
    def redeem(inv_id):
        inv = Investment.query.filter_by(id=inv_id, user_id=current_user.id, redeemed=False).first_or_404()
        elapsed_days = (datetime.utcnow() - inv.start_at).days
        if elapsed_days < inv.duration_days:
            flash('Investment not matured yet', 'warning')
        else:
            accrued = (inv.amount * (inv.apy/100.0)) * (inv.duration_days/365.0)
            payout = inv.amount + accrued
            inv.redeemed = True
            current_user.income_balance += payout
            db.session.add(inv)
            db.session.add(current_user)
            db.session.add(Transaction(user_id=current_user.id, type='investment_payout', amount=payout, note='Redeemed investment'))
            db.session.commit()
            flash('Investment redeemed and payout credited to income balance', 'success')
        return redirect(url_for('dashboard'))

    @app.route('/gift-code', methods=['GET', 'POST'])
    @login_required
    def gift_code():
        form = GiftClaimForm()
        if form.validate_on_submit():
            code_str = form.code.data.strip().upper()
            gc = GiftCode.query.filter_by(code=code_str).first()
            if not gc:
                flash('Invalid gift code', 'danger')
            else:
                if gc.expires_at and gc.expires_at < datetime.utcnow():
                    flash('Code expired', 'warning')
                elif gc.uses >= gc.max_uses:
                    flash('Code fully claimed', 'warning')
                else:
                    # check claimed by user
                    already = GiftClaim.query.filter_by(code=code_str, user_id=current_user.id).first()
                    if already:
                        flash('You already claimed this code', 'info')
                    else:
                        gc.uses += 1
                        claim = GiftClaim(code=code_str, user_id=current_user.id)
                        current_user.deposit_balance += gc.amount
                        tx = Transaction(user_id=current_user.id, type='gift', amount=gc.amount, note=f'Gift code {code_str}')
                        db.session.add_all([gc, claim, current_user, tx])
                        db.session.commit()
                        flash(f'Gift claimed: ${gc.amount:.2f}', 'success')
                        return redirect(url_for('dashboard'))
        return render_template('gift_code.html', form=form)

    @app.route('/transactions')
    @login_required
    def transactions():
        tx = Transaction.query.filter_by(user_id=current_user.id).order_by(Transaction.created_at.desc()).all()
        return render_template('transactions.html', tx=tx)

    @app.route('/profile', methods=['GET', 'POST'])
    @login_required
    def profile():
        form = ProfileForm(obj=current_user)
        if form.validate_on_submit():
            current_user.phone = form.phone.data.strip()
            if form.password.data:
                current_user.set_password(form.password.data)
            db.session.add(current_user); db.session.commit()
            flash('Profile updated', 'success')
            return redirect(url_for('profile'))
        return render_template('profile.html', form=form)

    # admin route (simple)
    @app.route('/admin')
    @login_required
    def admin():
        if not current_user.is_admin:
            return "Forbidden", 403
        users = User.query.order_by(User.created_at.desc()).limit(200).all()
        tx = Transaction.query.order_by(Transaction.created_at.desc()).limit(200).all()
        gifts = GiftCode.query.order_by(GiftCode.created_at.desc()).all()
        return render_template('admin.html', users=users, tx=tx, gifts=gifts)

    return app

# entrypoint
app = create_app()
if __name__ == '__main__':
    app.run(debug=(os.environ.get('FLASK_ENV') == 'development'))
