
# models.py â€” SQLAlchemy models
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    phone = db.Column(db.String(40))
    password_hash = db.Column(db.String(255), nullable=False)
    deposit_balance = db.Column(db.Float, default=0.0)
    income_balance = db.Column(db.Float, default=0.0)
    referral_balance = db.Column(db.Float, default=0.0)
    withdrawable_balance = db.Column(db.Float, default=0.0)
    referral_code = db.Column(db.String(64), unique=True)
    referred_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)

    def set_password_hash(self, pw_hash):
        self.password_hash = pw_hash

    def generate_referral_code(self):
        base = (self.username or 'user').upper()
        base = ''.join([c for c in base if c.isalnum()])[:6]
        import os, binascii
        self.referral_code = f"{base}{binascii.b2a_hex(os.urandom(2)).decode('ascii').upper()}"

    # flask-login compatibility
    def get_id(self):
        return str(self.id)

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type = db.Column(db.String(80), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(50), default='completed')
    note = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Investment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    plan_name = db.Column(db.String(120), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    apy = db.Column(db.Float, nullable=False)
    duration_days = db.Column(db.Integer, nullable=False)
    start_at = db.Column(db.DateTime, default=datetime.utcnow)
    redeemed = db.Column(db.Boolean, default=False)

class GiftCode(db.Model):
    code = db.Column(db.String(64), primary_key=True)
    amount = db.Column(db.Float, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=True)
    max_uses = db.Column(db.Integer, default=1)
    uses = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class GiftClaim(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(64), db.ForeignKey('gift_code.code'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    claimed_at = db.Column(db.DateTime, default=datetime.utcnow)

class Referral(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    referrer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    referee_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
