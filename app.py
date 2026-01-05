import os
from functools import wraps
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

# --- 1. Configuration ---
app.secret_key = os.environ.get('SECRET_KEY', 'super_secret_key_physio_expert')
db_url = os.environ.get('DATABASE_URL', 'sqlite:///physio.db')
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- 2. Models (تحديث الجداول) ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_confirmed = db.Column(db.Boolean, default=True)
    subscription_end_date = db.Column(db.DateTime, nullable=True)
    # [هام] هل هذا المستخدم مدير؟
    is_admin = db.Column(db.Boolean, default=False)

class Protocol(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    disease_name = db.Column(db.String(200), nullable=False)
    keywords = db.Column(db.String(500))
    protocol_text = db.Column(db.Text, nullable=False) # وصف العلاج
    # [هام] رابط صورة أماكن الإلكترودات
    electrode_image_url = db.Column(db.String(500), nullable=True)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- 3. Admin Security (حماية لوحة التحكم) ---
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # لو المستخدم مش مسجل دخول، أو مسجل بس مش مدير -> اطرده
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('غير مصرح لك بدخول منطقة الإدارة!', 'danger')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

# --- 4. Routes ---

@app.route('/')
@login_required
def home():
    # التحقق من الاشتراك (الكود السابق)
    now = datetime.utcnow()
    days_elapsed = (now - current_user.created_at).days
    is_trial = days_elapsed < 30
    is_subscribed = current_user.subscription_end_date and current_user.subscription_end_date > now
    
    if not (is_trial or is_subscribed):
        return redirect(url_for('subscribe'))
    
    days_left = 30 - days_elapsed if is_trial else (current_user.subscription_end_date - now).days
    
    # البحث
    result = None
    search_query = request.args.get('disease')
    if search_query:
        search_term = f"%{search_query}%"
        # البحث في الاسم أو الكلمات المفتاحية
        result = Protocol.query.filter(
            (Protocol.disease_name.ilike(search_term)) | 
            (Protocol.keywords.ilike(search_term))
        ).first()

    return render_template('index.html', result=result, days_left=days_left, user=current_user)

# --- منطقة الإدارة (Admin Panel) ---

@app.route('/admin')
@admin_required
def admin_dashboard():
    # عرض كل البروتوكولات الموجودة عشان تقدر تختار تعدل مين
    protocols = Protocol.query.all()
    return render_template('admin.html', protocols=protocols)

@app.route('/admin/add', methods=['GET', 'POST'])
@admin_required
def add_protocol():
    if request.method == 'POST':
        disease_name = request.form['disease_name']
        keywords = request.form['keywords']
        protocol_text = request.form['protocol_text']
        image_url = request.form['image_url'] # رابط الصورة
        
        new_protocol = Protocol(
            disease_name=disease_name,
            keywords=keywords,
            protocol_text=protocol_text,
            electrode_image_url=image_url
        )
        db.session.add(new_protocol)
        db.session.commit()
        flash('تم إضافة البروتوكول الجديد بنجاح!', 'success')
        return redirect(url_for('admin_dashboard'))
        
    return render_template('add_protocol.html')

@app.route('/admin/edit/<int:id>', methods=['GET', 'POST'])
@admin_required
def edit_protocol(id):
    protocol = Protocol.query.get_or_404(id)
    
    if request.method == 'POST':
        protocol.disease_name = request.form['disease_name']
        protocol.keywords = request.form['keywords']
        protocol.protocol_text = request.form['protocol_text']
        protocol.electrode_image_url = request.form['image_url']
        
        db.session.commit()
        flash('تم تعديل البروتوكول بنجاح!', 'success')
        return redirect(url_for('admin_dashboard'))
        
    return render_template('edit_protocol.html', protocol=protocol)

@app.route('/admin/delete/<int:id>')
@admin_required
def delete_protocol(id):
    protocol = Protocol.query.get_or_404(id)
    db.session.delete(protocol)
    db.session.commit()
    flash('تم حذف البروتوكول.', 'warning')
    return redirect(url_for('admin_dashboard'))

# --- مسار سري لمرة واحدة (عشان تحول نفسك لمدير) ---
@app.route('/make-me-admin')
@login_required
def make_me_admin():
    # هذا الرابط يحول المستخدم الحالي إلى مدير فوراً
    current_user.is_admin = True
    db.session.commit()
    return "مبروك! أنت الآن المدير (Admin). يمكنك الدخول إلى /admin"

# --- باقي المسارات (Login, Register, etc.) ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated: return redirect(url_for('home'))
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        if User.query.filter_by(email=email).first():
            flash('البريد مسجل مسبقاً', 'danger')
            return redirect(url_for('register'))
        hashed_pw = generate_password_hash(password, method='pbkdf2:sha256')
        new_user = User(email=email, password=hashed_pw, is_confirmed=True)
        db.session.add(new_user)
        db.session.commit()
        login_user(new_user)
        return redirect(url_for('home'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('home'))
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()
        if not user or not check_password_hash(user.password, password):
            flash('بيانات خاطئة', 'danger')
            return redirect(url_for('login'))
        login_user(user)
        return redirect(url_for('home'))
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/subscribe')
def subscribe(): return render_template('subscribe.html')
with app.app_context():
    db.drop_all()    # مسح القديم (التنظيف)
    db.create_all()  # بناء الجديد (بالتعديلات)
if __name__ == '__main__':
    app.run(debug=True)

