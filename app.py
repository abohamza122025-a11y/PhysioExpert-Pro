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
        result = Protocol.query.filter((Protocol.disease_name.ilike(search_term)) | (Protocol.keywords.ilike(search_term))).first()
    return render_template('index.html', result=result, user=current_user)

@app.route('/import-data')
@login_required
def import_data():
    full_data = [
        {"n": "Rotator Cuff Repair (Post-Op)", "k": "shoulder, cuff, قطع وتر الكتف", "t": "TENS: 100Hz. Phase 1: PROM only. Phase 2: AAROM. Phase 3: Strengthening."},
        {"n": "Total Hip Arthroplasty (Post-Op THA)", "k": "hip, tha, surgery, مفصل الفخذ", "t": "TENS for pain. Exercises: Ankle Pumps, Glute Squeeze, Heel Slides. Avoid crossing midline."},
        {"n": "Total Knee Arthroplasty (Post-Op TKA)", "k": "knee, tka, surgery, مفصل الركبة", "t": "NMES for Quads: 50Hz. Phase 1: Ankle pumps, Quad sets, Heel slides."},
        {"n": "Knee Osteoarthritis", "k": "knee pain, oa, stiffness, خشونة الركبة", "t": "NMES: 50Hz. Strengthening Quads. Exercises: Quad Sets, SLR, Mini Squats."},
        {"n": "Lumbar Disc Herniation (Sciatica)", "k": "back, sciatica, disc, ديسك, عرق النسا", "t": "IFC Carrier: 4000Hz. Paravertebral electrodes. Exercises: McKenzie Extension, Core Stability."},
        {"n": "Adhesive Capsulitis (Frozen Shoulder)", "k": "stiffness, shoulder, الكتف المتجمد", "t": "TENS: 100-150 Hz. US 1 MHz. Exercises: Wall Climb, Wand Exercises, Pendulums."},
        {"n": "Lateral Ankle Sprain", "k": "ankle, sprain, swelling, التواء الكاحل", "t": "HVPC/IFC: 120 Hz. Negative polarity for edema. Exercises: RICE, Balance."},
        {"n": "Meniscus Tear", "k": "knee locking, clicking, cartilage, غضروف الركبة", "t": "NMES for Quad strength. TENS for joint line pain. Exercises: Bike, Balance Training."},
        {"n": "ACL Reconstruction Rehab", "k": "acl, knee ligament, surgery, الرباط الصليبي", "t": "NMES (Russian Current) 2500Hz. Restore quad strength. Month 3: Running drills."},
        {"n": "Hamstring Muscle Strain", "k": "pulled muscle, thigh, مزق العضلة الخلفية", "t": "IFC for pain. US Pulsed 20%. Phase 2: Eccentric loading (Nordic Hamstring Curl)."},
        {"n": "Mechanical Neck Pain", "k": "neck, cervical, stiffness, شد عضلات الرقبة", "t": "TENS (Burst Mode) 2-4 Hz. Exercises: Chin Tucks, Trapezius Stretch."},
        {"n": "Diabetic Peripheral Neuropathy", "k": "diabetes, numbness, pain, التهاب الأعصاب", "t": "TENS 80-100Hz. Exercises: Balance Training, Gait Training, Foot Care."},
        {"n": "Bell's Palsy (Facial Palsy)", "k": "face, palsy, bell, شلل الوجه", "t": "EMS for facial muscles. Maintain muscle bulk. Exercises: Mime Therapy, Kabat Rehab."},
        {"n": "Stroke Rehabilitation (Hemiplegia)", "k": "cva, stroke, paralysis, الجلطة الدماغية", "t": "FES for Foot Drop. Neuroplasticity and functional motor re-learning."},
        {"n": "Lateral Epicondylitis (Tennis Elbow)", "k": "elbow, tennis elbow, التهاب الكوع", "t": "TENS 100 Hz. Pulsed US 3 MHz. Exercises: Eccentric Wrist Extension."},
        {"n": "Parkinson's Disease", "k": "tremor, balance, pd, الشلل الرعاش", "t": "Auditory/Visual Cueing. Exercises: LSVT BIG, Balance & Fall Prevention."},
        {"n": "Stress Urinary Incontinence", "k": "leakage, pelvic floor, سلس البول", "t": "Vaginal/Anal Electrical Stimulation 50Hz. Exercises: Kegel Exercises."},
        {"n": "Labor Pain Management", "k": "birth, delivery, pain, الولادة", "t": "Obstetric TENS: 100Hz. Paravertebral: T10-L1 and S2-S4."},
        {"n": "Diastasis Recti (Post-Partum)", "k": "pregnancy, tummy, انفصال العضلات", "t": "NMES for Rectus Abdominis. Exercises: Core brace, Heel Slides."},
        {"n": "Lymphedema Management", "k": "swelling, lymph, التورم الليمفاوي", "t": "Complex Decongestive Therapy (CDT). Manual Lymph Drainage. Bandaging."},
        {"n": "ESRD & Hemodialysis Rehab", "k": "kidney, dialysis, الغسيل الكلوي", "t": "NMES (Intradialytic) for Quads. Exercises: Intradialytic Cycling."},
        {"n": "Cardiac Rehab (CABG)", "k": "heart surgery, bypass, قلب مفتوح", "t": "TENS (Sternal Pain). Phase 1: Breathing exercises. Walking program."}
    ]
    try:
        db.create_all()
        Protocol.query.delete()
        for item in full_data:
            db.session.add(Protocol(disease_name=item['n'], keywords=item['k'], protocol_text=item['t']))
        db.session.commit()
        return f"<h1>✅ تم استعادة {len(full_data)} بروتوكول بنجاح!</h1>"
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
        return redirect(url_for('admin_dashboard'))
    return render_template('edit_protocol.html', protocol=protocol)

@app.route('/admin/delete/<int:id>')
@admin_required
def delete_protocol(id):
    protocol = Protocol.query.get_or_404(id)
    db.session.delete(protocol)
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

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
