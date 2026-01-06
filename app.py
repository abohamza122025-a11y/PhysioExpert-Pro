import os
import base64  # <-- 1. مكتبة تشفير الصور
from functools import wraps
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'physio_expert_final_2026')

# إعدادات قاعدة البيانات
db_url = os.environ.get('DATABASE_URL', 'sqlite:///physio.db')
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(); login_manager.init_app(app); login_manager.login_view = 'login'

# --- حقن البيانات الثابتة ---
@app.context_processor
def inject_global_vars():
    return dict(
        support_email="physioexpert8@gmail.com",
        disclaimer="Disclaimer: This tool is for educational purposes only. Always consult a qualified specialist before applying treatments."
    )

# --- الجداول (Models) ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    subscription_end = db.Column(db.DateTime, nullable=True)

class Protocol(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    disease_name = db.Column(db.String(200), nullable=False)
    keywords = db.Column(db.String(500))
    description = db.Column(db.Text)
    
    estim_type = db.Column(db.String(200))
    estim_params = db.Column(db.Text)
    estim_role = db.Column(db.Text)
    
    us_type = db.Column(db.String(200))
    us_params = db.Column(db.Text)
    us_role = db.Column(db.Text)
    
    exercises_list = db.Column(db.Text)
    exercises_role = db.Column(db.Text)
    source_ref = db.Column(db.String(300))
    
    # 2. تغيير نوع العمود ليقبل نص صورة طويل جداً
    electrode_image = db.Column(db.Text) 

@login_manager.user_loader
def load_user(user_id): return User.query.get(int(user_id))

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Admin access required', 'danger')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

# --- المسارات ---

@app.route('/', methods=['GET', 'POST'])
@login_required
def home():
    if not current_user.is_admin:
        days_passed = (datetime.utcnow() - current_user.created_at).days
        days_left = 30 - days_passed
        has_extended_sub = current_user.subscription_end and current_user.subscription_end > datetime.utcnow()
        if days_left <= 0 and not has_extended_sub:
            return redirect(url_for('subscription_expired'))
    else:
        days_left = "Unlimited (Admin)"

    result = None
    search_query = request.args.get('disease') or request.form.get('disease')
    if search_query:
        term = f"%{search_query}%"
        result = Protocol.query.filter(
            (Protocol.disease_name.ilike(term)) | 
            (Protocol.keywords.ilike(term))
        ).first()
    
    return render_template('index.html', result=result, user=current_user, days_left=days_left)

@app.route('/subscription')
def subscription_expired():
    return render_template('subscribe.html') # تأكد أن لديك ملف subscribe.html أو استخدم الكود المباشر

@app.route('/admin')
@admin_required
def admin_dashboard():
    protocols = Protocol.query.all()
    return render_template('admin.html', protocols=protocols)

# --- إضافة (مع معالجة الصورة) ---
@app.route('/admin/add', methods=['GET', 'POST'])
@admin_required
def add_protocol():
    if request.method == 'POST':
        # 3. كود معالجة الصورة
        image_data = ""
        if 'electrode_image' in request.files:
            file = request.files['electrode_image']
            if file.filename != '':
                encoded_string = base64.b64encode(file.read()).decode('utf-8')
                image_data = f"data:image/jpeg;base64,{encoded_string}"
        
        p = Protocol(
            disease_name=request.form['disease_name'],
            keywords=request.form['keywords'],
            description=request.form['description'],
            estim_type=request.form['estim_type'],
            estim_params=request.form['estim_params'],
            estim_role=request.form['estim_role'],
            us_type=request.form['us_type'],
            us_params=request.form['us_params'],
            us_role=request.form['us_role'],
            exercises_list=request.form['exercises_list'],
            exercises_role=request.form['exercises_role'],
            source_ref=request.form['source_ref'],
            electrode_image=image_data # حفظ كود الصورة
        )
        db.session.add(p)
        db.session.commit()
        flash('Protocol & Image Added!', 'success')
        return redirect(url_for('admin_dashboard'))
    return render_template('add_protocol.html')

# --- تعديل (مع معالجة الصورة) ---
@app.route('/admin/edit/<int:id>', methods=['GET', 'POST'])
@admin_required
def edit_protocol(id):
    p = Protocol.query.get_or_404(id)
    if request.method == 'POST':
        p.disease_name = request.form['disease_name']
        p.keywords = request.form['keywords']
        p.description = request.form['description']
        p.estim_type = request.form['estim_type']
        p.estim_params = request.form['estim_params']
        p.estim_role = request.form['estim_role']
        p.us_type = request.form['us_type']
        p.us_params = request.form['us_params']
        p.us_role = request.form['us_role']
        p.exercises_list = request.form['exercises_list']
        p.exercises_role = request.form['exercises_role']
        p.source_ref = request.form['source_ref']
        
        # تحديث الصورة فقط لو تم رفع واحدة جديدة
        if 'electrode_image' in request.files:
            file = request.files['electrode_image']
            if file.filename != '':
                encoded_string = base64.b64encode(file.read()).decode('utf-8')
                p.electrode_image = f"data:image/jpeg;base64,{encoded_string}"
        
        db.session.commit()
        flash('Updated Successfully!', 'success')
        return redirect(url_for('admin_dashboard'))
    return render_template('edit_protocol.html', protocol=p)

@app.route('/admin/delete/<int:id>')
@admin_required
def delete_protocol(id):
    p = Protocol.query.get_or_404(id)
    db.session.delete(p)
    db.session.commit()
    flash('Deleted!', 'warning')
    return redirect(url_for('admin_dashboard'))

# --- Login & Setup ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form['email']).first()
        if user and check_password_hash(user.password, request.form['password']):
            login_user(user)
            return redirect(url_for('home'))
        else: flash('Login Failed', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        try:
            pw = generate_password_hash(request.form['password'], method='pbkdf2:sha256')
            db.session.add(User(email=request.form['email'], password=pw))
            db.session.commit()
            return redirect(url_for('login'))
        except: flash('Email exists', 'danger')
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout(): logout_user(); return redirect(url_for('login'))

@app.route('/setup-system')
def setup_system():
    try:
        db.drop_all(); db.create_all()
        admin_email = "admin@physio.com"; admin_pass = "admin123"
        hashed_pw = generate_password_hash(admin_pass, method='pbkdf2:sha256')
        db.session.add(User(email=admin_email, password=hashed_pw, is_admin=True))
        
        # دالة البيانات الكبيرة (تم اختصارها هنا لعدم التكرار، استخدم نفس البيانات السابقة)
        # ولكن تأكد أنك لا تضع صوراً في البيانات الافتراضية الآن إلا لو كانت base64
        # الأفضل ترك الصور فارغة في التثبيت الأولي
        
        db.session.commit()
        return "<h1>✅ System Reset & Updated for Images!</h1><a href='/login'>Login</a>"
    except Exception as e: return f"Error: {str(e)}"

if __name__ == '__main__':
    with app.app_context(): db.create_all()
    app.run(debug=True)
