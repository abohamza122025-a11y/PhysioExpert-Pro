import os
import base64
import pandas as pd  # مكتبة معالجة الإكسيل
from functools import wraps
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename  # لتأمين أسماء الملفات المرفوعة

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'physio_expert_final_2026')

# --- إعدادات مجلد رفع الصور ---
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# --- فلتر لتقسيم النصوص إلى قوائم (للتدريبات) ---
@app.template_filter('split_list')
def split_list_filter(s, delimiter=','):
    if s:
        return [x.strip() for x in s.split(delimiter)]
    return []

# --- 1. إعدادات قاعدة البيانات ---
db_url = os.environ.get('DATABASE_URL', 'sqlite:///physio.db')
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(); login_manager.init_app(app); login_manager.login_view = 'login'

# --- بيانات الموقع الثابتة ---
@app.context_processor
def inject_global_vars():
    return dict(
        support_email="physioexpert8@gmail.com",
        disclaimer="Disclaimer: This tool is for educational purposes only. Always consult a qualified specialist before applying treatments."
    )

# --- 2. الجداول (Models) ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    subscription_end = db.Column(db.DateTime, nullable=True)

class Protocol(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(100)) # أضفنا التصنيف
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
    ex_frequency = db.Column(db.String(200)) # حقول إضافية للجرعات
    ex_intensity = db.Column(db.String(200))
    ex_progression = db.Column(db.Text)
    evidence_level = db.Column(db.String(50))
    source_ref = db.Column(db.String(300))
    electrode_image = db.Column(db.Text)  # يدعم المسار أو التشفير
    is_protected = db.Column(db.Boolean, default=False)

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

# --- 3. المسارات (Routes) ---

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

@app.route('/admin')
@admin_required
def admin_dashboard():
    protocols = Protocol.query.all()
    return render_template('admin.html', protocols=protocols)

# --- إضافة بروتوكول يدوي (مع دعم رفع الصورة من الكمبيوتر) ---
@app.route('/admin/add-manual', methods=['POST'])
@admin_required
def add_manual():
    image_path = ""
    if 'electrode_image' in request.files:
        file = request.files['electrode_image']
        if file.filename != '':
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            image_path = f"/static/uploads/{filename}"
    
    p = Protocol(
        disease_name=request.form['disease_name'],
        category=request.form.get('category', 'General'),
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
        ex_frequency=request.form.get('ex_frequency'),
        ex_intensity=request.form.get('ex_intensity'),
        source_ref=request.form['source_ref'],
        electrode_image=image_path,
        is_protected=False
    )
    db.session.add(p)
    db.session.commit()
    flash('Manual Protocol Added Successfully!', 'success')
    return redirect(url_for('admin_dashboard'))

# --- رفع بروتوكولات بالجملة عبر الإكسيل ---
@app.route('/admin/import-excel', methods=['POST'])
@admin_required
def import_excel():
    if 'excel_file' not in request.files:
        flash('No file selected', 'danger')
        return redirect(url_for('admin_dashboard'))
    
    file = request.files['excel_file']
    try:
        df = pd.read_excel(file)
        for _, row in df.iterrows():
            new_p = Protocol(
                disease_name=str(row['disease_name']),
                category=str(row.get('category', 'General')),
                keywords=str(row.get('keywords', '')),
                description=str(row.get('description', '')),
                exercises_list=str(row['exercises_list']),
                ex_frequency=str(row.get('ex_frequency', '3 times/week')),
                evidence_level=str(row.get('evidence_level', 'Grade A')),
                is_protected=False
            )
            db.session.add(new_p)
        db.session.commit()
        flash(f'Successfully imported {len(df)} protocols!', 'success')
    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete/<int:id>')
@admin_required
def delete_protocol(id):
    p = Protocol.query.get_or_404(id)
    db.session.delete(p)
    db.session.commit()
    flash('Protocol Deleted', 'warning')
    return redirect(url_for('admin_dashboard'))

# --- المصادقة ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form['email']).first()
        if user and check_password_hash(user.password, request.form['password']):
            login_user(user)
            return redirect(url_for('home'))
        else:
            flash('Login Failed. Check email/password', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout(): logout_user(); return redirect(url_for('login'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=False)
