import os
from functools import wraps
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash
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

# --- 2. Models ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_confirmed = db.Column(db.Boolean, default=True)
    subscription_end_date = db.Column(db.DateTime, nullable=True)
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

# --- 3. Helpers & Decorators ---
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('غير مصرح لك!', 'danger')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

# --- 4. Routes ---

@app.route('/', methods=['GET', 'POST'])
@login_required
def home():
    now = datetime.utcnow()
    days_elapsed = (now - current_user.created_at).days
    is_trial = days_elapsed < 30
    is_subscribed = current_user.subscription_end_date and current_user.subscription_end_date > now
    if not (is_trial or is_subscribed): return redirect(url_for('subscribe'))
    
    days_left = 30 - days_elapsed if is_trial else (current_user.subscription_end_date - now).days
    result = None
    search_query = request.args.get('disease') or request.form.get('disease')
    if search_query:
        search_term = f"%{search_query}%"
        result = Protocol.query.filter((Protocol.disease_name.ilike(search_term)) | (Protocol.keywords.ilike(search_term))).first()
    return render_template('index.html', result=result, days_left=days_left, user=current_user)

# --- دالة استيراد البيانات القديمة (تستخدم مرة واحدة) ---
@app.route('/import-my-data')
@login_required
def import_data():
    old_data = [
        {"name": "Knee Osteoarthritis", "key": "knee pain, oa, stiffness, خشونة الركبة", "text": "NMES (Strengthening) Target: Quads. Freq: 50Hz. Strengthening Quadriceps to offload joint. Exercises: Quad Sets, SLR, Mini Squats."},
        {"name": "Lumbar Disc Herniation (Sciatica)", "key": "back pain, sciatica, disc, ديسك, عرق النسا", "text": "IFC (Interferential) Carrier: 4000Hz. Paravertebral electrodes. Exercises: McKenzie Extension, Nerve Flossing, Core Stability."},
        {"name": "Adhesive Capsulitis (Frozen Shoulder)", "key": "stiffness, shoulder pain, capsulitis, الكتف المتجمد", "text": "TENS (High Rate) 100-150 Hz. Ultrasound 1 MHz (deep) for extensibility. Exercises: Pendulums, Wall Climb, Wand Exercises."},
        {"name": "Lateral Ankle Sprain", "key": "ankle pain, sprain, swelling, twist, التواء الكاحل", "text": "HVPC / IFC Freq: 120 Hz. Polarity: Negative for edema. Exercises: RICE Protocol, Ankle Pumps, Balance Training."},
        {"name": "ACL Reconstruction Rehab", "key": "acl, knee ligament, surgery, الرباط الصليبي", "text": "NMES (Russian Current) Target: Quads. Restore quad strength and prevent atrophy. Exercises: Patellar mobs, SLR, Closed chain squats."},
        {"name": "Bell's Palsy (Facial Palsy)", "key": "facial paralysis, face droop, bell, weakness, شلل الوجه", "text": "EMS Target: Individual facial muscles. Maintain muscle bulk/prevent atrophy. Mime Therapy, Kabat Rehabilitation."},
        {"name": "Stroke Rehabilitation (Hemiplegia)", "key": "cva, stroke, paralysis, gait, hemiparesis, الجلطة الدماغية", "text": "FES (Functional Electrical Stimulation) Target: Tibialis Anterior. Neuroplasticity and functional motor re-learning."},
        {"name": "Lateral Epicondylitis (Tennis Elbow)", "key": "elbow pain, tennis elbow, التهاب الكوع", "text": "TENS 100 Hz. Pulsed Ultrasound 3 MHz. Exercises: Eccentric Wrist Extension, Extensor Stretch."}
    ]
    try:
        count = 0
        for item in old_data:
            if not Protocol.query.filter_by(disease_name=item['name']).first():
                db.session.add(Protocol(disease_name=item['name'], keywords=item['key'], protocol_text=item['text']))
                count += 1
        db.session.commit()
        return f"<h1>✅ Done! {count} protocols imported.</h1><p><a href='/'>Go to Home</a></p>"
    except Exception as e: return str(e)

@app.route('/admin')
@admin_required
def admin_dashboard():
    protocols = Protocol.query.all()
    return render_template('admin.html', protocols=protocols)

@app.route('/admin/add', methods=['GET', 'POST'])
@admin_required
def add_protocol():
    if request.method == 'POST':
        db.session.add(Protocol(disease_name=request.form['disease_name'], keywords=request.form['keywords'], 
                               protocol_text=request.form['protocol_text'], electrode_image_url=request.form['image_url']))
        db.session.commit()
        return redirect(url_for('admin_dashboard'))
    return render_template('add_protocol.html')

@app.route('/make-me-admin')
@login_required
def make_me_admin():
    current_user.is_admin = True
    db.session.commit()
    return "مبروك! أنت الآن المدير."

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form['email']).first()
        if user and check_password_hash(user.password, request.form['password']):
            login_user(user)
            return redirect(url_for('home'))
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        hashed_pw = generate_password_hash(request.form['password'], method='pbkdf2:sha256')
        db.session.add(User(email=request.form['email'], password=hashed_pw))
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/subscribe')
def subscribe(): return render_template('subscribe.html')

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)
