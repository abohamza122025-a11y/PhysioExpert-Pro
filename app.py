import os
from functools import wraps
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text # <--- ضروري للتعامل مع التعديلات
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
    # بيانات طبية حقيقية ومفصلة
    full_data = [
        {
            "n": "Adhesive Capsulitis (Frozen Shoulder)",
            "k": "frozen shoulder, كتف, تيبس, adhesive",
            "d": "Pain and stiffness in the shoulder capsule. Treatment focuses on regaining ROM.",
            "et": "TENS / IFC",
            "ep": "Frequency: 100Hz (Pain), 4000Hz (IFC). Duration: 20 min.",
            "er": "Pain modulation to allow mobilization.",
            "ut": "Continuous Ultrasound",
            "up": "Frequency: 1MHz/3MHz. Intensity: 1.5 w/cm2 (Deep heat). Time: 5-8 min.",
            "ur": "Deep heating to increase tissue extensibility before stretching.",
            "ex": "Pendulum, Wand exercises, Wall climbing, Posterior capsule stretch.",
            "img": "shoulder.jpg"
        },
        {
            "n": "Lumbar Disc Herniation (Sciatica)",
            "k": "disc, sciatica, back pain, انزلاق غضروفي, عرق النسا",
            "d": "Nucleus pulposus protruding through annulus fibrosus compressing nerve root.",
            "et": "TENS (Burst Mode) / IFC",
            "ep": "Low rate TENS (2-4Hz) for chronic pain. IFC Vector scan.",
            "er": "Pain relief and muscle relaxation.",
            "ut": "Pulsed Ultrasound (if acute) / Thermal (if chronic)",
            "up": "1 MHz, 1.0-1.5 w/cm2 paraspinal muscles.",
            "ur": "Reduce muscle spasm in paraspinal muscles.",
            "ex": "McKenzie Extension, Core stability, Cat-Camel, Nerve gliding.",
            "img": "back.jpg"
        },
        {
            "n": "Knee Osteoarthritis",
            "k": "knee, oa, خشونة, ركبة, arthritis",
            "d": "Degeneration of joint cartilage and underlying bone.",
            "et": "NMES (Russian Current)",
            "ep": "Carrier Freq: 2500Hz. Burst: 50Hz. On/Off: 10/50 sec.",
            "er": "Strengthening Quadriceps muscle (VMO).",
            "ut": "Continuous Ultrasound",
            "up": "1 MHz, 1.2 w/cm2 around joint line.",
            "ur": "Pain relief and improving circulation.",
            "ex": "Straight Leg Raise (SLR), Terminal Knee Extension (TKE), Mini Squats.",
            "img": "knee.jpg"
        },
        {
            "n": "Lateral Epicondylitis (Tennis Elbow)",
            "k": "elbow, tennis, kوع, التهاب",
            "d": "Inflammation of the extensor tendons at the elbow.",
            "et": "TENS / Iontophoresis",
            "ep": "Conventional TENS 100Hz for pain control.",
            "er": "Pain management during activity.",
            "ut": "Pulsed Ultrasound",
            "up": "3 MHz, 0.8 w/cm2, Duty Cycle 20% (Sub-acute).",
            "ur": "Promote healing and collagen alignment.",
            "ex": "Eccentric wrist extension, Grip strengthening, Stretching.",
            "img": "elbow.jpg"
        },
        {
            "n": "Cervical Spondylosis",
            "k": "neck, cervical, رقبة, خشونة الفقرات",
            "d": "Age-related wear and tear affecting spinal disks in the neck.",
            "et": "TENS / IFC",
            "ep": "Frequency: 80-100Hz. Electrodes: Paraspinal cervical.",
            "er": "Relieve neck pain and tension headaches.",
            "ut": "Continuous Ultrasound",
            "up": "3 MHz (superficial), 1.0 w/cm2 on upper trapezius.",
            "ur": "Relax upper trapezius spasm.",
            "ex": "Chin tucks, Neck Isometrics, Scapular retraction.",
            "img": "neck.jpg"
        },
        {
            "n": "Plantar Fasciitis",
            "k": "foot, heel, plantar, شوكة عظمية, قدم",
            "d": "Inflammation of the plantar fascia tissue.",
            "et": "High Voltage Pulsed Current (HVPC)",
            "ep": "Negative polarity if edema present. 100Hz.",
            "er": "Pain relief and edema reduction.",
            "ut": "Continuous Ultrasound",
            "up": "3 MHz or 1 MHz, 1.5 w/cm2 over fascia.",
            "ur": "Deep heat to stretch fascia.",
            "ex": "Calf stretching, Rolling bottle/ball, Towel curl.",
            "img": "foot.jpg"
        },
        {
            "n": "Bell's Palsy",
            "k": "face, facial, seventh nerve, عصب سابع",
            "d": "Sudden weakness in the muscles on one half of the face.",
            "et": "Interrupted Direct Current (IDC)",
            "ep": "Pulse duration: 100-300ms (long duration for denervated muscle).",
            "er": "Maintain muscle properties until nerve regenerates.",
            "ut": "Not commonly used.",
            "up": "None.",
            "ur": "None.",
            "ex": "Facial expressions (smile, frown, close eyes), Kabat rehab.",
            "img": "face.jpg"
        },
        {
            "n": "Carpal Tunnel Syndrome",
            "k": "wrist, hand, carpal, نفق رسغي",
            "d": "Compression of the median nerve as it travels through the wrist.",
            "et": "TENS",
            "ep": "Conventional TENS over wrist area.",
            "er": "Symptom management.",
            "ut": "Pulsed Ultrasound",
            "up": "3 MHz, 0.5-0.8 w/cm2, 20% duty cycle.",
            "ur": "Reduce inflammation inside the tunnel.",
            "ex": "Tendon gliding, Median nerve gliding, Wrist splinting.",
            "img": "wrist.jpg"
        },
        {
            "n": "Ankle Sprain (Lateral)",
            "k": "ankle, sprain, ligament, التواء, كاحل",
            "d": "Injury to the lateral ligaments (ATFL) of the ankle.",
            "et": "IFC / High Voltage",
            "ep": "80-150Hz for acute pain and edema.",
            "er": "Edema control and pain relief.",
            "ut": "Pulsed Ultrasound",
            "up": "3 MHz, 0.5 w/cm2, 20% (Acute phase).",
            "ur": "Accelerate tissue healing.",
            "ex": "RICE protocol, Ankle pumps, Balance board, Calf raises.",
            "img": "ankle.jpg"
        },
        {
            "n": "Supraspinatus Tendinitis",
            "k": "shoulder, rotator cuff, tendinitis, وتر الكتف",
            "d": "Inflammation of the supraspinatus tendon.",
            "et": "TENS / IFC",
            "ep": "100Hz bipolar.",
            "er": "Pain control for therapy.",
            "ut": "Pulsed Ultrasound",
            "up": "3 MHz (if superficial) or 1 MHz, 1.0 w/cm2 pulsed.",
            "ur": "Reduce tendon inflammation.",
            "ex": "Pendulum, Isometric abduction, Scapular stabilization.",
            "img": "shoulder.jpg"
        }
    ]

    count = 0
    for i in full_data:
        # البحث عن البروتوكول بالاسم، إذا وجد نقوم بتحديثه، وإذا لم يوجد ننشئه
        p = Protocol.query.filter_by(disease_name=i['n']).first()
        if not p:
            p = Protocol()
            db.session.add(p)
            count += 1
        
        # تحديث البيانات (سواء كان جديد أو قديم) لضمان ملء الخانات الفارغة
        p.disease_name = i['n']
        p.keywords = i['k']
        p.description = i['d']
        p.estim_type = i['et']
        p.estim_params = i['ep']
        p.estim_role = i['er']
        p.us_type = i['ut']
        p.us_params = i['up']
        p.us_role = i['ur']
        p.exercises_list = i['ex']
        p.electrode_image = i['img']

    db.session.commit()
    return f"✅ Successfully Updated/Imported {count} New Protocols, and refreshed existing ones!"

# --- مسار الإصلاح الشامل (المعدل) ---
@app.route('/fix-db')
def fix_db_column():
    try:
        with db.engine.connect() as conn:
            # 1. إصلاح جدول المستخدمين (إضافة خانة الاشتراك)
            conn.execute(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS subscription_end TIMESTAMP'))
            
            # 2. إصلاح جدول البروتوكولات (إضافة الخانات الجديدة عشان ميعملش Error 500)
            columns_to_add = [
                "description TEXT",
                "estim_type VARCHAR(200)",
                "estim_params TEXT",
                "estim_role TEXT",
                "us_type VARCHAR(200)",
                "us_params TEXT",
                "us_role TEXT",
                "exercises_list TEXT",
                "electrode_image VARCHAR(500)"
            ]
            
            for col in columns_to_add:
                conn.execute(text(f'ALTER TABLE protocol ADD COLUMN IF NOT EXISTS {col}'))

            conn.commit()
        return "<h1>✅ Database Fully Fixed (Users + Protocols)!</h1><p>الان يمكنك استخدام الموقع بأمان.</p><a href='/'>Go Home</a>"
    except Exception as e:
        return f"<h1>Error: {str(e)}</h1>"

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

