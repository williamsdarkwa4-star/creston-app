import os
import psycopg2

def get_db_connection():
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        raise ValueError("DATABASE_URL environment variable is missing completely!")
    
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
        
    return psycopg2.connect(db_url)

def insert_investment_plan(*, name, min_limit, max_limit, roi, days):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO investment_plans (plan_name, min_limit, max_limit, roi_rate, term_days)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (plan_name) DO NOTHING
        """, (name, min_limit, max_limit, roi, days))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print("Failed to insert plan: " + str(e))

def init_db():
    commands = (
        """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(50) UNIQUE NOT NULL,
            email VARCHAR(100) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            wallet_balance NUMERIC(15, 2) DEFAULT 0.00,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS investment_plans (
            id SERIAL PRIMARY KEY,
            plan_name VARCHAR(30) UNIQUE NOT NULL,
            min_limit NUMERIC(12, 2) NOT NULL,
            max_limit NUMERIC(12, 2),
            roi_rate NUMERIC(5, 2) NOT NULL,
            term_days INT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS investments (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            plan_id INTEGER REFERENCES investment_plans(id),
            amount_invested NUMERIC(15, 2) NOT NULL,
            status VARCHAR(20) DEFAULT 'active',
            payout_date TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        for command in commands:
            cur.execute(command)
        cur.close()
        conn.commit()
        
        insert_investment_plan(name='Creston Alpha', min_limit=100.00, max_limit=1999.00, roi=5.00, days=7)
        insert_investment_plan(name='Creston Prime', min_limit=2000.00, max_limit=9999.00, roi=12.00, days=14)
        insert_investment_plan(name='Creston Zenith', min_limit=10000.00, max_limit=None, roi=30.00, days=30)
        
        print("CRESTON engine initialized.")
    except Exception as e:
        print("Database build error: " + str(e))
        raise e
    finally:
        if conn is not None:
            conn.close()

if __name__ == '__main__':
    init_db()
