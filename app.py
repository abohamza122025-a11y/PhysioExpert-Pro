import os
import base64
import pandas as pd  # مكتبة معالجة الإكسيل
from functools import wraps
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename  # لتأمين أسماء الصور المرفوعة
# ==========================================
# 1. إعدادات الذكاء الاصطناعي (Gemini AI)
# ==========================================
# ==========================================
# 1. إعدادات الذكاء الاصطناعي (Gemini AI)
# ==========================================
import json
import google.generativeai as genai

# المفتاح الخاص بك (تم استخراجه من ملفاتك)
GEMINI_API_KEY = "AIzaSyC15GUq00krv1BgDxRo_Xdgz1nA3aUNbQk"
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')
# ==========================================
# ==========================================
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'physio_expert_final_2026')
@app.template_filter('split_list')
def split_list_filter(s):
    if not s: return []
    return [item.strip() for item in s.split(',')]
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
    category = db.Column(db.String(100), default="General") # أضفنا التصنيف
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
    ex_frequency = db.Column(db.String(200)) # حقول إضافية للجرعات والأنيميشن
    ex_intensity = db.Column(db.String(200))
    ex_progression = db.Column(db.Text)
    evidence_level = db.Column(db.String(50), default="Grade A")
    source_ref = db.Column(db.String(300))
    electrode_image = db.Column(db.Text)  # يدعم المسار أو التشفير

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
# --- دالة جلب البروتوكول العلاجي من جيميني ---
# --- دالة جلب البروتوكول العلاجي من جيميني ---
def get_ai_protocol(disease_search):
    try:
        # تجهيز الأمر (Prompt) ليناسب تصميم موقعك
        prompt = f"""
        Act as an expert Physiotherapist. Create a detailed treatment protocol for "{disease_search}".
        
        CRITICAL: Return the output specifically as a valid JSON object ONLY. 
        Do not add Markdown formatting (no ```json).
        
        Use exactly these keys to match my website template:
        {{
            "disease_name": "{disease_search} (AI Protocol)",
            "keywords": "3 keywords separated by commas",
            "description": "Clinical presentation and definition (approx 40 words)",
            "estim_type": "Type of current (e.g. TENS, IFC)",
            "estim_params": "Frequency, Pulse Width, Duration",
            "estim_role": "Goal of electrotherapy",
            "electrode_image": "default_ai.jpg", 
            "us_type": "Continuous or Pulsed",
            "us_params": "Frequency, Intensity, Duty Cycle",
            "us_role": "Goal of ultrasound",
            "exercises_list": "Exercise 1, Exercise 2, Exercise 3, Exercise 4",
            "exercises_role": "Goal of exercises",
            "source_ref": "Generated by Gemini AI based on clinical guidelines"
        }}
        
        If "{disease_search}" is not a medical condition, return JSON with key "error".
        """
        
        response = model.generate_content(prompt)
        text_response = response.text.strip()
        
        # تنظيف الرد
        if text_response.startswith("```json"):
            text_response = text_response[7:]
        if text_response.endswith("```"):
            text_response = text_response[:-3]

        data = json.loads(text_response)
        
        if "error" in data:
            return None
            
        return data

    except Exception as e:
        print(f"⚠️ AI Service Error: {e}")
        return None
# ---------------------------------------------
# --- 3. المسارات (Routes) ---

@app.route('/', methods=['GET', 'POST'])
@login_required
def home():
    # 1. كود الاشتراك (زي ما هو)
    if not current_user.is_admin:
        days_passed = (datetime.utcnow() - current_user.created_at).days
        days_left = 30 - days_passed
        has_extended_sub = current_user.subscription_end and current_user.subscription_end > datetime.utcnow()
        if days_left <= 0 and not has_extended_sub:
            return redirect(url_for('subscription_expired'))
    else:
        days_left = "Unlimited (Admin)"

    # 2. بداية البحث (لاحظ المسافات هنا اتظبطت)
    result = None
    search_query = request.args.get('disease') or request.form.get('disease')
    
    if search_query:
        # أ: البحث في الداتا بيز المحلية
        term = f"%{search_query}%"
        result = Protocol.query.filter(
            (Protocol.disease_name.ilike(term)) | 
            (Protocol.keywords.ilike(term))
        ).first()

        # ب: الإضافة الجديدة (لو ملقاش نتيجة، اسأل AI)
        if not result:
            result = get_ai_protocol(search_query)
    
    return render_template('index.html', result=result, user=current_user, days_left=days_left)
