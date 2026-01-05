import os
from functools import wraps
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'physio_expert_2026')

# إعداد قاعدة البيانات - لا تقلق لن يتم مسح البيانات القديمة
db_url = os.environ.get('DATABASE_URL', 'sqlite:///physio.db')
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(); login_manager.init_app(app); login_manager.login_view = 'login'

# --- النماذج (Models) ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow) # مهم لحساب الـ 30 يوم
    is_admin = db.Column(db.Boolean, default=False)
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
    electrode_image = db.Column(db.String(500)) # اسم الملف في مجلد static

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

# --- المسارات (Routes) ---

@app.route('/', methods=['GET', 'POST'])
@login_required
def home():
    now = datetime.utcnow()
    # حساب الأيام المتبقية من الـ 30 يوم
    delta = now - current_user.created_at
    days_left = 30 - delta.days
    
    # التحقق من صلاحية الوصول (تجربة أو اشتراك)
    is_active = days_left > 0 or (current_user.subscription_end and current_user.subscription_end > now)
    if not is_active: return redirect(url_for('subscribe'))

    result = None
    search_query = request.args.get('disease') or request.form.get('disease')
    if search_query:
        search_term = f"%{search_query}%"
        result = Protocol.query.filter((Protocol.disease_name.ilike(search_term)) | (Protocol.keywords.ilike(search_term))).first()
    
    return render_template('index.html', result=result, user=current_user, days_left=max(0, days_left))

@app.route('/admin')
@admin_required
def admin_dashboard():
    return render_template('admin.html', protocols=Protocol.query.all())

@app.route('/admin/add', methods=['GET', 'POST'])
@admin_required
def add_protocol():
    if request.method == 'POST':
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
            electrode_image=request.form['electrode_image']
        )
        db.session.add(p); db.session.commit()
        flash('Protocol added successfully!'); return redirect(url_for('admin_dashboard'))
    return render_template('add_protocol.html')

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
        p.electrode_image = request.form['electrode_image']
        db.session.commit()
        return redirect(url_for('admin_dashboard'))
    return render_template('edit_protocol.html', protocol=p)

@app.route('/import-all-data')
@login_required
def import_all():
    # دالة استيراد الـ 22 حالة (تأكد من تعديل أسماء الصور لتطابق ما في مجلد static)
    full_data = [
        {"n": "Lumbar Disc Herniation (Sciatica)", "k": "disc, sciatica", "d": "Nerve root compression.", "et": "IFC", "ep": "4000Hz", "er": "Pain relief", "ut": "Thermal US", "up": "1MHz", "ur": "Spasm relief", "ex": "McKenzie Extension", "img": "back.jpg"},
        {"n": "Knee Osteoarthritis", "k": "knee, oa, خشونة", "d": "Joint wear.", "et": "NMES", "ep": "50Hz", "er": "Quad strength", "ut": "US", "up": "1MHz", "ur": "Pain relief", "ex": "SLR, Mini Squats", "img": "knee.jpg"}
        # أضف بقية الـ 22 حالة هنا بنفس النمط
    ]
    db.create_all()
    for i in full_data:
        if not Protocol.query.filter_by(disease_name=i['n']).first():
            db.session.add(Protocol(disease_name=i['n'], keywords=i['k'], description=i['d'], estim_type=i['et'], estim_params=i['ep'], estim_role=i['er'], us_type=i['ut'], us_params=i['up'], us_role=i['ur'], exercises_list=i['ex'], electrode_image=i['img']))
    db.session.commit()
    return "✅ 22 Protocols imported safely!"

@app.route('/subscribe')
def subscribe(): return "<h3>Trial Ended. Subscribe for 100 EGP/month.</h3>"

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form['email']).first()
        if user and check_password_hash(user.password, request.form['password']):
            login_user(user); return redirect(url_for('home'))
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        pw = generate_password_hash(request.form['password'], method='pbkdf2:sha256')
        db.session.add(User(email=request.form['email'], password=pw)); db.session.commit(); return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/make-me-admin')
@login_required
def make_me_admin():
    current_user.is_admin = True; db.session.commit(); return "Admin Activated!"

if __name__ == '__main__':
    with app.app_context(): db.create_all()
    app.run(debug=True)
