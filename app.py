import os
import random
import string
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.utils import secure_filename

app = Flask(__name__)
# FIXED: The description text string below is now safely commented out using a '#' hash symbol
# Secure fallback cryptography secret key generation
app.secret_key = os.environ.get('SECRET_KEY', 'creston-master-engine-production-key-2026')

UPLOAD_FOLDER = os.path.join('static', 'receipts')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def get_db_connection():
    # FIXED: Forces the application to check your Render environment configurations string variables
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        # If Render hasn't linked the database yet, this throws an explicit error instead of falling back to a broken local link
        raise RuntimeError("DATABASE_URL is missing. Please link your PostgreSQL database to this Web Service in your Render Dashboard.")
    return psycopg2.connect(db_url, cursor_factory=RealDictCursor)

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                nickname VARCHAR(100) NOT NULL,
                phone_number VARCHAR(20) UNIQUE NOT NULL,
                password VARCHAR(255) NOT NULL,
                invite_code VARCHAR(50) UNIQUE,
                referred_by VARCHAR(50),
                income_balance NUMERIC(15,2) DEFAULT 0.00,
                deposit_balance NUMERIC(15,2) DEFAULT 10.00,
                today_income NUMERIC(15,2) DEFAULT 0.00,
                total_income NUMERIC(15,2) DEFAULT 0.00,
                total_withdrawn NUMERIC(15,2) DEFAULT 0.00
            );
        ''')

        # Add withdrawal password safely
        cur.execute('''
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS withdraw_password VARCHAR(255);
        ''')

        cur.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id SERIAL PRIMARY KEY,
                user_id INT REFERENCES users(id) ON DELETE CASCADE,
                type VARCHAR(50) NOT NULL,
                amount NUMERIC(15,2) NOT NULL,
                status VARCHAR(50) DEFAULT 'pending',
                channel VARCHAR(50),
                meta_sender_name VARCHAR(150),
                screenshot_file VARCHAR(255),
                recipient_phone VARCHAR(50),
                network_provider VARCHAR(50),
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')
        cur.execute('''
       ALTER TABLE user_plans
        ADD COLUMN IF NOT EXISTS last_income_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
         ''')

        cur.execute('''
            CREATE TABLE IF NOT EXISTS user_plans (
                id SERIAL PRIMARY KEY,
                user_id INT REFERENCES users(id) ON DELETE CASCADE,
                plan_type INT NOT NULL,
                purchase_price NUMERIC(15,2) NOT NULL,
                daily_yield NUMERIC(15,2) NOT NULL,
                date_activated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')

        conn.commit()

    except Exception as e:
        conn.rollback()
        print("Database setup error:", e)

    finally:
        cur.close()
        conn.close()
try:
    init_db()
except Exception as e:
    print(f"PostgreSQL Production System Notice: {e}")
    
PLAN_CATALOG = {
    1: {"cost": 70, "daily": 8},
    2: {"cost": 100, "daily": 20},
    3: {"cost": 260, "daily": 45},
    4: {"cost": 400, "daily": 60},
    5: {"cost": 600, "daily": 100},
    6: {"cost": 800, "daily": 150},
    7: {"cost": 1000, "daily": 200}
}



def update_plan_income():
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT id, user_id, daily_yield, last_income_time
            FROM user_plans;
        """)

        plans = cur.fetchall()

        for plan in plans:
            current_time = datetime.utcnow()
            activated_time = plan['last_income_time']

            hours = (current_time - activated_time).total_seconds() / 3600

            if hours >= 24:

                amount = plan['daily_yield']

                # Add profit to user balance
                cur.execute("""
                    UPDATE users
                    SET income_balance = income_balance + %s,
                        today_income = today_income + %s,
                        total_income = total_income + %s
                    WHERE id = %s;
                """,
                (
                    amount,
                    amount,
                    amount,
                    plan['user_id']
                ))

                # Reset the 24-hour timer
                cur.execute("""
                    UPDATE user_plans
                    SET last_income_time = CURRENT_TIMESTAMP
                    WHERE id = %s;
                """,
                (plan['id'],))

        conn.commit()

    except Exception as e:
        conn.rollback()
        print("Income update error:", e)

    finally:
        cur.close()
        conn.close()

# ==========================================
# CLIENT USER INTERFACE PIPELINES
# ==========================================

@app.route('/')
def home_redirect():
    return redirect(url_for('register'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    url_invite_code = request.args.get('invite', 'RUFCR65')
    
    if request.method == 'POST':
        nickname = request.form.get('nickname')
        phone = request.form.get('phone_number').strip()
        password = request.form.get('password')
        invite_used = request.form.get('invite_code')
        
        my_invite_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        
        conn = get_db_connection()
        cur = conn.cursor()
        try:
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
            
    return render_template('register.html', invite_code=url_invite_code)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        phone = request.form.get('phone_number').strip()
        password = request.form.get('password')
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT id, nickname, password FROM users WHERE phone_number = %s;', (phone,))
        user = cur.fetchone()
        cur.close()
        conn.close()
        
        # FIXED: RealDictCursor checks require referencing string keys like ['password']
        if user and user['password'] == password:
            session['user_id'] = user['id']
            session['nickname'] = user['nickname']
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid credentials.")
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT income_balance, deposit_balance FROM users WHERE id = %s;', (session['user_id'],))
    wallet = cur.fetchone()
    cur.close()
    conn.close()
    update_plan_income()
    return render_template('dashboard.html', income_balance=wallet['income_balance'], deposit_balance=wallet['deposit_balance'])
       
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
        flash("Insufficient funds.")
        cur.close()
        conn.close()
        return redirect(url_for('dashboard'))
        
    cur.execute('UPDATE users SET deposit_balance = deposit_balance - %s WHERE id = %s;', (plan_cost, session['user_id']))
    cur.execute('INSERT INTO user_plans (user_id, plan_type, purchase_price, daily_yield) VALUES (%s, %s, %s, %s);',
                (session['user_id'], plan_id, plan_cost, plan_yield))
    conn.commit()
    cur.close()
    conn.close()
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
        if float(amount) < 60:
            flash("Minimum deposit requirement is GHS 60.")
            return redirect(url_for('deposit'))
        return redirect(url_for('payment_gateway', amount=amount, channel=channel))
        
    return render_template('deposit.html', available_balance=user['deposit_balance'])

@app.route('/payment_gateway')
def payment_gateway():
    if 'user_id' not in session: return redirect(url_for('login'))
    amount = request.args.get('amount', '0.00')
    channel = request.args.get('channel', 'MTN')
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
    return redirect(url_for('dashboard'))

@app.route('/withdraw', methods=['GET', 'POST'])
def withdraw():

    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT income_balance, withdraw_password
        FROM users
        WHERE id = %s;
    """, (session['user_id'],))

    user = cur.fetchone()


    if not user:
        cur.close()
        conn.close()
        flash("User account not found.")
        return redirect(url_for('login'))


    if request.method == 'POST':

        network = request.form.get('network_provider')
        phone = request.form.get('recipient_phone')
        password = request.form.get('withdraw_password')


        try:
            amount = float(request.form.get('withdraw_amount'))
        except:
            flash("Enter a valid withdrawal amount.")
            cur.close()
            conn.close()
            return redirect(url_for('withdraw'))



        # Check withdrawal password
        if not user['withdraw_password']:

            flash("Please set your withdrawal password first.")
            cur.close()
            conn.close()
            return redirect(url_for('profile'))


        if password != user['withdraw_password']:

            flash("Incorrect withdrawal password.")
            cur.close()
            conn.close()
            return redirect(url_for('withdraw'))



        # Minimum withdrawal
        if amount < 30:

            flash("Minimum withdrawal amount is GHS 30.")
            cur.close()
            conn.close()
            return redirect(url_for('withdraw'))



        # Balance check
        if amount > float(user['income_balance']):

            flash("Insufficient income balance.")
            cur.close()
            conn.close()
            return redirect(url_for('withdraw'))



        try:

            # Create withdrawal request
            cur.execute("""
                INSERT INTO transactions
                (
                    user_id,
                    type,
                    amount,
                    recipient_phone,
                    network_provider,
                    status
                )
                VALUES
                (
                    %s,
                    'withdrawal',
                    %s,
                    %s,
                    %s,
                    'pending'
                );
            """,
            (
                session['user_id'],
                amount,
                phone,
                network
            ))


            # Temporarily remove amount until admin decision
            cur.execute("""
                UPDATE users
                SET income_balance = income_balance - %s
                WHERE id = %s;
            """,
            (
                amount,
                session['user_id']
            ))


            conn.commit()

            flash("Withdrawal request submitted successfully.")


        except Exception as e:

            conn.rollback()
            flash("Withdrawal failed. Try again.")


        finally:

            cur.close()
            conn.close()


        return redirect(url_for('dashboard'))



    cur.close()
    conn.close()


    return render_template(
        'withdraw.html',
        income_balance=user['income_balance']
    )

