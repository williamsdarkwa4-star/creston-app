# forms.py â€” Flask-WTF forms
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, DecimalField, SelectField, IntegerField
from wtforms.validators import DataRequired, Length, NumberRange, Optional

class RegisterForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=80)])
    phone = StringField('Phone', validators=[Optional(), Length(max=40)])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    referral = StringField('Referral code', validators=[Optional()])
    submit = SubmitField('Create account')

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Sign in')

class DepositForm(FlaskForm):
    amount = DecimalField('Amount', validators=[DataRequired(), NumberRange(min=1)], places=2)
    submit = SubmitField('Deposit')

class InvestForm(FlaskForm):
    plan = SelectField('Plan', choices=[], coerce=int)
    amount = DecimalField('Amount', validators=[DataRequired(), NumberRange(min=1)], places=2)
    submit = SubmitField('Invest')

class GiftClaimForm(FlaskForm):
    code = StringField('Gift code', validators=[DataRequired(), Length(max=64)])
    submit = SubmitField('Claim')

class ProfileForm(FlaskForm):
    phone = StringField('Phone', validators=[Optional(), Length(max=40)])
    password = PasswordField('New password (leave blank to keep)')
    submit = SubmitField('Save')
