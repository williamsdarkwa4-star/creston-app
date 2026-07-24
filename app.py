import os
import re
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session
import psycopg2
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import secrets

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'creston_secure_investment_system_key_2026')

def get_db_connection():
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        raise ValueError("DATABASE_URL environment variable is missing!")
    conn = psycopg2.connect(db_url, sslmode='require')
    return conn
CREATE TABLE IF NOT EXISTS withdrawals (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    amount NUMERIC(15, 2) NOT NULL,
    channel VARCHAR(50) NOT NULL,
    wallet_number VARCHAR(20) NOT NULL,
    status VARCHAR(20) DEFAULT 'Pending', -- Pending, Approved, Rejected
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Step 1: Add a unique referral code column to the users table
ALTER TABLE users ADD COLUMN IF NOT EXISTS my_referral_code VARCHAR(20) UNIQUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by VARCHAR(20);

-- Step 2: Create a commissions ledger table for audit logs
CREATE TABLE IF NOT EXISTS referral_commissions (
    id SERIAL PRIMARY KEY,
    referrer_id INT REFERENCES users(id) ON DELETE CASCADE,
    downline_id INT REFERENCES users(id) ON DELETE CASCADE,
    commission_amount NUMERIC(15, 2) NOT NULL,
    description VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


def init_db():
    """Automated database table construction routine."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Create users system table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            nickname VARCHAR(50) NOT NULL UNIQUE,
            phone_number VARCHAR(20) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            invite_code VARCHAR(20),
            income_wallet NUMERIC(15, 2) DEFAULT 15.00,
            deposit_wallet NUMERIC(15, 2) DEFAULT 0.00,
            is_banned BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Create structural plans schema
        cur.execute("""
        CREATE TABLE IF NOT EXISTS plans (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            price NUMERIC(15, 2) NOT NULL,
            daily_earning NUMERIC(15, 2) NOT NULL,
            duration_days INT DEFAULT 100
        );
        """)

        # Create live active portfolios table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS user_plans (
            id SERIAL PRIMARY KEY,
            user_id INT REFERENCES users(id) ON DELETE CASCADE,
            plan_id INT REFERENCES plans(id) ON DELETE CASCADE,
            purchase_price NUMERIC(15, 2) NOT NULL,
            daily_earning NUMERIC(15, 2) NOT NULL,
            days_accrued INT DEFAULT 0,
            duration_days INT DEFAULT 100,
            last_payout TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Populate plans if empty to prevent empty dashboard rows
        cur.execute("SELECT COUNT(*) FROM plans;")
        if cur.fetchone()[0] == 0:
            cur.execute("""
            INSERT INTO plans (name, price, daily_earning) VALUES
            ('CRESTON 1', 70.00, 10.00),
            ('CRESTON 2', 100.00, 20.00),
            ('CRESTON 3', 300.00, 40.00),
            ('CRESTON 4', 500.00, 70.00),
            ('CRESTON 5', 800.00, 150.00),
            ('CRESTON 6', 1000.00, 360.00),
            ('CRESTON 7', 2000.00, 450.00),
            ('CRESTON 8', 5000.00, 600.00);
            """)
        conn.commit()
        print("Database initialized successfully!")
    except Exception as e:
        conn.rollback()
        print(f"Error initializing database: {e}")
    finally:
        cur.close()
        conn.close()

# Run table generator engine automatically before web initialization
with app.app_context():
    try:
        init_db()
    except Exception as ex:
        print(f"Skipping startup initialization (database url might not be set yet): {ex}")

# -------------------------------------------------------------
# 👤 ROUTE LOGIC HANDLERS
# -------------------------------------------------------------

def process_automated_payouts(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, daily_earning, days_accrued, duration_days, last_payout 
            FROM user_plans 
            WHERE user_id = %s AND days_accrued < duration_days;
        """, (user_id,))
        active_plans = cur.fetchall()
        now = datetime.now()
        for plan in active_plans:
            up_id, daily_earning, days_accrued, duration_days, last_payout = plan
            days_passed = (now - last_payout).days
            if days_passed > 0:
                allowed_days = min(days_passed, duration_days - days_accrued)
                total_credit = allowed_days * daily_earning
                cur.execute("UPDATE users SET income_wallet = income_wallet + %s WHERE id = %s;", (total_credit, user_id))
                cur.execute("UPDATE user_plans SET days_accrued = days_accrued + %s, last_payout = %s WHERE id = %s;", (allowed_days, now, up_id))
        conn.commit()
    except Exception as e:
        conn.rollback()
    finally:
        cur.close()
        conn.close()



def generate_unique_referral_code():
    """Generates an alphanumeric 8-character string for marketing invitations."""
    return secrets.token_hex(4).upper()

# --- UPDATE YOUR EXISTING /REGISTER ROUTE TO MATCH THIS ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        nickname = request.form.get('nickname', '').strip()
        phone_number = request.form.get('phone_number', '').strip()
        password = request.form.get('password', '')
        invite_code = request.form.get('invite_code', '').strip().upper() # Clean input

        if not nickname or not phone_number or not password:
            flash("All required fields must be filled out.", "error")
            return redirect(url_for('register'))

        hashed_password = generate_password_hash(password, method='scrypt')
        my_new_ref = generate_unique_referral_code()
        
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            # Check duplication metrics
            cur.execute("SELECT id FROM users WHERE nickname = %s OR phone_number = %s;", (nickname, phone_number))
            if cur.fetchone():
                flash("Nickname or phone number is already registered.", "error")
                return redirect(url_for('register'))

            # Verify if the provided invitation code exists in system architecture
            referred_by_code = None
            if invite_code:
                cur.execute("SELECT my_referral_code FROM users WHERE my_referral_code = %s;", (invite_code,))
                if cur.fetchone():
                    referred_by_code = invite_code
                else:
                    flash("Invalid invitation code. Leave blank if you don't have one.", "error")
                    return redirect(url_for('register'))

            # Write parameters securely into PostgreSQL rows
            cur.execute(
                """INSERT INTO users (nickname, phone_number, password_hash, invite_code, my_referral_code, referred_by) 
                   VALUES (%s, %s, %s, %s, %s, %s);""",
                (nickname, phone_number, hashed_password, invite_code, my_new_ref, referred_by_code)
            )
            conn.commit()
            flash("Account successfully created! Please log in.", "success")
            return redirect(url_for('login'))
        except Exception as e:
            conn.rollback()
            flash("A database error occurred. Please try again.", "error")
        finally:
            cur.close()
            conn.close()

    # Pre-populate field if visitor clicked a downstream structural URL path link
    passed_ref = request.args.get('ref', '').upper()
    return render_template('register.html', passed_ref=passed_ref)


# --- NEW PATHWAY: DOWNLINE PURCHASE REWARD INCENTIVE ---
def reward_referrer_commission(conn, cur, buyer_id, active_plan_price):
    """Checks tree architecture. Awards 10% commission on plans directly to Income Wallet."""
    try:
        # Identify if this buyer has an upstream structural upline anchor
        cur.execute("SELECT referred_by FROM users WHERE id = %s;", (buyer_id,))
        ref_res = cur.fetchone()
        
        if ref_res and ref_res[0]:
            upline_code = ref_res[0]
            
            # Find the ID of that referrer
            cur.execute("SELECT id FROM users WHERE my_referral_code = %s FOR UPDATE;", (upline_code,))
            referrer = cur.fetchone()
            
            if referrer:
                referrer_id = referrer[0]
                # Calculate 10% bonus yield parameter
                commission = float(active_plan_price) * 0.10
                
                # Credit Referrer's Income Wallet instantly
                cur.execute("UPDATE users SET income_wallet = income_wallet + %s WHERE id = %s;", (commission, referrer_id))
                
                # Insert tracking record ledger row
                cur.execute(
                    """INSERT INTO referral_commissions (referrer_id, downline_id, commission_amount, description)
                       VALUES (%s, %s, %s, %s);""",
                    (referrer_id, buyer_id, commission, f"10% Downline Activation Bonus")
                )
    except Exception as ex:
        print(f"Commission engine skip tracking: {ex}")


# --- NEW PATHWAY: RENDER THE USER INVITE DASHBOARD ---
@app.route('/invite')
def invite():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    user_id = session['user_id']
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Retrieve user's dedicated code metrics
    cur.execute("SELECT my_referral_code FROM users WHERE id = %s;", (user_id,))
    user_code = cur.fetchone()[0]
    
    # Calculate how many people have signed up using this user's link
    cur.execute("SELECT COUNT(*) FROM users WHERE referred_by = %s;", (user_code,))
    total_referrals = cur.fetchone()[0]
    
    # Sum total historical bonuses earned
    cur.execute("SELECT COALESCE(SUM(commission_amount), 0.00) FROM referral_commissions WHERE referrer_id = %s;", (user_id,))
    total_earned = cur.fetchone()[0]
    
    cur.close()
    conn.close()
    
    # Construct structural referral link matching your production domain layout
    # Dynamically adapts to local testing vs live server environments
    domain = request.host_url
    referral_link = f"{domain}register?ref={user_code}"
    
    return render_template('invite.html', code=user_code, count=total_referrals, earnings=total_earned, link=referral_link)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        phone_number = request.form.get('phone_number', '').strip()
        password = request.form.get('password', '')
        if not phone_number or not password:
            flash("Please enter both phone number and password.", "error")
            return redirect(url_for('login'))

        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT id, password_hash, is_banned, nickname FROM users WHERE phone_number = %s;", (phone_number,))
            user = cur.fetchone()
            if user:
                user_id, stored_hash, is_banned, nickname = user
                if is_banned:
                    flash("This account has been suspended.", "error")
                    return redirect(url_for('login'))
                if check_password_hash(stored_hash, password):
                    session['user_id'] = user_id
                    session['nickname'] = nickname
                    return redirect(url_for('dashboard'))
            flash("Invalid phone number or password.", "error")
        except Exception as e:
            flash("A server error occurred. Please try again.", "error")
        finally:
            cur.close()
            conn.close()
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    process_automated_payouts(user_id)
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT income_wallet, deposit_wallet FROM users WHERE id = %s;", (user_id,))
        wallets = cur.fetchone()
        income, deposit = wallets if wallets else (0.00, 0.00)
        cur.execute("SELECT id, name, price, daily_earning, duration_days FROM plans ORDER BY price ASC;")
        db_plans = cur.fetchall()
        available_plans = [{'id': p[0], 'name': p[1], 'price': p[2], 'daily': p[3], 'validity': p[4], 'total': p[3]*p[4]} for p in db_plans]
    finally:
        cur.close()
        conn.close()
    return render_template('dashboard.html', income=income, deposit=deposit, plans=available_plans)

@app.route('/invest/<int:plan_id>', methods=['POST'])
def invest_plan(plan_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT price, daily_earning, duration_days FROM plans WHERE id = %s;", (plan_id,))
        plan = cur.fetchone()
        if not plan:
            flash("Selected plan does not exist.", "error")
            return redirect(url_for('dashboard'))
        price, daily_earning, duration_days = plan
        cur.execute("SELECT deposit_wallet FROM users WHERE id = %s FOR UPDATE;", (user_id,))
        deposit_wallet = cur.fetchone()[0]
        if deposit_wallet < price:
            flash("Insufficient funds in deposit wallet! Please deposit first.", "error")
            return redirect(url_for('dashboard'))
        cur.execute("UPDATE users SET deposit_wallet = deposit_wallet - %s WHERE id = %s;", (price, user_id))
        cur.execute("INSERT INTO user_plans (user_id, plan_id, purchase_price, daily_earning, duration_days, last_payout) VALUES (%s, %s, %s, %s, %s, NOW());", (user_id, plan_id, price, daily_earning, duration_days))
        conn.commit()
        flash("Investment successfully activated!", "success")
    except Exception as e:
        conn.rollback()
        flash("Transaction failed. Try again.", "error")
    finally:
        cur.close()


# Configure file storage limits for screenshot vouchers
UPLOAD_FOLDER = 'static/uploads/vouchers'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ensure directory structure exists safely
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/deposit', methods=['GET', 'POST'])
def deposit():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    user_id = session['user_id']
    conn = get_db_connection()
    cur = conn.cursor()
    
    if request.method == 'POST':
        amount = request.form.get('amount', '').strip()
        channel = request.form.get('channel', '').strip()
        
        try:
            amount_num = float(amount)
        except ValueError:
            flash("Please enter a valid numeric amount.", "error")
            return redirect(url_for('deposit'))
            
        if amount_num < 70.00:
            flash("Minimum top-up threshold is GHS 70.00.", "error")
            return redirect(url_for('deposit'))
            
        if channel not in ['MTN', 'TELECEL']:
            flash("Please select a valid gateway channel.", "error")
            return redirect(url_for('deposit'))
            
        # Send details forward onto payment presentation engine
        return redirect(url_for('checkout', amount=amount_num, channel=channel))

    # GET request logic layout matching screenshot #1
    cur.execute("SELECT deposit_wallet FROM users WHERE id = %s;", (user_id,))
    user_wallet = cur.fetchone()
    deposit_balance = user_wallet[0] if user_wallet else 0.00
    cur.close()
    conn.close()
    
    return render_template('deposit.html', balance=deposit_balance)


@app.route('/checkout')
def checkout():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    amount = request.args.get('amount', '0.00')
    channel = request.args.get('channel', 'MTN')
    
    # Configure phone numbers to display depending on choice
    merchant_number = "0257425844" if channel == "MTN" else "0257425844"
    
    return render_template('checkout.html', amount=amount, channel=channel, number=merchant_number)


@app.route('/submit-voucher', methods=['POST'])
def submit_voucher():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    user_id = session['user_id']
    sender_name = request.form.get('sender_name', '').strip()
    amount = request.form.get('amount', '0.00')
    channel = request.form.get('channel', 'MTN')
    
    if not sender_name:
        flash("Sender's account name is required.", "error")
        return redirect(url_for('checkout', amount=amount, channel=channel))
        
    file = request.files.get('screenshot')
    filename = None
    
    if file and allowed_file(file.filename):
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        filename = secure_filename(f"user_{user_id}_{timestamp}_{file.filename}")
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """INSERT INTO deposits (user_id, amount, channel, sender_name, screenshot_filename)
               VALUES (%s, %s, %s, %s, %s);""",
            (user_id, float(amount), channel, sender_name, filename)
        )
        conn.commit()
        flash("Deposit submitted successfully! Processing takes 0-3 mins.", "success")
    except Exception as e:
        conn.rollback()
        flash("Submission failed. Try again.", "error")
    finally:
        cur.close()
        conn.close()
        
    return redirect(url_for('dashboard'))
  @app.route('/withdraw', methods=['GET', 'POST'])
def withdraw():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    user_id = session['user_id']
    conn = get_db_connection()
    cur = conn.cursor()
    
    if request.method == 'POST':
        amount = request.form.get('amount', '').strip()
        channel = request.form.get('channel', '').strip()
        wallet_number = request.form.get('wallet_number', '').strip()
        
        try:
            amount_num = float(amount)
        except ValueError:
            flash("Please enter a valid numeric value.", "error")
            return redirect(url_for('withdraw'))
            
        if amount_num < 50.00:
            flash("Minimum withdrawal threshold is GHS 50.00.", "error")
            return redirect(url_for('withdraw'))
            
        if not wallet_number or not re.match(r'^\d{9,15}$', wallet_number):
            flash("Please specify a valid payment phone number.", "error")
            return redirect(url_for('withdraw'))

        try:
            # Lock the current user row to prevent database multi-click race conditions
            cur.execute("SELECT income_wallet FROM users WHERE id = %s FOR UPDATE;", (user_id,))
            income_balance = cur.fetchone()[0]
            
            if income_balance < amount_num:
                flash("Insufficient funds in your income wallet portfolio.", "error")
                return redirect(url_for('withdraw'))
                
            # Deduct the pending transaction amount safely
            cur.execute("UPDATE users SET income_wallet = income_wallet - %s WHERE id = %s;", (amount_num, user_id))
            cur.execute(
                """INSERT INTO withdrawals (user_id, amount, channel, wallet_number)
                   VALUES (%s, %s, %s, %s);""",
                (user_id, amount_num, channel, wallet_number)
            )
            conn.commit()
            flash("Withdrawal request dispatched to admin processing queue.", "success")
            return redirect(url_for('dashboard'))
        except Exception as e:
            conn.rollback()
            flash("Processing error occurred. Please try again.", "error")
            return redirect(url_for('withdraw'))
        finally:
            cur.close()
            conn.close()

    # GET request handler: displays available income assets
    cur.execute("SELECT income_wallet FROM users WHERE id = %s;", (user_id,))
    income_balance = cur.fetchone()[0]
    cur.close()
    conn.close()
    return render_template('withdraw.html', balance=income_balance)

@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    user_id = session['user_id']
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # 1. Fetch current user balance info
        cur.execute("SELECT nickname, phone_number FROM users WHERE id = %s;", (user_id,))
        user_info = cur.fetchone()
        nickname, phone_number = user_info if user_info else ("User", "")

        # 2. Calculate Total Income earned historically from active user_plans
        cur.execute("SELECT COALESCE(SUM(days_accrued * daily_earning), 0.00) FROM user_plans WHERE user_id = %s;", (user_id,))
        total_income = cur.fetchone()[0]
        
        # 3. Calculate Total Approved Withdrawals
        cur.execute("SELECT COALESCE(SUM(amount), 0.00) FROM withdrawals WHERE user_id = %s AND status = 'Approved';", (user_id,))
        total_withdrawn = cur.fetchone()[0]
        
    except Exception as e:
        total_income = 0.00
        total_withdrawn = 0.00
        nickname, phone_number = "User", ""
    finally:
        cur.close()
        conn.close()
        
    return render_template('profile.html', 
                           nickname=nickname, 
                           phone=phone_number, 
                           total_income=total_income, 
                           total_withdrawn=total_withdrawn)

@app.route('/my-plans')
def my_plans():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    user_id = session['user_id']
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Fetch active or completed user investment contracts
        cur.execute("""
            SELECT up.purchase_price, up.daily_earning, up.days_accrued, up.duration_days, up.created_at, p.name 
            FROM user_plans up
            JOIN plans p ON up.plan_id = p.id
            WHERE up.user_id = %s
            ORDER BY up.created_at DESC;
        """, (user_id,))
        db_user_plans = cur.fetchall()
        
        active_contracts = []
        for row in db_user_plans:
            price, daily, accrued, duration, created_at, plan_name = row
            active_contracts.append({
                'name': plan_name,
                'price': price,
                'daily': daily,
                'days_left': max(0, duration - accrued),
                'total_earned': accrued * daily,
                'date': created_at.strftime('%Y-%m-%d %H:%M'),
                'is_active': accrued < duration
            })
    except Exception as e:
        active_contracts = []
    finally:
        cur.close()
        conn.close()
        
    return render_template('my_plans.html', contracts=active_contracts)


@app.route('/history')
def history():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    user_id = session['user_id']
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        ledger = []
        
        # 1. Pull historical user deposit transactions
        cur.execute("""
            SELECT amount, channel, status, created_at 
            FROM deposits 
            WHERE user_id = %s 
            ORDER BY created_at DESC;
        """, (user_id,))
        for row in cur.fetchall():
            ledger.append({
                'type': 'RECHARGE',
                'amount': f"+GHS {row[0]}",
                'meta': f"via {row[1]}",
                'status': row[2],
                'raw_date': row[3]
            })
            
        # 2. Pull historical user cash out withdrawal requests
        cur.execute("""
            SELECT amount, channel, status, created_at 
            FROM withdrawals 
            WHERE user_id = %s 
            ORDER BY created_at DESC;
        """, (user_id,))
        for row in cur.fetchall():
            ledger.append({
                'type': 'CASH OUT',
                'amount': f"-GHS {row[0]}",
                'meta': f"to {row[1]}",
                'status': row[2],
                'raw_date': row[3]
            })
            
        # 3. Pull historical network commission payout tracking rows
        cur.execute("""
            SELECT commission_amount, description, created_at 
            FROM referral_commissions 
            WHERE referrer_id = %s 
            ORDER BY created_at DESC;
        """, (user_id,))
        for row in cur.fetchall():
            ledger.append({
                'type': 'COMMISSION',
                'amount': f"+GHS {row[0]}",
                'meta': row[1],
                'status': 'Approved',
                'raw_date': row[2]
            })

        # Sort combined transaction metrics with the most recent at the top
        ledger.sort(key=lambda x: x['raw_date'], reverse=True)
        
        # Format timestamps cleanly for human scanning path
        for item in ledger:
            item['date'] = item['raw_date'].strftime('%Y-%m-%d %H:%M')
            
    except Exception as e:
        ledger = []
    finally:
        cur.close()
        conn.close()
        
    return render_template('history.html', logs=ledger)

@app.route('/service')
def service():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('service.html')
# -------------------------------------------------------------
# 👑 ISOLATED ADMIN CONTROL MODULES (HIDDEN RUNTIME)
# -------------------------------------------------------------

# Configuration parameters: Hardcoded master credential profile restriction
ADMIN_MASTER_PASSWORD = "Williams12" 

def admin_required(f):
    """Enforces administrative authentication checkpoints via server session tags."""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            flash("Unauthorized entry block triggered.", "error")
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/creston-control-center/login', methods=['GET', 'POST'])
def admin_login():
    """Bypasses standard navigation blocks entirely via hidden route access."""
    if request.method == 'POST':
        secret_input = request.form.get('admin_secret', '')
        
        if secret_input == ADMIN_MASTER_PASSWORD:
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            flash("Invalid master security authorization key.", "error")
            return redirect(url_for('admin_login'))
            
    return render_template('admin_login.html')


@app.route('/creston-control-center/dashboard')
@admin_required
def admin_dashboard():
    """Displays all database metrics including current balances and packages."""
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Audit tracking query collecting system wallets and plan purchases
    cur.execute("""
        SELECT u.id, u.nickname, u.phone_number, u.deposit_wallet, u.income_wallet, u.is_banned,
               (SELECT COUNT(*) FROM user_plans WHERE user_id = u.id) as active_plans
        FROM users u 
        ORDER BY u.created_at DESC;
    """)
    db_users = cur.fetchall()
    
    users_list = []
    for r in db_users:
        users_list.append({
            'id': r[0], 'nickname': r[1], 'phone': r[2],
            'deposit': r[3], 'income': r[4], 'banned': r[5], 'plans': r[6]
        })
        
    cur.close()
    conn.close()
    return render_template('admin_dashboard.html', users=users_list)


@app.route('/creston-control-center/approvals')
@admin_required
def admin_approvals():
    """Core transaction resolution gateway matrix."""
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Extract pending wallet recharge voucher uploads
    cur.execute("""
        SELECT d.id, u.phone_number, d.amount, d.channel, d.sender_name, d.screenshot_filename 
        FROM deposits d JOIN users u ON d.user_id = u.id
        WHERE d.status = 'Pending' ORDER BY d.created_at ASC;
    """)
    deposits_queue = [{
        'id': r[0], 'phone': r[1], 'amount': r[2], 'channel': r[3], 'name': r[4], 'file': r[5]
    } for r in cur.fetchall()]
    
    # Extract pending profit cash out withdrawal tasks
    cur.execute("""
        SELECT w.id, u.phone_number, w.amount, w.channel, w.wallet_number 
        FROM withdrawals w JOIN users u ON w.user_id = u.id
        WHERE w.status = 'Pending' ORDER BY w.created_at ASC;
    """)
    withdrawals_queue = [{
        'id': r[0], 'phone': r[1], 'amount': r[2], 'channel': r[3], 'target': r[4]
    } for r in cur.fetchall()]
    
    cur.close()
    conn.close()
    return render_template('admin_approvals.html', deposits=deposits_queue, withdrawals=withdrawals_queue)


@app.route('/creston-control-center/action/deposit/<int:tx_id>/<string:decision>', methods=['POST'])
@admin_required
def resolve_deposit_tx(tx_id, decision):
    """Processes voucher validations, balancing deposit metrics securely on approval."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT user_id, amount, status FROM deposits WHERE id = %s FOR UPDATE;", (tx_id,))
        tx = cur.fetchone()
        if tx and tx[2] == 'Pending':
            uid, amount, _ = tx
            if decision == 'approve':
                cur.execute("UPDATE deposits SET status = 'Approved' WHERE id = %s;", (tx_id,))
                cur.execute("UPDATE users SET deposit_wallet = deposit_wallet + %s WHERE id = %s;", (amount, uid))
            else:
                cur.execute("UPDATE deposits SET status = 'Rejected' WHERE id = %s;", (tx_id,))
            conn.commit()
    except Exception:
        conn.rollback()
    finally:
        cur.close()
        conn.close()
    return redirect(url_for('admin_approvals'))


@app.route('/creston-control-center/action/withdraw/<int:tx_id>/<string:decision>', methods=['POST'])
@admin_required
def resolve_withdraw_tx(tx_id, decision):
    """Executes pay resolutions, applying cash refunds automatically on structural denials."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT user_id, amount, status FROM withdrawals WHERE id = %s FOR UPDATE;", (tx_id,))
        tx = cur.fetchone()
        if tx and tx[2] == 'Pending':
            uid, amount, _ = tx
            if decision == 'approve':
                cur.execute("UPDATE withdrawals SET status = 'Approved' WHERE id = %s;", (tx_id,))
            else:
                cur.execute("UPDATE withdrawals SET status = 'Rejected' WHERE id = %s;", (tx_id,))
                cur.execute("UPDATE users SET income_wallet = income_wallet + %s WHERE id = %s;", (amount, uid))
            conn.commit()
    except Exception:
        conn.rollback()
    finally:
        cur.close()
        conn.close()
    return redirect(url_for('admin_approvals'))


