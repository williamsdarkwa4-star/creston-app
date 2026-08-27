"""
Create database tables and seed an admin user (run once).
python create_db.py
"""
from app import create_app, db
from models import User, GiftCode
from werkzeug.security import generate_password_hash
import os

app = create_app()
with app.app_context():
    db.create_all()
    # create admin account if not exists
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        admin = User(username='admin', phone='', is_admin=True)
        admin.set_password('adminpass')
        admin.referral_code = 'ADMINCODE'
        db.session.add(admin)
    # sample gift code
    if not GiftCode.query.filter_by(code='WELCOME50').first():
        g = GiftCode(code='WELCOME50', amount=50.0)
        db.session.add(g)
    db.session.commit()
    print("DB initialized. Admin user created with username=admin password=adminpass (change ASAP).")
