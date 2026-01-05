import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

# --- 1. Configuration ---
app.secret_key = os.environ.get('SECRET_KEY', 'super_secret_key_physio_expert')

# --- 2. Database Configuration ---
db_url = os.environ.get('DATABASE_URL', 'sqlite:///physio.db')
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
}

# (تم حذف إعدادات الإيميل لأننا لم نعد نحتاجها)

# --- 3. Extensions ---
db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- 4. Models ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # جعلنا الافتراضي True ليتمكن المستخدم من الدخول فوراً
    is_confirmed = db.Column(db.Boolean, default=True) 

class Protocol(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    disease_name = db.Column(db.String(200), nullable=False)
    keywords = db.Column(db.String(500))
    protocol_text = db.Column(db.Text, nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- 5. Routes ---

@app.route('/')
@login_required
def home():
    # حساب فترة التجربة المجانية (30 يوم)
    days_elapsed = (datetime.utcnow() - current_user.created_at).days
    days_left = 30 - days_elapsed
    
    # إذا انتهت الفترة المجانية، حوله لصفحة الاشتراك
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
        
        # التأكد من عدم تكرار الإيميل
        user_exists = User.query.filter_by(email=email).first()
        if user_exists:
            flash('هذا البريد الإلكتروني مسجل بالفعل! حاول تسجيل الدخول.', 'danger')
            return redirect(url_for('register'))
        
        # إنشاء المستخدم الجديد
        hashed_pw = generate_password_hash(password, method='pbkdf2:sha256')
        # نضع is_confirmed=True مباشرة
        new_user = User(email=email, password=hashed_pw, is_confirmed=True)
        
        try:
            db.session.add(new_user)
            db.session.commit()
            
            # تسجيل الدخول تلقائياً بعد التسجيل (تجربة مستخدم أفضل)
            login_user(new_user)
            flash('تم إنشاء الحساب بنجاح! أهلاً بك في فترتك التجريبية.', 'success')
            return redirect(url_for('home'))
            
        except Exception as e:
            db.session.rollback()
            print(f"Database Error: {e}")
            flash('حدث خطأ أثناء التسجيل، حاول مرة أخرى.', 'danger')
            
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
        
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        remember = True if request.form.get('remember') else False
        
        user = User.query.filter_by(email=email).first()
        
        # التحقق من البيانات
        if not user or not check_password_hash(user.password, password):
            flash('البريد الإلكتروني أو كلمة المرور غير صحيحة.', 'danger')
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

# إنشاء الجداول عند البدء
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)
