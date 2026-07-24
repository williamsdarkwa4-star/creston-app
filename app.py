import os
import random
import string
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'creston-master-system-engine-key-2026')

UPLOAD_FOLDER = os.path.join('static', 'receipts')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def get_db_connection():
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        # Local Pydroid 3 terminal isolated manual sandbox connection parameter string
        return psycopg2.connect("dbname=creston_db user=postgres password=secret", cursor_factory=RealDictCursor)
    return psycopg2.connect(db_url, cursor_factory=RealDictCursor)

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    # 1. Primary Membership Registry User Profile Matrix Table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            nickname VARCHAR(100) NOT NULL,
            phone_number VARCHAR(20) UNIQUE NOT NULL,
            password VARCHAR(255) NOT NULL,
            invite_code VARCHAR(50) UNIQUE,
            referred_by VARCHAR(50),
            income_balance NUMERIC(15, 2) DEFAULT 0.00,
            deposit_balance NUMERIC(15, 2) DEFAULT 10.00, -- Automatically receive GHS 10 sign up bonus
            today_income NUMERIC(15, 2) DEFAULT 0.00,
            total_income NUMERIC(15, 2) DEFAULT 0.00,
            total_withdrawn NUMERIC(15, 2) DEFAULT 0.00
        );
    ''')
    # 2. Financial Auditing Transaction Ledger Table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id SERIAL PRIMARY KEY,
            user_id INT REFERENCES users(id) ON DELETE CASCADE,
            type VARCHAR(50) NOT NULL, -- 'deposit' or 'withdrawal'
            amount NUMERIC(15, 2) NOT NULL,
            status VARCHAR(50) DEFAULT 'pending', -- 'pending', 'approved', 'rejected'
            channel VARCHAR(50),
            meta_sender_name VARCHAR(150),
            screenshot_file VARCHAR(255),
            recipient_phone VARCHAR(50),
            network_provider VARCHAR(50),
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    # 3. Active Running Power Plan Inventory Catalog Inventory Tracker Table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS user_plans (
            id SERIAL PRIMARY KEY,
            user_id INT REFERENCES users(id) ON DELETE CASCADE,
            plan_type INT NOT NULL,
            purchase_price NUMERIC(15, 2) NOT NULL,
            daily_yield NUMERIC(15, 2) NOT NULL,
            date_activated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    conn.commit()
    cur.close()
    conn.close()

try:
    init_db()
except Exception as e:
    print(f"Database Initialized System Note: {e}")

# Static package data tracking configuration matrices representing your 7 tiers
PLAN_CATALOG = {
    1: {"cost": 70, "daily": 8},
    2: {"cost": 100, "daily": 20},
    3: {"cost": 260, "daily": 45},
    4: {"cost": 400, "daily": 60},
    5: {"cost": 600, "daily": 100},
    6: {"cost": 800, "daily": 150},
    7: {"cost": 1000, "daily": 200}
}

# ==========================================
# CLIENT SYSTEM TERMINAL ROUTES
# ==========================================

@app.route('/')
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        nickname = request.form.get('nickname')
        phone = request.form.get('phone_number').strip()
        password = request.form.get('password')
        invite_used = request.form.get('invite_code')
        
        my_invite_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            # Mandated rule: deposit_balance starts with a free GHS 10.00 signup allocation
            cur.execute(
                '''INSERT INTO users (nickname, phone_number, password, invite_code, referred_by, deposit_balance) 
                   VALUES (%s, %s, %s, %s, %s, 10.00);''',
                (nickname, phone, password, my_invite_code, invite_used)
            )
            conn.commit()
            flash("Account securely provisioned with GHS 10 welcome bonus! Login now.")
            return redirect(url_for('login'))
        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            flash("This operational phone number string is already registered.")
        finally:
            cur.close()
            conn.close()
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        phone = request.form.get('phone_number').strip()
        password = request.form.get('password')
        
        conn = get_db_connection()
        cur = conn.cursor()
        # id is index 0, nickname is index 1, password is index 2
        cur.execute('SELECT id, nickname, password FROM users WHERE phone_number = %s;', (phone,))
        user = cur.fetchone()
        cur.close()
        conn.close()
        
        # Fixed comparison using explicit database row item index spacing
        if user and user[2] == password:
            session['user_id'] = user[0]
            session['nickname'] = user[1]
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid authentication credential pairing.")
            
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: 
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    cur = conn.cursor()
    # income_balance is index 0, deposit_balance is index 1
    cur.execute('SELECT income_balance, deposit_balance FROM users WHERE id = %s;', (session['user_id'],))
    wallet = cur.fetchone()
    cur.close()
    conn.close()
    
    # Safely unpack the numeric tuple items cleanly for Jinja2
    return render_template('dashboard.html', income_balance=wallet[0], deposit_balance=wallet[1])


@app.route('/invest', methods=['POST'])
def invest():
    if 'user_id' not in session: return redirect(url_for('login'))
    plan_id = int(request.form.get('plan_id', 0))
    if plan_id not in PLAN_CATALOG: return redirect(url_for('dashboard'))
    
    plan_cost = PLAN_CATALOG[plan_id]["cost"]
    plan_yield = PLAN_CATALOG[plan_id]["daily"]
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT deposit_balance FROM users WHERE id = %s;', (session['user_id'],))
    user = cur.fetchone()
    
    if float(user['deposit_balance']) < plan_cost:
        flash("Insufficient funds in Deposit Wallet to acquire this package.")
        cur.close()
        conn.close()
        return redirect(url_for('dashboard'))
        
    cur.execute('UPDATE users SET deposit_balance = deposit_balance - %s WHERE id = %s;', (plan_cost, session['user_id']))
    cur.execute('INSERT INTO user_plans (user_id, plan_type, purchase_price, daily_yield) VALUES (%s, %s, %s, %s);',
                (session['user_id'], plan_id, plan_cost, plan_yield))
    conn.commit()
    cur.close()
    conn.close()
    flash(f"CRESTON Plan #{plan_id} activated successfully! Running compounding ledger synced.")
    return redirect(url_for('profile'))

@app.route('/deposit', methods=['GET', 'POST'])
def deposit():
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT deposit_balance FROM users WHERE id = %s;', (session['user_id'],))
    user = cur.fetchone()
    cur.close()
    conn.close()
    
    if request.method == 'POST':
        amount = request.form.get('amount')
        channel = request.form.get('channel')
        if float(amount) < 70:
            flash("Minimum deposit requirement is GHS 70.")
            return redirect(url_for('deposit'))
        return redirect(url_for('payment_gateway', amount=amount, channel=channel))
        
    return render_template('deposit.html', available_balance=user['deposit_balance'])

@app.route('/payment_gateway')
def payment_gateway():
    if 'user_id' not in session: return redirect(url_for('login'))
    amount = request.args.get('amount', '0.00')
    channel = request.args.get('channel', 'MTN')
    # Displays your explicit centralized collection merchant numbers
    merchant_number = "0257425844"
    return render_template('payment_gateway.html', amount=amount, channel=channel, merchant_number=merchant_number)

@app.route('/submit_deposit_proof', methods=['POST'])
def submit_deposit_proof():
    if 'user_id' not in session: return redirect(url_for('login'))
    sender_name = request.form.get('sender_name')
    amount = request.form.get('amount')
    channel = request.form.get('channel')
    file = request.files.get('screenshot')
    
    if file:
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''INSERT INTO transactions (user_id, type, amount, channel, meta_sender_name, screenshot_file, status) 
                       VALUES (%s, 'deposit', %s, %s, %s, %s, 'pending');''',
                    (session['user_id'], amount, channel, sender_name, filename))
        conn.commit()
        cur.close()
        conn.close()
        flash("Proof of deposit sent successfully to admin for approval.")
    return redirect(url_for('dashboard'))

@app.route('/withdraw', methods=['GET', 'POST'])
def withdraw():
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT income_balance FROM users WHERE id = %s;', (session['user_id'],))
    user = cur.fetchone()
    cur.close()
    conn.close()
    
    if request.method == 'POST':
        network = request.form.get('network_provider')
        phone = request.form.get('recipient_phone')
        amount = float(request.form.get('withdraw_amount', 0))
        