@app.route('/set_withdraw_password', 
methods=['GET', 'POST'])
def set_withdraw_password():

    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':

        password = request.form.get('password')
        confirm = request.form.get('confirm_password')

        if password != confirm:
            flash("Passwords do not match.")
            return redirect(url_for('set_withdraw_password'))

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            UPDATE users
            SET withdraw_password=%s
            WHERE id=%s;
        """,
        (
            password,
            session['user_id']
        ))

        conn.commit()
        cur.close()
        conn.close()

        flash("Withdrawal password saved successfully.")
        return redirect(url_for('profile'))

    return render_template("set_withdraw_password.html")   
# ==========================================
# CLIENT SERVICE / SUPPORT ROUTE
# ==========================================

@app.route('/service')
def service():
    # Strict validation: ensure only authenticated accounts can reach support
    if 'user_id' not in session: 
        return redirect(url_for('login'))
        
    # Serves your custom templates/service.html layout frame instantly
    return render_template('service.html')
# ==========================================
# CLIENT HISTORY ROUTE
# ==========================================

@app.route('/history')
def history():
    # Strict check: ensure only logged-in clients can access their statements
    if 'user_id' not in session: 
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Queries deposits and cashout requests for this user, sorted newest first
    cur.execute('''
        SELECT type, amount, status, timestamp 
        FROM transactions 
        WHERE user_id = %s 
        ORDER BY timestamp DESC;
    ''', (session['user_id'],))
    
    logs = cur.fetchall()
    cur.close()
    conn.close()
    
    # Feeds data records directly into your templates/history.html UI view layer
    return render_template('history.html', logs=logs)
# ==========================================
# CLIENT INVITATION / AFFILIATE TEAM ROUTE
# ==========================================

@app.route('/invite')
def invite():
    # Strict navigation validation: block unauthenticated sessions
    if 'user_id' not in session: 
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 1. Fetch the logged-in client's custom invite code string token
    cur.execute('SELECT invite_code FROM users WHERE id = %s;', (session['user_id'],))
    me = cur.fetchone()
    
    # 2. Extract downline matching members listed under that referral code
    cur.execute('''
        SELECT nickname, phone_number 
        FROM users 
        WHERE referred_by = %s 
        ORDER BY id DESC;
    ''', (me['invite_code'],))
    
    team = cur.fetchall()
    cur.close()
    conn.close()
    
    # Passes data variables instantly into your templates/invite.html layout file
    return render_template('invite.html', invite_code=me['invite_code'], team=team)
# ==========================================
# CLIENT PROFILE & MY PLANS ROUTES
# ==========================================

@app.route('/profile')
def profile():
    # Strict validation: prevent unauthenticated tracking access
    if 'user_id' not in session: 
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Queries the live financial ledger metrics for this specific user row
    cur.execute('''
        SELECT id, phone_number, income_balance, today_income, total_income, total_withdrawn 
        FROM users 
        WHERE id = %s;
    ''', (session['user_id'],))
    
    user = cur.fetchone()
    cur.close()
    conn.close()
    
    # Feeds balances cleanly into your templates/profile.html interface layout
    return render_template('profile.html', 
                           user_id=user['id'], 
                           phone_number=user['phone_number'], 
                           income_balance=user['income_balance'], 
                           today_income=user['today_income'], 
                           total_income=user['total_income'], 
                           total_withdrawn=user['total_withdrawn'])


@app.route('/my_plans')
def my_plans():

    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT 
            plan_type,
            purchase_price,
            daily_yield,
            date_activated
        FROM user_plans
        WHERE user_id = %s
        ORDER BY date_activated DESC;
    """, (session['user_id'],))

    plans = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        'my_plans.html',
        active_plans=plans
    )
