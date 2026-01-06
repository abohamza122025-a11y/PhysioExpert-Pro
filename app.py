import os
from functools import wraps
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'physio_expert_final_2026')

# --- إعداد قاعدة البيانات ---
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
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    subscription_end = db.Column(db.DateTime, nullable=True)

class Protocol(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    disease_name = db.Column(db.String(200), nullable=False) # اسم المرض
    keywords = db.Column(db.String(500)) # كلمات دلالية للبحث
    description = db.Column(db.Text) # وصف الحالة
    
    # العلاج الكهربي
    estim_type = db.Column(db.String(200)) # نوع التيار
    estim_params = db.Column(db.Text) # الباراميترز
    estim_role = db.Column(db.Text) # الدور العلاجي
    
    # الموجات فوق الصوتية
    us_type = db.Column(db.String(200)) # نوع الموجات
    us_params = db.Column(db.Text) # الباراميترز
    us_role = db.Column(db.Text) # الدور العلاجي
    
    # التمارين العلاجية
    exercises_list = db.Column(db.Text) # قائمة التمارين
    exercises_role = db.Column(db.Text) # دور التمارين (جديد)
    
    source_ref = db.Column(db.String(300)) # المصدر الطبي (جديد)
    electrode_image = db.Column(db.String(500)) 

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

# --- البيانات الطبية الاحترافية (شاملة) ---
def get_full_medical_data():
    return [
        # --- العظام (Orthopedics) ---
        {
            "n": "Adhesive Capsulitis (Frozen Shoulder) - Stage 2",
            "k": "frozen shoulder, كتف, تيبس, adhesive",
            "d": "Pain and significant stiffness. Synovitis and capsular fibrosis.",
            "et": "TENS / IFC",
            "ep": "Freq: 100Hz (Sensory) for 20 min. Intensity: Comfortable tingling.",
            "er": "Pain modulation to allow manual therapy.",
            "ut": "Continuous Ultrasound",
            "up": "Freq: 1MHz (Deep). Intensity: 1.5 w/cm2. Time: 5-8 min.",
            "ur": "Deep heating to increase extensibility of the inferior capsule.",
            "ex": "Pendulum, Wand exercises (Flex/Abd), Wall climbing, Posterior capsule stretch.",
            "ex_r": "Increase ROM and prevent further adhesion.",
            "src": "Kisner & Colby, Therapeutic Exercise, 7th Ed.",
            "img": "shoulder.jpg"
        },
        {
            "n": "Knee Osteoarthritis (Chronic)",
            "k": "knee, oa, خشونة, ركبة, arthritis",
            "d": "Degeneration of articular cartilage, osteophytes formation.",
            "et": "NMES (Russian Current)",
            "ep": "Carrier: 2500Hz, Burst: 50Hz. Duty Cycle: 10/50. Ramp: 2s.",
            "er": "Strengthening Quadriceps (VMO) to offload the joint.",
            "ut": "Continuous Ultrasound",
            "up": "1 MHz, 1.0-1.2 w/cm2 around joint margins.",
            "ur": "Pain relief and improving periarticular circulation.",
            "ex": "Quad setting, SLR, Mini Squats, Hamstring stretching.",
            "ex_r": "Improve stability and reduce joint loading.",
            "src": "O'Sullivan, Physical Rehabilitation.",
            "img": "knee.jpg"
        },
        {
            "n": "Lumbar Disc Herniation (Sciatica)",
            "k": "disc, sciatica, back pain, انزلاق غضروفي",
            "d": "Compression of nerve root by nucleus pulposus.",
            "et": "TENS (Burst Mode) or IFC",
            "ep": "Low rate TENS (2-4Hz) for endorphin release. 20-30 min.",
            "er": "Central pain modulation for chronic radicular pain.",
            "ut": "Thermal Ultrasound (Chronic)",
            "up": "1 MHz, 1.5 w/cm2 on paraspinal muscles (Not over spine directly).",
            "ur": "Relieve paraspinal muscle spasm.",
            "ex": "McKenzie Extension Protocol, Nerve Gliding (Flossing), Core stability.",
            "ex_r": "Centralize symptoms and stabilize lumbar spine.",
            "src": "McKenzie Method Guidelines.",
            "img": "back.jpg"
        },
        
        # --- الإصابات الرياضية (Sports Injuries) ---
        {
            "n": "Lateral Ankle Sprain (Acute Phase)",
            "k": "ankle, sprain, ligament, التواء, كاحل",
            "d": "Inversion injury affecting ATFL ligament. Edema present.",
            "et": "High Voltage Pulsed Current (HVPC)",
            "ep": "Polarity: Negative (Edema). Freq: 100-120Hz. Voltage: 10% below motor.",
            "er": "Curb formation of edema and pain control.",
            "ut": "Pulsed Ultrasound (Non-thermal)",
            "up": "3 MHz, 0.5 w/cm2, Duty Cycle: 20%.",
            "ur": "Accelerate tissue healing via acoustic streaming.",
            "ex": "Isometrics (all directions), Ankle pumps, Towel curl.",
            "ex_r": "Maintain muscle function without stressing the ligament.",
            "src": "Brukner & Khan, Clinical Sports Medicine.",
            "img": "ankle.jpg"
        },
        {
            "n": "ACL Reconstruction (Post-Op Weeks 2-4)",
            "k": "acl, knee, rabat saliby, رباط صليبي",
            "d": "Post-surgical rehab after Anterior Cruciate Ligament graft.",
            "et": "NMES (Biphasic)",
            "ep": "Freq: 50-75Hz. Pulse Width: 200-300us. On/Off: 10/30.",
            "er": "Re-educate Quadriceps and prevent atrophy.",
            "ut": "Not applied over hardware/screws.",
            "up": "Contraindicated over metal implants directly.",
            "ur": "None.",
            "ex": "Patellar mobilization, Heel slides (ROM 0-90), Weight shifting.",
            "ex_r": "Regain full extension and gradual flexion.",
            "src": "MOON ACL Rehab Protocol.",
            "img": "knee_op.jpg"
        },

        # --- الأعصاب (Neurology) ---
        {
            "n": "Hemiplegia (Stroke) - Flaccid Stage",
            "k": "stroke, cva, hemiplegia, جلطة, شلل نصفي",
            "d": "Loss of muscle tone and voluntary movement on one side.",
            "et": "FES (Functional Electrical Stimulation)",
            "ep": "Freq: 25-35Hz (to avoid fatigue). Ramp up: 2-3s. Function-based.",
            "er": "Facilitate muscle contraction (e.g., Wrist extensors, Dorsiflexors).",
            "ut": "None.",
            "up": "None.",
            "ur": "None.",
            "ex": "Passive ROM, Weight bearing on affected side, Bridging.",
            "ex_r": "Maintain joint integrity and sensory input.",
            "src": "Carr & Shepherd, Neurological Rehabilitation.",
            "img": "stroke.jpg"
        },
        {
            "n": "Bell's Palsy",
            "k": "face, facial, seventh nerve, عصب سابع",
            "d": "Unilateral facial paralysis. LMN lesion.",
            "et": "Interrupted Direct Current (IDC)",
            "ep": "Pulse duration: 100-300ms (for denervated muscle). Point stimulation.",
            "er": "Maintain muscle contractility until nerve regeneration.",
            "ut": "None.",
            "up": "None.",
            "ur": "None.",
            "ex": "Manual massage, Kabat exercises, Mirror biofeedback.",
            "ex_r": "Retrain facial expressions and prevent synkinesis.",
            "src": "Tidy's Physiotherapy.",
            "img": "face.jpg"
        },

        # --- الأطفال (Pediatrics) ---
        {
            "n": "Cerebral Palsy (Spastic Diplegia)",
            "k": "cp, child, spastic, شلل دماغي, اطفال",
            "d": "Increased tone in lower limbs, scissoring gait.",
            "et": "NMES (Antagonist muscles)",
            "ep": "Stimulate Tibialis Anterior to inhibit Gastrocnemius (Reciprocal Inhibition).",
            "er": "Reduce spasticity and improve gait pattern.",
            "ut": "None.",
            "up": "None.",
            "ur": "None.",
            "ex": "Stretching (Adductors/Calf), Bobath ball exercises, Gait training.",
            "ex_r": "Normalize tone and facilitate milestones.",
            "src": "Tecklin, Pediatric Physical Therapy.",
            "img": "cp_child.jpg"
        },
        {
            "n": "Erb's Palsy",
            "k": "erbs, brachial plexus, ملخ الولادة, اطفال",
            "d": "Injury to upper brachial plexus (C5-C6) during birth.",
            "et": "Electrical Stimulation (IDC/Galvanic)",
            "ep": "Long duration pulse for deltoid/biceps if denervated.",
            "er": "Maintain muscle bulk.",
            "ut": "None.",
            "up": "None.",
            "ur": "None.",
            "ex": "Passive ROM (prevent contracture), Sensory stimulation.",
            "ex_r": "Maintain shoulder mobility.",
            "src": "Campbell's Physical Therapy for Children.",
            "img": "erbs.jpg"
        },

        # --- نساء وتوليد (Women's Health) ---
        {
            "n": "Diastasis Recti (Post-Natal)",
            "k": "diastasis, pregnancy, abdomen, انفصال عضلات البطن",
            "d": "Separation of rectus abdominis muscles after pregnancy.",
            "et": "NMES (Rectus Abdominis)",
            "ep": "Freq: 35-50Hz. Width: 200us. With voluntary contraction.",
            "er": "Re-educate abdominal muscles.",
            "ut": "None.",
            "up": "None.",
            "ur": "None.",
            "ex": "Pelvic tilt, Heel slides, Head lift (with support). Avoid sit-ups.",
            "ex_r": "Close the separation and strengthen core.",
            "src": "ACOG Guidelines for Postpartum Exercise.",
            "img": "abs.jpg"
        },
        {
            "n": "Chronic Pelvic Inflammatory Disease (PID)",
            "k": "pid, pelvic pain, نساء, التهاب حوض",
            "d": "Chronic pain due to adhesions/inflammation.",
            "et": "Shortwave Diathermy (SWD)",
            "ep": "Continuous mode (Thermal). 20 min.",
            "er": "Deep heating to resolve inflammation and increase blood flow.",
            "ut": "Continuous Ultrasound (External)",
            "up": "1 MHz, 1.5 w/cm2 over lower abdomen.",
            "ur": "Reduce pain and adhesions.",
            "ex": "Relaxation exercises, Pelvic floor awareness.",
            "ex_r": "Reduce pelvic tension.",
            "src": "Electrotherapy Evidence-Based Practice.",
            "img": "pelvic.jpg"
        }
    ]

# --- المسارات (Routes) ---

@app.route('/', methods=['GET', 'POST'])
@login_required
def home():
    now = datetime.utcnow()
    # منطق الاشتراك
    is_active = True # للتسهيل عليك حالياً، يمكنك تفعيل منطق الأيام لاحقاً
    
    result = None
    if request.method == 'POST':
        search_query = request.form.get('disease')
        if search_query:
            term = f"%{search_query}%"
            # تم تعديل all() إلى first() ليتوافق مع صفحة العرض
            result = Protocol.query.filter(
                (Protocol.disease_name.ilike(term)) | 
                (Protocol.keywords.ilike(term))
            ).first() 
    
    # تم تعديل results إلى result (مفرد)
    return render_template('index.html', result=result, user=current_user)

@app.route('/admin')
@admin_required
def admin_dashboard():
    protocols = Protocol.query.all()
    return render_template('admin.html', protocols=protocols)

# --- مسار التثبيت الشامل (الحل السحري) ---
@app.route('/setup-system')
def setup_system():
    try:
        # 1. تنظيف قاعدة البيانات تماماً (Reset)
        db.drop_all()
        db.create_all()
        
        # 2. إنشاء حساب الأدمن (أوتوماتيكياً)
        # البريد: admin@physio.com
        # كلمة السر: admin123
        admin_email = "admin@physio.com"
        admin_pass = "admin123"
        hashed_pw = generate_password_hash(admin_pass, method='pbkdf2:sha256')
        
        new_admin = User(email=admin_email, password=hashed_pw, is_admin=True)
        db.session.add(new_admin)
        
        # 3. إدخال البيانات الطبية الشاملة
        data = get_full_medical_data()
        count = 0
        for i in data:
            p = Protocol(
                disease_name=i['n'],
                keywords=i['k'],
                description=i['d'],
                estim_type=i['et'],
                estim_params=i['ep'],
                estim_role=i['er'],
                us_type=i['ut'],
                us_params=i['up'],
                us_role=i['ur'],
                exercises_list=i['ex'],
                exercises_role=i.get('ex_r', ''), # جديد
                source_ref=i.get('src', ''),      # جديد
                electrode_image=i['img']
            )
            db.session.add(p)
            count += 1
            
        db.session.commit()
        
        html_response = f"""
        <div style="text-align:center; font-family:sans-serif; padding:50px;">
            <h1 style="color:green;">✅ System Setup Complete!</h1>
            <p>1. Database reset and tables created.</p>
            <p>2. <strong>{count}</strong> Professional Medical Protocols imported.</p>
            <p>3. Admin Account Created:</p>
            <div style="background:#f0f0f0; padding:20px; display:inline-block; border-radius:10px;">
                <p><strong>Email:</strong> {admin_email}</p>
                <p><strong>Password:</strong> {admin_pass}</p>
            </div>
            <br><br>
            <a href="/login" style="background:blue; color:white; padding:10px 20px; text-decoration:none; border-radius:5px;">Go to Login</a>
        </div>
        """
        return html_response
        
    except Exception as e:
        return f"<h1>Error during setup: {str(e)}</h1>"

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

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        try:
            hashed_pw = generate_password_hash(request.form['password'], method='pbkdf2:sha256')
            new_user = User(email=request.form['email'], password=hashed_pw)
            db.session.add(new_user)
            db.session.commit()
            return redirect(url_for('login'))
        except:
            flash('Email already exists', 'danger')
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