@app.route('/subscription')
def subscription_expired():
    return render_template('subscribe.html') 

@app.route('/admin')
@admin_required
def admin_dashboard():
    protocols = Protocol.query.all()
    users = User.query.all()  # أضف هذا السطر
    return render_template('admin.html', protocols=protocols, users=users) # أضف users هنا

# أضف هذه الدالة كاملةً تحتها
@app.route('/admin/reset-user-password/<email>/<new_password>')
@admin_required 
def manual_reset(email, new_password):
    user = User.query.filter_by(email=email).first()
    if user:
        user.password = generate_password_hash(new_password, method='pbkdf2:sha256')
        db.session.commit()
        flash(f'Success: Password for {email} updated!', 'success')
        return redirect(url_for('admin_dashboard'))
    return "User not found", 404

# --- إضافة بروتوكول يدوي (يدعم رفع صورة من الكمبيوتر) ---
@app.route('/admin/add-manual', methods=['POST'])
@admin_required
def add_manual():
    image_data = ""
    # رفع الصورة وتحويلها لتشفير Base64 لضمان عدم ضياعها
    if 'electrode_image' in request.files:
        file = request.files['electrode_image']
        if file.filename != '':
            # قراءة ملف الصورة وتحويله لنص مشفر
            encoded_string = base64.b64encode(file.read()).decode('utf-8')
            image_data = f"data:image/jpeg;base64,{encoded_string}"
        
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
        ex_progression=request.form.get('ex_progression'),
        evidence_level=request.form.get('evidence_level', 'Grade A'),
        source_ref=request.form['source_ref'],
        electrode_image=image_data  # تخزين النص المشفر في قاعدة البيانات
    )
    db.session.add(p)
    db.session.commit()
    flash('Manual Protocol Added with Secure Image!', 'success')
    return redirect(url_for('admin_dashboard'))
# --- مسار تعديل بروتوكول موجود ---
@app.route('/admin/edit/<int:id>', methods=['GET', 'POST'])
@admin_required
def edit_protocol(id):
    p = Protocol.query.get_or_404(id)
    if request.method == 'POST':
        # استخدام .get يتجنب خطأ 400 تماماً
        p.disease_name = request.form.get('disease_name')
        p.category = request.form.get('category')
        p.description = request.form.get('description')
        p.keywords = request.form.get('keywords')
        p.estim_type = request.form.get('estim_type')
        p.estim_params = request.form.get('estim_params')
        p.estim_role = request.form.get('estim_role')
        p.us_type = request.form.get('us_type')
        p.us_params = request.form.get('us_params')
        p.us_role = request.form.get('us_role')
        p.exercises_list = request.form.get('exercises_list')
        p.exercises_role = request.form.get('exercises_role')
        p.ex_frequency = request.form.get('ex_frequency')
        p.source_ref = request.form.get('source_ref')

        if 'electrode_image' in request.files:
            file = request.files['electrode_image']
            if file and file.filename != '':
                encoded_string = base64.b64encode(file.read()).decode('utf-8')
                p.electrode_image = f"data:image/jpeg;base64,{encoded_string}"

        db.session.commit()
        flash('Protocol Updated Successfully!', 'success')
        return redirect(url_for('admin_dashboard'))
    
    return render_template('edit_protocol.html', protocol=p)
@app.route('/admin/import-excel', methods=['POST'])
@admin_required
def import_excel():
    if 'excel_file' not in request.files:
        flash('No file selected', 'danger')
        return redirect(url_for('admin_dashboard'))
    
    file = request.files['excel_file']
    if file.filename == '':
        flash('No selected file', 'warning')
        return redirect(url_for('admin_dashboard'))

    try:
        df = pd.read_excel(file)
        # تنظيف أسماء الأعمدة من أي مسافات زائدة
        df.columns = df.columns.str.strip()
        
        for _, row in df.iterrows():
            # استخدام .get هنا يمنع الخطأ تماماً لو العمود مش موجود في الإكسيل
            new_p = Protocol(
                disease_name=str(row.get('disease_name', 'Unknown Condition')),
                category=str(row.get('category', 'General')),
                keywords=str(row.get('keywords', '')),
                description=str(row.get('description', '')),
                estim_type=str(row.get('estim_type', '')),
                estim_params=str(row.get('estim_params', '')),
                estim_role=str(row.get('estim_role', '')),
                us_type=str(row.get('us_type', '')),
                us_params=str(row.get('us_params', '')),
                us_role=str(row.get('us_role', '')),
                exercises_list=str(row.get('exercises_list', '')),
                exercises_role=str(row.get('exercises_role', '')),
                ex_frequency=str(row.get('ex_frequency', '3 times/week')),
                ex_intensity=str(row.get('ex_intensity', 'Moderate')),
                evidence_level=str(row.get('evidence_level', 'Grade A')),
                source_ref=str(row.get('source_ref', 'N/A'))
                # حذفنا is_protected لأنه غير موجود في الـ Model الخاص بك
            )
            db.session.add(new_p)
            
        db.session.commit()
        flash(f'Successfully imported {len(df)} protocols!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Excel Error: {str(e)}', 'danger')
        
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

