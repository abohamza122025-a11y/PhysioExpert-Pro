import os
from functools import wraps
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, abort
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'physio_expert_final_2026')

# ----------------------------------------
# 1. إعدادات قاعدة البيانات
# ----------------------------------------
db_url = os.environ.get('DATABASE_URL', 'sqlite:///physio.db')
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(); login_manager.init_app(app); login_manager.login_view = 'login'

# ----------------------------------------
# 2. حقن البيانات الثابتة (Email & Disclaimer) في كل الصفحات
# ----------------------------------------
@app.context_processor
def inject_global_vars():
    return dict(
        support_email="physioexpert8@gmail.com",
        disclaimer="Disclaimer: This tool is for educational purposes only. Always consult a qualified specialist before applying treatments."
    )

# ----------------------------------------
# 3. الجداول (Models)
# ----------------------------------------
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # يمكن للادمن تمديد الاشتراك يدوياً بتغيير هذا التاريخ
    subscription_end = db.Column(db.DateTime, nullable=True) 

class Protocol(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    disease_name = db.Column(db.String(200), nullable=False)
    keywords = db.Column(db.String(500))
    description = db.Column(db.Text)
    
    # العلاج الكهربي
    estim_type = db.Column(db.String(200))
    estim_params = db.Column(db.Text)
    estim_role = db.Column(db.Text)
    
    # الموجات الصوتية
    us_type = db.Column(db.String(200))
    us_params = db.Column(db.Text)
    us_role = db.Column(db.Text)
    
    # التمارين
    exercises_list = db.Column(db.Text)
    exercises_role = db.Column(db.Text)
    
    source_ref = db.Column(db.String(300))
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

# ----------------------------------------
# 4. المسارات الأساسية (Routes)
# ----------------------------------------

@app.route('/', methods=['GET', 'POST'])
@login_required
def home():
    # --- منطق التجربة المجانية (30 يوم) ---
    if not current_user.is_admin: # الأدمن لا تنتهي فترته أبداً
        days_passed = (datetime.utcnow() - current_user.created_at).days
        days_left = 30 - days_passed
        
        # لو انتهت الفترة المجانية، ولم يقم الأدمن بتمديد الاشتراك يدوياً
        has_extended_sub = current_user.subscription_end and current_user.subscription_end > datetime.utcnow()
        
        if days_left <= 0 and not has_extended_sub:
            return redirect(url_for('subscription_expired'))
    else:
        days_left = "Unlimited (Admin)"

    # --- منطق البحث ---
    result = None
    search_query = request.args.get('disease') or request.form.get('disease')
    if search_query:
        term = f"%{search_query}%"
        result = Protocol.query.filter(
            (Protocol.disease_name.ilike(term)) | 
            (Protocol.keywords.ilike(term))
        ).first()
    
    return render_template('index.html', result=result, user=current_user, days_left=days_left)

# --- صفحة انتهاء الاشتراك والدفع ---
@app.route('/subscription')
def subscription_expired():
    return """
    <div style="text-align:center; padding:50px; font-family:sans-serif;">
        <h1 style="color:red;">Trial Ended</h1>
        <p style="font-size:18px;">Your 30-day free trial has expired.</p>
        <p>To continue using Physio Expert Pro, please subscribe.</p>
        <hr style="width:50%; margin:20px auto;">
        
        <h3>Payment Methods:</h3>
        
        <div style="background:#f9f9f9; padding:20px; display:inline-block; border:1px solid #ddd; border-radius:10px;">
            <p><strong>1. PayPal:</strong> <a href="https://www.paypal.com/paypalme/my/profile" target="_blank">Click Here to Pay</a></p>
            <p><strong>2. Vodafone Cash:</strong> <span style="color:green; font-weight:bold;">01040710253</span></p>
        </div>
        
        <p style="margin-top:30px;">After payment, send the receipt to: 
        <a href="mailto:physioexpert8@gmail.com">physioexpert8@gmail.com</a> to activate your account.</p>
        
        <br>
        <a href="/logout" style="background:gray; color:white; padding:10px 20px; text-decoration:none; border-radius:5px;">Logout</a>
    </div>
    """

# ----------------------------------------
# 5. لوحة تحكم الأدمن (الإضافات الجديدة)
# ----------------------------------------

@app.route('/admin')
@admin_required
def admin_dashboard():
    # صفحة تعرض كل الأمراض مع أزرار التحكم
    protocols = Protocol.query.all()
    return render_template('admin.html', protocols=protocols)

# --- إضافة بروتوكول جديد ---
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
            exercises_role=request.form['exercises_role'],
            source_ref=request.form['source_ref'],
            electrode_image=request.form['electrode_image'] # يكتب اسم الملف فقط مثل knee.jpg
        )
        db.session.add(p)
        db.session.commit()
        flash('Protocol Added Successfully!', 'success')
        return redirect(url_for('admin_dashboard'))
    return render_template('add_protocol.html') # يحتاج ملف HTML بسيط فورم

