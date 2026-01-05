import os
from threading import Thread # (1) استيراد مكتبة الـ Threading
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer, SignatureExpired

app = Flask(__name__)

# --- Configuration ---
app.secret_key = os.environ.get('SECRET_KEY', 'super_secret_key_physio_expert')

# إعدادات قاعدة البيانات
db_url = os.environ.get('DATABASE_URL', 'sqlite:///physio.db')
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# (2) حل مشكلة انقطاع الاتصال (EOF detected)
# هذا الكود يجعل SQLAlchemy يفحص الاتصال قبل استخدامه
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
}

# إعدادات البريد الإلكتروني
app.config['MAIL_SERVER'] = 'smtp.googlemail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['SECURITY_PASSWORD_SALT'] = os.environ.get('SECURITY_PASSWORD_SALT', 'email_confirm_salt')

db = SQLAlchemy(app)
mail = Mail(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
s = URLSafeTimedSerializer(app.secret_key)

# --- Database Models ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_confirmed = db.Column(db.Boolean, default=False)

class Protocol(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    disease_name = db.Column(db.String(200), nullable=False)
    keywords = db.Column(db.String(500))
    protocol_text = db.Column(db.Text, nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- (3) دالة إرسال الإيميل في الخلفية ---
def send_async_email(app, msg):
    with app.app_context():
        try:
            mail.send(msg)
        except Exception as e:
            print(f"Error sending email: {e}")

def send_confirmation_email(user_email):
    token = s.dumps(user_email, salt=app.config['SECURITY_PASSWORD_SALT'])
    link = url_for('confirm_email', token=token, _external=True)
    msg = Message('تفعيل حساب Physio Expert', sender=app.config['MAIL_USERNAME'], recipients=[user_email])
    msg.body = f'أهلاً بك! لتفعيل حسابك يرجى الضغط على الرابط التالي: {link}'
    
    # تشغيل الإرسال في Thread منفصل عشان الموقع ميعلقش
    Thread(target=send_async_email, args=(app, msg)).start()

# --- Routes ---

@app.route('/')
@login_required
def home():
    days_elapsed = (datetime.utcnow() - current_user.created_at).days
    days_left = 30 - days_elapsed
    
    if days_left <= 0:
        return redirect(url_for('subscribe'))
    
    result = None
    search_query = request.args.get('disease') or request.form.get('disease')
    if search_query:
        search_term = f"%{search_query}%"
        protocol = Protocol.query.filter(
            (Protocol.disease_name.ilike(search_term)) | 
            (Protocol.keywords.ilike(search_term))
        ).first()
        result = protocol if protocol else "Not Found"

    return render_template('index.html', result=result, days_left=days_left, user=current_user)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        user_exists = User.query.filter_by(email=email).first()
        if user_exists:
            flash('هذا البريد الإلكتروني مسجل بالفعل!', 'danger')
            return redirect(url_for('register'))
        
        hashed_pw = generate_password_hash(password, method='pbkdf2:sha256')
        new_user = User(email=email, password=hashed_pw)
        
        try:
            db.session.add(new_user)
            db.session.commit()
            send_confirmation_email(email)
            flash('تم إنشاء الحساب بنجاح! تم إرسال رابط التفعيل إلى بريدك الإلكتروني.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            db.session.rollback() # تراجع عن الحفظ لو حصل خطأ
            print(f"Error: {e}")
            flash('حدث خطأ أثناء التسجيل، حاول مرة أخرى.', 'danger')
            
    return render_template('register.html')

@app.route('/confirm/<token>')
def confirm_email(token):
    try:
        email = s.loads(token, salt=app.config['SECURITY_PASSWORD_SALT'], max_age=3600)
    except SignatureExpired:
        flash('رابط التفعيل منتهي الصلاحية.', 'danger')
        return redirect(url_for('login'))
    except Exception:
        flash('رابط التفعيل غير صحيح.', 'danger')
        return redirect(url_for('login'))
    
    user = User.query.filter_by(email=email).first_or_404()
    if user.is_confirmed:
        flash('الحساب مفعل بالفعل. قم بتسجيل الدخول.', 'success')
    else:
        user.is_confirmed = True
        db.session.commit()
        flash('تم تفعيل حسابك بنجاح!', 'success')
        
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
        
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        remember = True if request.form.get('remember') else False
        
        user = User.query.filter_by(email=email).first()
        
        if not user or not check_password_hash(user.password, password):
            flash('تأكد من البريد الإلكتروني وكلمة المرور.', 'danger')
            return redirect(url_for('login'))
        
        if not user.is_confirmed:
            flash('يرجى تفعيل حسابك أولاً من خلال الرابط المرسل لبريدك.', 'warning')
            return redirect(url_for('login'))
            
        login_user(user, remember=remember)
        return redirect(url_for('home'))
        
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/subscribe')
@login_required
def subscribe():
    return render_template('subscribe.html')

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)