@app.route('/forgot-password')
def forgot_password():
    return render_template('forgot_password.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        try:
            pw = generate_password_hash(request.form['password'], method='pbkdf2:sha256')
            db.session.add(User(email=request.form['email'], password=pw))
            db.session.commit()
            return redirect(url_for('login'))
        except: flash('Email already exists', 'danger')
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout(): logout_user(); return redirect(url_for('login'))

# --- التثبيت (الكامل مع البيانات) ---
@app.route('/setup-sys-secure-hmna12-4-2026')
def setup_system():
    try:
        # مسح القديم وإنشاء الجديد
        db.drop_all()
        db.create_all()
        
        # إنشاء الأدمن
        admin_email = "admin@physio.com"
        admin_pass = "AboHamzaPhysioadmin2026"
        hashed_pw = generate_password_hash(admin_pass, method='pbkdf2:sha256')
        db.session.add(User(email=admin_email, password=hashed_pw, is_admin=True))
        
        # قائمة الأمراض الكاملة
        protocols_data = [
            {"n": "Adhesive Capsulitis", "c": "Orthopedics", "k": "frozen shoulder, stiff", "d": "Stiffness and pain in the shoulder joint.", "et": "TENS", "ep": "100Hz, continuous", "er": "Pain relief", "ut": "Ultrasound", "up": "1.5 W/cm2, 1MHz", "ur": "Deep heating", "ex": "Pendulum, Wand exercises", "ex_r": "Increase ROM", "ef": "Daily", "ei": "Pain-free", "ev": "Grade A", "src": "Kisner & Colby", "img": "/static/uploads/shoulder.jpg"},
            {"n": "Knee Osteoarthritis", "c": "Orthopedics", "k": "knee oa, pain, joint", "d": "Degenerative joint disease affecting the knee.", "et": "IFC", "ep": "Beat freq 80-150Hz", "er": "Pain modulation", "ut": "None", "up": "None", "ur": "None", "ex": "Quads setting, SLR", "ex_r": "Strengthening", "ef": "3x/week", "ei": "Moderate", "ev": "Grade A", "src": "Dutton", "img": "/static/uploads/knee.jpg"},
            {"n": "Low Back Pain (Mechanical)", "c": "Orthopedics", "k": "lbp, back, lumbar", "d": "Pain in the lumbar region not due to radiculopathy.", "et": "TENS", "ep": "80-100Hz", "er": "Gate control", "ut": "IR Lamp", "up": "20 mins", "ur": "Relaxation", "ex": "McKenzie, Pelvic tilt", "ex_r": "Core stability", "ef": "Daily", "ei": "Controlled", "ev": "Grade A", "src": "Magee", "img": "/static/uploads/back.jpg"},
            {"n": "Carpal Tunnel Syndrome", "c": "Orthopedics", "k": "cts, wrist, hand", "d": "Median nerve compression at the wrist.", "et": "Ultrasound", "ep": "0.8 W/cm2, pulsed 20%", "er": "Anti-inflammatory", "ut": "US", "up": "See above", "ur": "Healing", "ex": "Tendon gliding", "ex_r": "Mobility", "ef": "Daily", "ei": "Low", "ev": "Grade B", "src": "Brotzman", "img": "/static/uploads/wrist.jpg"},
            {"n": "Lateral Epicondylitis", "c": "Orthopedics", "k": "tennis elbow", "d": "Inflammation of the extensor origin.", "et": "Laser", "ep": "4 J/cm2", "er": "Tissue repair", "ut": "Phonophoresis", "up": "1.0 W/cm2", "ur": "Drug delivery", "ex": "Eccentric wrist ext", "ex_r": "Remodeling", "ef": "3x/week", "ei": "Intense", "ev": "Grade A", "src": "Kisner", "img": "/static/uploads/elbow.jpg"},
            {"n": "Stroke (Hemiplegia)", "c": "Neurology", "k": "cva, neuro", "d": "Paralysis on one side of the body.", "et": "FES", "ep": "35Hz, 300us", "er": "Re-education", "ut": "None", "up": "None", "ur": "None", "ex": "Task-oriented training", "ex_r": "Neuroplasticity", "ef": "Daily", "ei": "High", "ev": "Grade A", "src": "Carr & Shepherd", "img": "/static/uploads/stroke.jpg"},
            {"n": "Bell's Palsy", "c": "Neurology", "k": "facial, nerve", "d": "Facial nerve paralysis.", "et": "ESTR", "ep": "Interrupted DC", "er": "Muscle stimulation", "ut": "None", "up": "None", "ur": "None", "ex": "Facial expressions", "ex_r": "Function", "ef": "2x/daily", "ei": "Threshold", "ev": "Grade B", "src": "Tidy's", "img": "/static/uploads/face.jpg"},
            {"n": "Cerebral Palsy (Spastic)", "c": "Pediatrics", "k": "cp, child, peds", "d": "Motor disorder due to brain damage.", "et": "NMES", "ep": "Antagonist muscles", "er": "Reduce spasticity", "ut": "None", "up": "None", "ur": "None", "ex": "Stretching, NDT", "ex_r": "Function", "ef": "Daily", "ei": "Mild", "ev": "Grade A", "src": "Tecklin", "img": "/static/uploads/cp.jpg"},
            {"n": "Sciatica", "c": "Orthopedics", "k": "nerve, leg pain", "d": "Pain radiating along the sciatic nerve.", "et": "TENS", "ep": "Burst mode", "er": "Endorphin release", "ut": "Hot Pack", "up": "20 mins", "ur": "Relaxation", "ex": "Nerve gliding", "ex_r": "Mobilization", "ef": "Daily", "ei": "Comfortable", "ev": "Grade A", "src": "Magee", "img": "/static/uploads/sciatica.jpg"},
            {"n": "Ankle Sprain", "c": "Sports", "k": "ankle, ligament", "d": "Ligament injury in the ankle.", "et": "Cryotherapy", "ep": "Ice 15 mins", "er": "Vasoconstriction", "ut": "US", "up": "Pulsed 20%", "ur": "Healing (Subacute)", "ex": "Proprioception", "ex_r": "Balance", "ef": "3x/week", "ei": "Functional", "ev": "Grade A", "src": "Brotzman", "img": "/static/uploads/ankle.jpg"},
            {"n": "Plantar Fasciitis", "c": "Orthopedics", "k": "foot, heel", "d": "Inflammation of the plantar fascia.", "et": "Ultrasound", "ep": "1.5 W/cm2 continuous", "er": "Extensibility", "ut": "Shockwave", "up": "2000 shocks", "ur": "Break adhesions", "ex": "Calf stretching", "ex_r": "Flexibility", "ef": "Daily", "ei": "Moderate", "ev": "Grade A", "src": "Dutton", "img": "/static/uploads/foot.jpg"},
            {"n": "Neck Pain (Cervical Spondylosis)", "c": "Orthopedics", "k": "neck, cervical", "d": "Degeneration of cervical spine.", "et": "IFT", "ep": "4000Hz base", "er": "Pain relief", "ut": "Hot Pack", "up": "15 mins", "ur": "Relaxation", "ex": "Chin tucks", "ex_r": "Posture", "ef": "Daily", "ei": "Low", "ev": "Grade A", "src": "Maitland", "img": "/static/uploads/neck.jpg"},
            {"n": "Rotator Cuff Tendinitis", "c": "Orthopedics", "k": "shoulder, cuff", "d": "Inflammation of shoulder tendons.", "et": "US", "ep": "1MHz, pulsed", "er": "Healing", "ut": "Laser", "up": "Low level", "ur": "Repair", "ex": "Isometrics", "ex_r": "Strength", "ef": "3x/week", "ei": "Submaximal", "ev": "Grade A", "src": "Kisner", "img": "/static/uploads/shoulder_cuff.jpg"},
            {"n": "Patellofemoral Pain Syndrome", "k": "knee, runner", "d": "Pain around the kneecap.", "et": "Biofeedback", "ep": "VMO muscle", "er": "Re-education", "ut": "Ice", "up": "10 mins", "ur": "Pain", "ex": "VMO strengthening", "ex_r": "Tracking", "ef": "3x/week", "ei": "Moderate", "ev": "Grade A", "src": "Brotzman", "img": "/static/uploads/knee_vmo.jpg"},
            {"n": "Guillain-Barre Syndrome", "c": "Neurology", "k": "gbs, neuro", "d": "Rapid-onset muscle weakness.", "et": "None", "ep": "Avoid fatigue", "er": "None", "ut": "None", "up": "None", "ur": "None", "ex": "PROM -> AAROM", "ex_r": "Maintain range", "ef": "Daily", "ei": "Gentle", "ev": "Grade B", "src": "O'Sullivan", "img": "/static/uploads/gbs.jpg"},
            {"n": "Multiple Sclerosis", "c": "Neurology", "k": "ms, neuro", "d": "Demyelinating disease.", "et": "Cooling vest", "ep": "Minimize heat", "er": "Performance", "ut": "None", "up": "None", "ur": "None", "ex": "Energy conservation", "ex_r": "Endurance", "ef": "3x/week", "ei": "Sub-fatigue", "ev": "Grade A", "src": "O'Sullivan", "img": "/static/uploads/ms.jpg"},
            {"n": "Rheumatoid Arthritis", "c": "Orthopedics", "k": "ra, hand, joint", "d": "Autoimmune joint inflammation.", "et": "Paraffin Wax", "ep": "Dip method", "er": "Pain/Stiffness", "ut": "TENS", "up": "Conv. mode", "ur": "Pain", "ex": "Gentle AROM", "ex_r": "Mobility", "ef": "Daily", "ei": "Painless", "ev": "Grade B", "src": "Tidy's", "img": "/static/uploads/hand_ra.jpg"},
            {"n": "Scoliosis", "c": "Orthopedics", "k": "spine, curve", "d": "Sideways curvature of the spine.", "et": "NMES", "ep": "Convex side", "er": "Muscle balance", "ut": "None", "up": "None", "ur": "None", "ex": "Schroth method", "ex_r": "Correction", "ef": "Daily", "ei": "Corrective", "ev": "Grade A", "src": "Kisner", "img": "/static/uploads/spine.jpg"},
            {"n": "Achilles Tendinitis", "c": "Orthopedics", "k": "heel, tendon", "d": "Overuse of the Achilles tendon.", "et": "US", "ep": "3MHz pulsed", "er": "Healing", "ut": "Eccentric load", "up": "Slow drop", "ur": "Remodeling", "ex": "Heel drops", "ex_r": "Strength", "ef": "Daily", "ei": "High-eccentric", "ev": "Grade A", "src": "Brotzman", "img": "/static/uploads/heel.jpg"},
            {"n": "Fibromyalgia", "c": "General", "k": "fibro, pain", "d": "Widespread musculoskeletal pain.", "et": "TENS", "ep": "Burst/Acupuncture", "er": "Central pain", "ut": "Heat", "up": "General", "ur": "Relaxation", "ex": "Aerobic (Low impact)", "ex_r": "Endurance", "ef": "3x/week", "ei": "Low-Moderate", "ev": "Grade A", "src": "Dutton", "img": "/static/uploads/body.jpg"}
        ]

        for p in protocols_data:
            new_p = Protocol(
                disease_name=p["n"], 
                category=p.get("c", "General"),
                keywords=p["k"], 
                description=p["d"],
                estim_type=p["et"], 
                estim_params=p["ep"], 
                estim_role=p["er"],
                us_type=p["ut"], 
                us_params=p["up"], 
                us_role=p["ur"],
                exercises_list=p["ex"], 
                exercises_role=p["ex_r"],
                ex_frequency=p.get("ef", "3x/week"),
                ex_intensity=p.get("ei", "Moderate"),
                evidence_level=p.get("ev", "Grade A"),
                source_ref=p["src"], 
                electrode_image=p["img"]
            )
            db.session.add(new_p)
        
        db.session.commit()
        return "<h1>✅ System Reset & Data Updated!</h1><a href='/login'>Login</a>"
    except Exception as e: return f"Error: {str(e)}"

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=False)









