import os
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_db_connection, init_db

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'creston_fallback_secure_key_2026')

@app.route('/db-init-secure-setup')
def dynamic_init():
    try:
        init_db()
        return "Creston Tables Successfully Created with Keyword-Only Safeguards."
    except Exception as e:
        return "Database Setup Failed: " + str(e)

@app.route('/')
def index():
    return render_template('base.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        email = request.form['email'].strip()
        password = request.form['password']
        hashed_password = generate_password_hash(password)
        
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                'INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s)',
                (username, email, hashed_password)
            )
            conn.commit()
            cur.close()
            conn.close()
            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            flash('Error: Duplicate user details or database issue.', 'danger')
            
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute('SELECT id, password_hash FROM users WHERE username = %s', (username,))
            user = cur.fetchone()
            cur.close()
            conn.close()
            
            if user and check_password_hash(user, password):
                session['user_id'] = user
                session['username'] = username
                return redirect(url_for('dashboard'))
            else:
                flash('Invalid username or password.', 'danger')
        except Exception as e:
            flash('System verification failed: ' + str(e), 'danger')
            
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute('SELECT wallet_balance FROM users WHERE id = %s', (session['user_id'],))
        balance_row = cur.fetchone()
        user_balance = float(balance_row) if balance_row else 0.00
        
        cur.execute("""
            SELECT p.plan_name, i.amount_invested, i.status, i.payout_date 
            FROM investments i
            JOIN investment_plans p ON i.plan_id = p.id
            WHERE i.user_id = %s
        """, (session['user_id'],))
        rows = cur.fetchall()
        
        investment_list = []
        for row in rows:
            investment_list.append({
                'plan_name': str(row),
                'amount': float(row),
                'status': str(row),
                'payout_date': row.strftime('%Y-%m-%d') if row else 'N/A'
            })
            
        cur.close()
        conn.close()
        return render_template('dashboard.html', balance=user_balance, investments=investment_list)
    except Exception as e:
        flash('Could not load portfolio: ' + str(e), 'danger')
        return render_template('dashboard.html', balance=0.00, investments=[])

@app.route('/deposit', methods=['GET', 'POST'])
def deposit():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        try:
            amount = float(request.form['amount'])
            if amount <= 0:
                flash('Please enter a valid deposit amount greater than $0.', 'danger')
                return redirect(url_for('deposit'))
                
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("UPDATE users SET wallet_balance = wallet_balance + %s WHERE id = %s", (amount, session['user_id']))
            conn.commit()
            cur.close()
            conn.close()
            
            flash(f'Successfully funded wallet with ${amount:,.2f}!', 'success')
            return redirect(url_for('dashboard'))
        except Exception as e:
            flash('Deposit failed: ' + str(e), 'danger')
            
    return render_template('deposit.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