# ==========================================
# MASTER ADMINISTRATIVE SECURITY ENDPOINTS
# ==========================================
@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out successfully.")
    return redirect(url_for('login'))

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        user = request.form.get('Williams')
        pw = request.form.get('Williams12')
        # Setup static admin panel login configuration credentials details
        if user == "Williams" and pw == "Williams12":
            session['admin_logged'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            flash("Invalid security authorization credentials.")
    return render_template('admin/login.html')

@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('admin_logged'): return redirect(url_for('admin_login'))
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) as total FROM users;')
    users_count = cur.fetchone()['total']
    cur.execute('SELECT SUM(income_balance + deposit_balance) as total_cap FROM users;')
    cap = cur.fetchone()['total_cap'] or 0.00
    cur.close()
    conn.close()
    return render_template('admin/dashboard.html', total_users=users_count, total_capital=cap)

@app.route('/admin/approvals')
def admin_approvals():
    if not session.get('admin_logged'): return redirect(url_for('admin_login'))
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''SELECT t.id, t.type, t.amount, t.channel, t.meta_sender_name, t.screenshot_file, t.recipient_phone, t.network_provider, u.phone_number 
                   FROM transactions t JOIN users u ON t.user_id = u.id WHERE t.status = 'pending' ORDER BY t.timestamp ASC;''')
    txs = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('admin/approvals.html', pending_transactions=txs)

@app.route('/admin/action_transaction/<int:tx_id>/<string:action>')
def action_transaction(tx_id, action):

    if not session.get('admin_logged'):
        return redirect(url_for('admin_login'))

    conn = get_db_connection()
    cur = conn.cursor()

    try:

        cur.execute("""
            SELECT user_id, type, amount, status
            FROM transactions
            WHERE id=%s;
        """,(tx_id,))

        tx = cur.fetchone()


        if not tx:
            flash("Transaction not found.")
            return redirect(url_for('admin_approvals'))


        # Prevent double approval
        if tx['status'] != 'pending':
            flash("Transaction already processed.")
            return redirect(url_for('admin_approvals'))


        if action == "approve":

            cur.execute("""
                UPDATE transactions
                SET status='approved'
                WHERE id=%s;
            """,(tx_id,))


            if tx['type'] == 'deposit':

                cur.execute("""
                    UPDATE users
                    SET deposit_balance =
                    deposit_balance + %s
                    WHERE id=%s;
                """,
                (
                    tx['amount'],
                    tx['user_id']
                ))


            elif tx['type'] == 'withdrawal':

                cur.execute("""
                    UPDATE users
                    SET total_withdrawn =
                    total_withdrawn + %s
                    WHERE id=%s;
                """,
                (
                    tx['amount'],
                    tx['user_id']
                ))



        elif action == "reject":

            cur.execute("""
                UPDATE transactions
                SET status='rejected'
                WHERE id=%s;
            """,(tx_id,))


            # Return withdrawal money
            if tx['type'] == 'withdrawal':

                cur.execute("""
                    UPDATE users
                    SET income_balance =
                    income_balance + %s
                    WHERE id=%s;
                """,
                (
                    tx['amount'],
                    tx['user_id']
                ))


        conn.commit()
        flash("Transaction updated successfully.")


    except Exception as e:
        conn.rollback()
        flash("Transaction update failed.")


    finally:
        cur.close()
        conn.close()


    return redirect(url_for('admin_approvals'))

@app.route('/admin/users')
def admin_users():
    if not session.get('admin_logged'): return redirect(url_for('admin_login'))
    conn = get_db_connection()
    cur = conn.cursor()
    # Pulls complete data mapping user list phone number and current balance configurations
    cur.execute('SELECT nickname, phone_number, (income_balance + deposit_balance) as wallet_balance FROM users ORDER BY id DESC;')
    members = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('admin/users.html', members=members)

@app.route('/admin/password_reset', methods=['GET', 'POST'])
def admin_password_reset():
    if not session.get('admin_logged'): return redirect(url_for('admin_login'))
    if request.method == 'POST':
        phone = request.form.get('target_phone').strip()
        new_pw = request.form.get('new_password')
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('UPDATE users SET password = %s WHERE phone_number = %s;', (new_pw, phone))
        conn.commit()
        cur.close()
        conn.close()
        flash(f"Access password for +233 {phone} updated successfully.")
    return render_template('admin/password_reset.html')
@app.route('/admin/adjust_balance', methods=['GET', 'POST'])
def admin_adjust_balance():
    if not session.get('admin_logged'):
        return redirect(url_for('admin_login'))

    if request.method == 'POST':
        phone = request.form.get('phone_number').strip()
        wallet = request.form.get('wallet')
        action = request.form.get('action')
        amount = float(request.form.get('amount'))

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            "SELECT id FROM users WHERE phone_number=%s;",
            (phone,)
        )
        user = cur.fetchone()

        if not user:
            flash("User not found.")
            cur.close()
            conn.close()
            return redirect(url_for('admin_adjust_balance'))

        if wallet not in ["deposit_balance", "income_balance"]:
            flash("Invalid wallet selected.")
            cur.close()
            conn.close()
            return redirect(url_for('admin_adjust_balance'))

        if action == "add":
            cur.execute(
                f"UPDATE users SET {wallet} = {wallet} + %s WHERE phone_number=%s;",
                (amount, phone)
            )
            flash("Funds added successfully.")

        elif action == "deduct":
            cur.execute(
                f"UPDATE users SET {wallet} = GREATEST({wallet} - %s, 0) WHERE phone_number=%s;",
                (amount, phone)
            )
            flash("Funds deducted successfully.")

        conn.commit()
        cur.close()
        conn.close()

        return redirect(url_for('admin_adjust_balance'))

    return render_template("admin/adjust_balance.html")

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged', None)
    return redirect(url_for('admin_login'))

if __name__ == "__main__":
    app.run(debug=True)