@app.route('/creston-control-center/action/add-funds', methods=['POST'])
@admin_required
def admin_add_funds():
    """Allows manual balance additions to a user's wallet fields."""
    uid = request.form.get('user_id')
    amount = float(request.form.get('amount', 0))
    target_wallet = request.form.get('target_wallet')
    
    if target_wallet in ['deposit_wallet', 'income_wallet']:
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute(f"UPDATE users SET {target_wallet} = {target_wallet} + %s WHERE id = %s;", (amount, uid))
            conn.commit()
        except Exception:
            conn.rollback()
        finally:
            cur.close()
            conn.close()
    return redirect(url_for('admin_dashboard'))


@app.route('/creston-control-center/action/ban/<int:user_id>/<int:ban_status>', methods=['POST'])
@admin_required
def admin_toggle_ban_status(user_id, ban_status):
    """Toggles account ban states to restrict malicious profile entities."""
    is_banned = True if ban_status == 1 else False
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE users SET is_banned = %s WHERE id = %s;", (is_banned, user_id))
        conn.commit()
    finally:
        cur.close()
        conn.close()
    return redirect(url_for('admin_dashboard'))


@app.route('/creston-control-center/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('login'))
    # -------------------------------------------------------------
# PRODUCTION PRODUCTION SERVER ENTRYPOINT FOR RENDER
# -------------------------------------------------------------
if __name__ == '__main__':
    # Render passes a dynamic PORT configuration variable automatically
    port = int(os.environ.get("PORT", 5000))
    # debug=False turns off developer logs for secure public use
    app.run(host="0.0.0.0", port=port, debug=False)