# --- تعديل بروتوكول موجود ---
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
        p.electrode_image = request.form['electrode_image']
        
        db.session.commit()
        flash('Protocol Updated!', 'success')
        return redirect(url_for('admin_dashboard'))
    return render_template('edit_protocol.html', protocol=p)

# --- حذف بروتوكول ---
@app.route('/admin/delete/<int:id>')
@admin_required
def delete_protocol(id):
    p = Protocol.query.get_or_404(id)
    db.session.delete(p)
    db.session.commit()
    flash('Protocol Deleted!', 'warning')
    return redirect(url_for('admin_dashboard'))

# ----------------------------------------
# 6. التوثيق واستعادة كلمة السر
# ----------------------------------------

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

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    # صفحة بسيطة لإرشاد المستخدم
    if request.method == 'POST':
        flash('Please contact support at physioexpert8@gmail.com to reset your password.', 'info')
    
    return """
    <div style="text-align:center; padding:50px; font-family:sans-serif;">
        <h2>Reset Password</h2>
        <p>To ensure security, please contact our support team to reset your password manually.</p>
        <p><strong>Email:</strong> <a href="mailto:physioexpert8@gmail.com">physioexpert8@gmail.com</a></p>
        <br>
        <a href="/login">Back to Login</a>
    </div>
    """

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ----------------------------------------
# 7. التثبيت والبيانات (Code from previous step preserved)
# ----------------------------------------
def get_full_medical_data():
    return [
        {"n": "Adhesive Capsulitis (Frozen Shoulder) - Stage 2", "k": "frozen shoulder, كتف, تيبس, adhesive", "d": "Pain and significant stiffness. Synovitis and capsular fibrosis.", "et": "TENS / IFC", "ep": "Freq: 100Hz (Sensory) for 20 min. Intensity: Comfortable tingling.", "er": "Pain modulation to allow manual therapy.", "ut": "Continuous Ultrasound", "up": "Freq: 1MHz (Deep). Intensity: 1.5 w/cm2. Time: 5-8 min.", "ur": "Deep heating to increase extensibility.", "ex": "Pendulum, Wand exercises, Wall climbing.", "ex_r": "Increase ROM.", "src": "Kisner & Colby", "img": "shoulder.jpg"},
        {"n": "Knee Osteoarthritis (Chronic)", "k": "knee, oa, خشونة, ركبة", "d": "Degeneration of articular cartilage.", "et": "NMES (Russian)", "ep": "Carrier: 2500Hz, Burst: 50Hz. Duty: 10/50.", "er": "Strengthening Quadriceps.", "ut": "Continuous Ultrasound", "up": "1 MHz, 1.0 w/cm2.", "ur": "Pain relief.", "ex": "Quad setting, SLR, Mini Squats.", "ex_r": "Improve stability.", "src": "O'Sullivan", "img": "knee.jpg"},
        {"n": "Lumbar Disc Herniation (Sciatica)", "k": "disc, sciatica, back, انزلاق", "d": "Compression of nerve root.", "et": "TENS (Burst)", "ep": "Low rate (2-4Hz). 20-30 min.", "er": "Central pain modulation.", "ut": "Thermal Ultrasound", "up": "1 MHz, 1.5 w/cm2 paraspinal.", "ur": "Relieve spasm.", "ex": "McKenzie Extension, Nerve Gliding.", "ex_r": "Centralize symptoms.", "src": "McKenzie Method", "img": "back.jpg"},
        {"n": "Lateral Ankle Sprain", "k": "ankle, sprain, التواء", "d": "Inversion injury (ATFL).", "et": "HVPC", "ep": "Negative Polarity. 100-120Hz.", "er": "Edema control.", "ut": "Pulsed Ultrasound", "up": "3 MHz, 0.5 w/cm2, 20%.", "ur": "Tissue healing.", "ex": "Isometrics, Ankle pumps.", "ex_r": "Maintain function.", "src": "Brukner & Khan", "img": "ankle.jpg"},
        {"n": "Hemiplegia (Stroke)", "k": "stroke, cva, جلطة", "d": "Loss of movement on one side.", "et": "FES", "ep": "Freq: 35Hz. Function-based.", "er": "Facilitate dorsiflexion/wrist ext.", "ut": "None", "up": "None", "ur": "None", "ex": "Weight bearing, Bridging.", "ex_r": "Motor relearning.", "src": "Carr & Shepherd", "img": "stroke.jpg"},
        {"n": "Bell's Palsy", "k": "face, facial, عصب سابع", "d": "Facial paralysis.", "et": "IDC", "ep": "Long pulse 100-300ms.", "er": "Maintain muscle property.", "ut": "None", "up": "None", "ur": "None", "ex": "Kabat exercises, Massage.", "ex_r": "Retrain expression.", "src": "Tidy's Physiotherapy", "img": "face.jpg"},
        {"n": "Cerebral Palsy (Spastic)", "k": "cp, child, spastic, شلل دماغي", "d": "Increased tone.", "et": "NMES (Antagonist)", "ep": "Stimulate Tibialis Ant.", "er": "Reciprocal inhibition.", "ut": "None", "up": "None", "ur": "None", "ex": "Stretching, Bobath.", "ex_r": "Normalize tone.", "src": "Tecklin", "img": "cp_child.jpg"},
        {"n": "Erb's Palsy", "k": "erbs, brachial, ملخ", "d": "C5-C6 injury.", "et": "Galvanic", "ep": "Long duration.", "er": "Maintain bulk.", "ut": "None", "up": "None", "ur": "None", "ex": "Passive ROM.", "ex_r": "Prevent contracture.", "src": "Campbell", "img": "erbs.jpg"},
        {"n": "Diastasis Recti", "k": "diastasis, pregnancy, بطن", "d": "Abdominal separation.", "et": "NMES", "ep": "35-50Hz. With contraction.", "er": "Re-educate abs.", "ut": "None", "up": "None", "ur": "None", "ex": "Pelvic tilt, Head lift.", "ex_r": "Core strength.", "src": "ACOG", "img": "abs.jpg"},
        {"n": "Carpal Tunnel Syndrome", "k": "wrist, carpal, نفق رسغي", "d": "Median nerve compression.", "et": "TENS", "ep": "Conventional.", "er": "Pain relief.", "ut": "Pulsed US", "up": "3MHz, 0.8 w/cm2.", "ur": "Reduce inflammation.", "ex": "Tendon gliding.", "ex_r": "Mobility.", "src": "Hand Therapy Guidelines", "img": "wrist.jpg"},
        {"n": "Supraspinatus Tendinitis", "k": "shoulder, rotator, وتر", "d": "Tendon inflammation.", "et": "TENS", "ep": "100Hz.", "er": "Pain control.", "ut": "Pulsed US", "up": "3MHz, 1.0 w/cm2.", "ur": "Healing.", "ex": "Pendulum, Isometric.", "ex_r": "Strength.", "src": "Magee", "img": "shoulder.jpg"},
        {"n": "Tennis Elbow", "k": "elbow, tennis, كوع", "d": "Extensor origin inflammation.", "et": "TENS", "ep": "Conventional.", "er": "Pain.", "ut": "Pulsed US", "up": "1MHz.", "ur": "Repair.", "ex": "Eccentric wrist ext.", "ex_r": "Load management.", "src": "Vicenzino", "img": "elbow.jpg"},
        {"n": "Plantar Fasciitis", "k": "foot, heel, شوكة", "d": "Fascia inflammation.", "et": "HVPC", "ep": "100Hz.", "er": "Pain.", "ut": "Continuous US", "up": "3MHz, 1.5.", "ur": "Stretch.", "ex": "Calf stretch, Ball roll.", "ex_r": "Flexibility.", "src": "JOSPT", "img": "foot.jpg"},
        {"n": "Patellofemoral Pain", "k": "knee, chondromalacia, صابونة", "d": "Anterior knee pain.", "et": "NMES (VMO)", "ep": "50Hz.", "er": "Tracking.", "ut": "None", "up": "None", "ur": "None", "ex": "VMO strength, Hip abd.", "ex_r": "Biomechanics.", "src": "McConnell", "img": "knee.jpg"},
        {"n": "Cervical Spondylosis", "k": "neck, cervical, رقبة", "d": "Disc degeneration.", "et": "TENS", "ep": "80-100Hz.", "er": "Pain.", "ut": "Continuous US", "up": "1.0 w/cm2.", "ur": "Spasm.", "ex": "Chin tucks.", "ex_r": "Posture.", "src": "McKenzie", "img": "neck.jpg"},
        {"n": "Ankle Sprain (Lateral)", "k": "ankle, sprain, كاحل", "d": "Ligament injury.", "et": "IFC", "ep": "80-150Hz.", "er": "Edema control.", "ut": "Pulsed US", "up": "3MHz.", "ur": "Healing.", "ex": "Balance board.", "ex_r": "Proprioception.", "src": "Brukner", "img": "ankle.jpg"}
    ]

@app.route('/setup-system')
def setup_system():
    try:
        db.drop_all(); db.create_all()
        admin_email = "admin@physio.com"; admin_pass = "admin123"
        hashed_pw = generate_password_hash(admin_pass, method='pbkdf2:sha256')
        db.session.add(User(email=admin_email, password=hashed_pw, is_admin=True))
        data = get_full_medical_data()
        count = 0
        for i in data:
            p = Protocol(disease_name=i['n'], keywords=i['k'], description=i['d'], estim_type=i['et'], estim_params=i['ep'], estim_role=i['er'], us_type=i['ut'], us_params=i['up'], us_role=i['ur'], exercises_list=i['ex'], exercises_role=i.get('ex_r', ''), source_ref=i.get('src', ''), electrode_image=i['img'])
            db.session.add(p); count += 1
        db.session.commit()
        return f"<h1>✅ System Updated!</h1><p>{count} Protocols Loaded.</p><a href='/login'>Login Now</a>"
    except Exception as e: return f"Error: {str(e)}"

if __name__ == '__main__':
    with app.app_context(): db.create_all()
    app.run(debug=True)
