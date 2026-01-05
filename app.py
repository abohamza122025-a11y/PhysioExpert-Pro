import os
from functools import wraps
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'physio_expert_2026')

# إعداد قاعدة البيانات
db_url = os.environ.get('DATABASE_URL', 'sqlite:///physio.db')
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# النماذج (Models)
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_admin = db.Column(db.Boolean, default=False)

class Protocol(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    disease_name = db.Column(db.String(200), nullable=False)
    keywords = db.Column(db.String(500))
    protocol_text = db.Column(db.Text, nullable=False)
    electrode_image_url = db.Column(db.String(500), nullable=True)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# حماية الأدمن
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('منطقة محظورة!', 'danger')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

# --- المسارات (Routes) ---

@app.route('/', methods=['GET', 'POST'])
@login_required
def home():
    result = None
    search_query = request.args.get('disease') or request.form.get('disease')
    if search_query:
        search_term = f"%{search_query}%"
        result = Protocol.query.filter(
            (Protocol.disease_name.ilike(search_term)) | 
            (Protocol.keywords.ilike(search_term))
        ).first()
    return render_template('index.html', result=result, user=current_user)

@app.route('/import-data')
def import_data():
    data = [
        {"n": "Knee Osteoarthritis - خشونة الركبة", "k": "knee, oa, خشونة, الركبة", "t": "NMES: 50Hz. Strengthening Quads. Exercises: Quad Sets, SLR, Mini Squats."},
        {"n": "Lumbar Disc - الديسك", "k": "back, disc, ديسك, ظهر", "t": "IFC Carrier: 4000Hz. Exercises: McKenzie Extension, Core Stability."},
        {"n": "Adhesive Capsulitis - الكتف المتجمد", "k": "shoulder, stiffness, الكتف, المتجمد", "t": "TENS: 100Hz. Exercises: Wall Climb, Wand Exercises."},
        {"n": "Ankle Sprain - التواء الكاحل", "k": "ankle, sprain, التواء, الكاحل", "t": "HVPC: 120Hz for edema. Exercises: RICE, Balance training."},
        {"n": "ACL Rehab - الرباط الصليبي", "k": "acl, knee, الرباط, الصليبي", "t": "Russian Current: 2500Hz. Restore quad strength."},
        {"n": "Bell's Palsy - شلل الوجه", "k": "face, bell, شلل, الوجه", "t": "EMS for facial muscles. Exercises: Mime Therapy."},
        {"n": "Stroke Rehab - الجلطة الدماغية", "k": "stroke, paralysis, الجلطة", "t": "FES for Foot Drop. Neuroplasticity focus."},
        {"n": "Tennis Elbow - التهاب الكوع", "k": "elbow, tennis, التهاب, الكوع", "t": "TENS 100Hz. Pulsed US. Eccentric exercises."}
    ]
    try:
        db.create_all()
        Protocol.query.delete()
        for i in data:
            db.session.add(Protocol(disease_name=i['n'], keywords=i['k'], protocol_text=i['t']))
        db.session.commit()
        return "✅ Done! Data Imported."
    except Exception as e: return str(e)

@app.route('/admin')
@admin_required
def admin_dashboard():
    return render_template('admin.html', protocols=Protocol.query.all())

@app.route('/admin/add', methods=['GET', 'POST'])
@admin_required
def add_protocol():
    if request.method == 'POST':
        p = Protocol(disease_name=request.form['disease_name'], keywords=request.form['keywords'],
                    protocol_text=request.form['protocol_text'], electrode_image_url=request.form['image_url'])
        db.session.add(p); db.session.commit()
        return redirect(url_for('admin_dashboard'))
    return render_template('add_protocol.html')

@app.route('/make-me-admin')
@login_required
def make_me_admin():
    current_user.is_admin = True
    db.session.commit()
    return "أنت الآن مدير!"

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
        db.session.add(User(email=request.form['email'], password=pw))
        db.session.commit(); return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
def logout():
    logout_user(); return redirect(url_for('login'))

if __name__ == '__main__':
    with app.app_context(): db.create_all()
    app.run(debug=True)
