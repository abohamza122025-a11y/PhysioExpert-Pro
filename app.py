import os
import base64
import pandas as pd
from functools import wraps
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from sqlalchemy import text
from io import BytesIO
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import google.generativeai as genai
import json

# ==========================================
# إعدادات التطبيق
# ==========================================
app = Flask(__name__)

# استخدام متغير البيئة للمفتاح السري، أو قيمة احتياطية عشوائية للأمان
app.secret_key = os.environ.get('SECRET_KEY', 'default_secret_key_change_in_production')

# ==========================================
# إعدادات الذكاء الاصطناعي (مؤمنة)
# ==========================================
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

# التحقق من وجود المفتاح قبل تشغيل التطبيق
if not GEMINI_API_KEY:
    # هذا التنبيه سيظهر في السجلات (Logs) إذا نسينا وضع المفتاح في Render
    print("Warning: GEMINI_API_KEY not found in environment variables.")
else:
    genai.configure(api_key=GEMINI_API_KEY)

model = genai.GenerativeModel('gemini-1.5-flash')

# ==========================================
# إعدادات قاعدة البيانات
# ==========================================
db_url = os.environ.get('DATABASE_URL', 'sqlite:///physio.db')

# إصلاح مشكلة اسم قاعدة البيانات في Render (postgres vs postgresql)
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# ... (كود تصحيح رابط قاعدة البيانات موجود هنا)
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {"pool_pre_ping": True}


# ده السطر القديم اللي موجود عندك، خليه زي ما هو
db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# ... هنا يكمل باقي الكود الخاص بالـ Routes والـ Functions ...
# --- بيانات الموقع الثابتة ---
@app.context_processor
def inject_global_vars():
    return dict(
        support_email="physioexpert8@gmail.com",
        disclaimer="Disclaimer: For educational purposes only."
    )

# --- الفلاتر ---
@app.template_filter('split_list')
def split_list_filter(s):
    if not s: return []
    return [item.strip() for item in s.split(',')]

# --- 2. الجداول (Models) ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    subscription_end = db.Column(db.DateTime, nullable=True)
    can_print = db.Column(db.Boolean, default=False)

class Protocol(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(100), default="General")
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
    ex_frequency = db.Column(db.String(200))
    ex_intensity = db.Column(db.String(200))
    ex_progression = db.Column(db.Text)
    evidence_level = db.Column(db.String(50), default="Grade A")
    source_ref = db.Column(db.String(300))
    electrode_image = db.Column(db.Text)
    video_link = db.Column(db.String(500), nullable=True)
    notes = db.Column(db.Text, nullable=True)

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

# --- دالة الذكاء الاصطناعي ---
def get_ai_protocol(disease_search):
    try:
        prompt = f"""
        Act as an expert Physiotherapist. Create a detailed treatment protocol for "{disease_search}".
        Return JSON object ONLY. Keys: disease_name, keywords, description, estim_type, estim_params, estim_role, electrode_image, us_type, us_params, us_role, exercises_list, exercises_role, source_ref.
        If not medical, return JSON with key "error".
        """
        response = model.generate_content(prompt)
        text_response = response.text.strip()
        if text_response.startswith("```json"): text_response = text_response[7:]
        if text_response.endswith("```"): text_response = text_response[:-3]
        data = json.loads(text_response)
        if "error" in data: return None
        return data
    except: return None

# ==========================================
# 3. المسارات (Routes)
# ==========================================

# ⚠️ هام جداً: هذا الرابط بدون حماية لكي يعمل الإصلاح
@app.route('/admin/update-db-schema')
def update_db_schema():
    try:
        with db.engine.connect() as conn:
            # 1. إضافة عمود can_print
            try:
                conn.execute(text("ALTER TABLE \"user\" ADD COLUMN can_print BOOLEAN DEFAULT FALSE"))
            except Exception as e:
                print(f"Column can_print might exist: {e}")
            
            # 2. إضافة عمود video_link
            try:
                conn.execute(text("ALTER TABLE protocol ADD COLUMN video_link TEXT"))
            except Exception as e:
                print(f"Column video_link might exist: {e}")

            # 3. إضافة عمود notes
            try:
                conn.execute(text("ALTER TABLE protocol ADD COLUMN notes TEXT"))
            except Exception as e:
                print(f"Column notes might exist: {e}")
            
            conn.commit()
        return "<h1>✅ ALL Columns Added Successfully! (can_print, video_link, notes) <br> <a href='/login'>Go to Login</a></h1>"
    except Exception as e:
        return f"<h1>Error: {str(e)}</h1>"

@app.route('/admin/toggle-print/<int:user_id>')
@admin_required
def toggle_print(user_id):
    user = User.query.get_or_404(user_id)
    user.can_print = not user.can_print
    db.session.commit()
    status = "Enabled" if user.can_print else "Disabled"
    flash(f'Printing permission {status} for {user.email}', 'info')
    return redirect(url_for('admin_dashboard'))        

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
    users = User.query.all()
    return render_template('admin.html', protocols=protocols, users=users)

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

@app.route('/admin/add-manual', methods=['POST'])
@admin_required
def add_manual():
    image_data = ""
    if 'electrode_image' in request.files:
        file = request.files['electrode_image']
        if file.filename != '':
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
        video_link=request.form.get('video_link'),
        notes=request.form.get('notes'),
        electrode_image=image_data
    )
    db.session.add(p)
    db.session.commit()
    flash('Manual Protocol Added Successfully!', 'success')
    return redirect(url_for('admin_dashboard'))
    
@app.route('/admin/edit/<int:id>', methods=['GET', 'POST'])
@admin_required
def edit_protocol(id):
    p = Protocol.query.get_or_404(id)
    if request.method == 'POST':
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
        p.video_link = request.form.get('video_link')
        p.notes = request.form.get('notes')

        if 'electrode_image' in request.files:
            file = request.files['electrode_image']
            if file and file.filename != '':
                encoded_string = base64.b64encode(file.read()).decode('utf-8')
                p.electrode_image = f"data:image/jpeg;base64,{encoded_string}"

        db.session.commit()
        flash('Protocol Updated Successfully!', 'success')
        return redirect(url_for('admin_dashboard'))
    
    return render_template('edit_protocol.html', protocol=p)

@app.route('/admin/export-data')
@admin_required
def export_data():
    protocols = Protocol.query.all()
    p_data = [{
        'disease_name': p.disease_name,
        'category': p.category,
        'description': p.description,
        'notes': p.notes
    } for p in protocols]
    
    df_protocols = pd.DataFrame(p_data)
    
    from io import BytesIO
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_protocols.to_excel(writer, sheet_name='Protocols', index=False)
        users = User.query.all()
        u_data = [{'email': u.email, 'is_admin': u.is_admin} for u in users]
        df_users = pd.DataFrame(u_data)
        df_users.to_excel(writer, sheet_name='Users', index=False)

    output.seek(0)
    
    return send_file(
        output, 
        download_name=f'physio_backup_{datetime.now().strftime("%Y-%m-%d")}.xlsx',
        as_attachment=True,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

@app.route('/admin/import-excel', methods=['POST'])
@admin_required
def import_excel():
    if 'excel_file' not in request.files:
        flash('No file selected', 'danger'); return redirect(url_for('admin_dashboard'))
    
    file = request.files['excel_file']
    if file.filename == '':
        flash('No selected file', 'warning'); return redirect(url_for('admin_dashboard'))

    try:
        df = pd.read_excel(file)
        df.columns = df.columns.str.strip()
        for _, row in df.iterrows():
            new_p = Protocol(
                disease_name=str(row.get('disease_name', 'Unknown')),
                category=str(row.get('category', 'General')),
                description=str(row.get('description', '')),
                notes=str(row.get('notes', ''))
            )
            db.session.add(new_p)
        db.session.commit()
        flash(f'Imported {len(df)} protocols!', 'success')
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
def forgot_password(): return render_template('forgot_password.html')

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
        
        # قائمة الأمراض الكاملة (50 مرض)
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
            {"n": "Fibromyalgia", "c": "General", "k": "fibro, pain", "d": "Widespread musculoskeletal pain.", "et": "TENS", "ep": "Burst/Acupuncture", "er": "Central pain", "ut": "Heat", "up": "General", "ur": "Relaxation", "ex": "Aerobic (Low impact)", "ex_r": "Endurance", "ef": "3x/week", "ei": "Low-Moderate", "ev": "Grade A", "src": "Dutton", "img": "/static/uploads/body.jpg"},
            {"n": "Meniscus Tear", "c": "Orthopedics", "k": "knee, locking", "d": "Tear in the knee cartilage.", "et": "NMES", "ep": "Quads", "er": "Prevent atrophy", "ut": "Ice", "up": "15 mins", "ur": "Edema", "ex": "Mini-squats", "ex_r": "Strength", "ef": "Daily", "ei": "Pain-free", "ev": "Grade A", "src": "Magee", "img": "/static/uploads/knee_meniscus.jpg"},
            {"n": "ACL Reconstruction", "c": "Orthopedics", "k": "knee, acl, surgery", "d": "Post-op rehab for ACL.", "et": "NMES", "ep": "Quads", "er": "Activation", "ut": "Cryo-cuff", "up": "Continuous", "ur": "Swelling", "ex": "Heel slides, Quad sets", "ex_r": "ROM & Strength", "ef": "Daily", "ei": "Protocol-based", "ev": "Grade A", "src": "Brotzman", "img": "/static/uploads/acl.jpg"},
            {"n": "Piriformis Syndrome", "c": "Orthopedics", "k": "buttock pain, sciatica", "d": "Sciatic nerve compression by piriformis.", "et": "US", "ep": "Deep heat", "er": "Relaxation", "ut": "Heat", "up": "20 mins", "ur": "Spasm", "ex": "Piriformis stretch", "ex_r": "Flexibility", "ef": "Daily", "ei": "Moderate", "ev": "Grade B", "src": "Dutton", "img": "/static/uploads/piriformis.jpg"},
            {"n": "Thoracic Outlet Syndrome", "c": "Orthopedics", "k": "tos, arm numb", "d": "Compression of nerves/vessels in neck.", "et": "TENS", "ep": "Sensory", "er": "Pain", "ut": "Heat", "up": "Neck", "ur": "Relaxation", "ex": "Corner stretch, Scalene stretch", "ex_r": "Postural correction", "ef": "Daily", "ei": "Gentle", "ev": "Grade B", "src": "Kisner", "img": "/static/uploads/tos.jpg"},
            {"n": "De Quervain's Tenosynovitis", "c": "Orthopedics", "k": "thumb, wrist", "d": "Pain in thumb tendons.", "et": "US", "ep": "Pulsed", "er": "Inflammation", "ut": "None", "up": "None", "ur": "None", "ex": "Thumb Spica", "ex_r": "Rest", "ef": "Daily", "ei": "Low", "ev": "Grade B", "src": "Brotzman", "img": "/static/uploads/thumb.jpg"},
            {"n": "Temporomandibular Joint Dysfunction", "c": "Orthopedics", "k": "tmj, jaw", "d": "Jaw pain and clicking.", "et": "US", "ep": "0.8 W/cm2", "er": "Relaxation", "ut": "Laser", "up": "Trigger points", "ur": "Pain", "ex": "Rocabado exercises", "ex_r": "Coordination", "ef": "Daily", "ei": "Gentle", "ev": "Grade B", "src": "Magee", "img": "/static/uploads/tmj.jpg"},
            {"n": "Parkinson's Disease", "c": "Neurology", "k": "pd, tremor", "d": "Neurodegenerative disorder.", "et": "Cueing (Auditory)", "ep": "Metronome", "er": "Gait", "ut": "None", "up": "None", "ur": "None", "ex": "Big & Loud (LSVT)", "ex_r": "Amplitude", "ef": "4x/week", "ei": "High", "ev": "Grade A", "src": "O'Sullivan", "img": "/static/uploads/parkinsons.jpg"},
            {"n": "Spinal Cord Injury (Paraplegia)", "c": "Neurology", "k": "sci, paralysis", "d": "Injury to spinal cord.", "et": "FES", "ep": "Cycling", "er": "Fitness", "ut": "None", "up": "None", "ur": "None", "ex": "Transfers, Wheelchair skills", "ex_r": "Independence", "ef": "Daily", "ei": "Moderate", "ev": "Grade A", "src": "O'Sullivan", "img": "/static/uploads/sci.jpg"},
            {"n": "Traumatic Brain Injury", "c": "Neurology", "k": "tbi, head", "d": "Brain injury due to trauma.", "et": "None", "ep": "None", "er": "None", "ut": "None", "up": "None", "ur": "None", "ex": "Dual-task training", "ex_r": "Cognition-Motor", "ef": "Daily", "ei": "Variable", "ev": "Grade A", "src": "Carr & Shepherd", "img": "/static/uploads/tbi.jpg"},
            {"n": "Peripheral Neuropathy", "c": "Neurology", "k": "diabetes, numbness", "d": "Nerve damage in extremities.", "et": "TENS", "ep": "Frequency modulated", "er": "Pain masking", "ut": "Anodyne (IR)", "up": "30 mins", "ur": "Circulation", "ex": "Balance training", "ex_r": "Fall prevention", "ef": "Daily", "ei": "Safe", "ev": "Grade B", "src": "Dutton", "img": "/static/uploads/foot_neuro.jpg"},
            {"n": "Duchenne Muscular Dystrophy", "c": "Pediatrics", "k": "dmd, child", "d": "Genetic muscle wasting.", "et": "None", "ep": "Avoid eccentrics", "er": "None", "ut": "None", "up": "None", "ur": "None", "ex": "Swimming, Cycling", "ex_r": "Maintain function", "ef": "3x/week", "ei": "Submaximal", "ev": "Grade B", "src": "Tecklin", "img": "/static/uploads/dmd.jpg"},
            {"n": "Spina Bifida", "c": "Pediatrics", "k": "myelomeningocele", "d": "Neural tube defect.", "et": "NMES", "ep": "Functional", "er": "Gait", "ut": "None", "up": "None", "ur": "None", "ex": "Gait training", "ex_r": "Mobility", "ef": "Daily", "ei": "Functional", "ev": "Grade A", "src": "Tecklin", "img": "/static/uploads/sb.jpg"},
            {"n": "Torticollis", "c": "Pediatrics", "k": "wry neck, baby", "d": "Twisted neck in infants.", "et": "Microcurrent", "ep": "Gentle", "er": "Relaxation", "ut": "Warmth", "up": "Gentle", "ur": "Relaxation", "ex": "Stretching SCM", "ex_r": "Correction", "ef": "Daily", "ei": "Gentle", "ev": "Grade A", "src": "Tecklin", "img": "/static/uploads/torticollis.jpg"},
            {"n": "Osgood-Schlatter Disease", "c": "Pediatrics", "k": "knee, growth", "d": "Tibial tuberosity pain.", "et": "Ice", "ep": "Post-activity", "er": "Pain", "ut": "None", "up": "Contraindicated", "ur": "Growth plate", "ex": "Hamstring stretch", "ex_r": "Flexibility", "ef": "Daily", "ei": "Pain-free", "ev": "Grade B", "src": "Brotzman", "img": "/static/uploads/osgood.jpg"},
            {"n": "Chronic Obstructive Pulmonary Disease", "c": "Cardiopulmonary", "k": "copd, lung", "d": "Chronic lung obstruction.", "et": "NMES", "ep": "Quads", "er": "Strength (if dyspneic)", "ut": "None", "up": "None", "ur": "None", "ex": "Pursed lip breathing", "ex_r": "Efficiency", "ef": "Daily", "ei": "Borg 3-4", "ev": "Grade A", "src": "Hillegass", "img": "/static/uploads/lungs.jpg"},
            {"n": "Myocardial Infarction (Post-Op)", "c": "Cardiopulmonary", "k": "heart attack, cardiac", "d": "Rehab after heart attack.", "et": "None", "ep": "Monitor ECG", "er": "None", "ut": "None", "up": "None", "ur": "None", "ex": "Phase 1: Mobilization", "ex_r": "Function", "ef": "Daily", "ei": "Low (HR+20)", "ev": "Grade A", "src": "Hillegass", "img": "/static/uploads/heart.jpg"},
            {"n": "Cystic Fibrosis", "c": "Cardiopulmonary", "k": "cf, mucus", "d": "Genetic lung disease.", "et": "None", "ep": "None", "er": "None", "ut": "Flutter/PEP", "up": "Device", "ur": "Clearance", "ex": "Aerobic", "ex_r": "Airway clearance", "ef": "Daily", "ei": "High", "ev": "Grade A", "src": "Hillegass", "img": "/static/uploads/cf.jpg"},
            {"n": "Lymphedema", "c": "Cardiopulmonary", "k": "swelling, lymph", "d": "Fluid accumulation.", "et": "None", "ep": "None", "er": "None", "ut": "None", "up": "None", "ur": "None", "ex": "Decongestive exercises", "ex_r": "Pump", "ef": "Daily", "ei": "Slow", "ev": "Grade A", "src": "Hillegass", "img": "/static/uploads/lymph.jpg"},
            {"n": "Burn Injury", "c": "Integumentary", "k": "skin, burn", "d": "Thermal injury.", "et": "TENS", "ep": "During debridement", "er": "Pain", "ut": "US (Non-thermal)", "up": "Pulsed", "ur": "Healing", "ex": "ROM (Anti-contracture)", "ex_r": "Mobility", "ef": "Daily", "ei": "Painful", "ev": "Grade A", "src": "Cameron", "img": "/static/uploads/burn.jpg"},
            {"n": "Pressure Ulcer", "c": "Integumentary", "k": "bed sore", "d": "Skin breakdown.", "et": "HVPC", "ep": "Negative polarity", "er": "Healing", "ut": "US", "up": "Periwound", "ur": "Circulation", "ex": "Positioning", "ex_r": "Offloading", "ef": "2 hrs", "ei": "N/A", "ev": "Grade A", "src": "Cameron", "img": "/static/uploads/ulcer.jpg"},
            {"n": "Shin Splints", "c": "Sports", "k": "mtss, leg", "d": "Medial tibial stress syndrome.", "et": "Ice", "ep": "Massage", "er": "Pain", "ut": "US", "up": "Low intensity", "ur": "Healing", "ex": "Toe taps, Calf stretch", "ex_r": "Loading", "ef": "Daily", "ei": "Low", "ev": "Grade B", "src": "Brotzman", "img": "/static/uploads/shin.jpg"},
            {"n": "Groin Strain", "c": "Sports", "k": "adductor, hip", "d": "Strain of adductor muscles.", "et": "TENS", "ep": "Pain mode", "er": "Pain", "ut": "None", "up": "None", "ur": "None", "ex": "Adductor squeeze", "ex_r": "Strength", "ef": "3x/week", "ei": "Isom->Iso", "ev": "Grade B", "src": "Brotzman", "img": "/static/uploads/groin.jpg"},
            {"n": "Hamstring Strain", "c": "Sports", "k": "thigh, pull", "d": "Tear in hamstring.", "et": "None", "ep": "None", "er": "None", "ut": "None", "up": "None", "ur": "None", "ex": "Nordic Hamstring", "ex_r": "Eccentric", "ef": "2x/week", "ei": "High", "ev": "Grade A", "src": "Brotzman", "img": "/static/uploads/hamstring.jpg"},
            {"n": "Bankart Repair", "c": "Orthopedics", "k": "shoulder instability", "d": "Post-op for instability.", "et": "NMES", "ep": "Post-delt", "er": "Strength", "ut": "None", "up": "None", "ur": "None", "ex": "Closed chain", "ex_r": "Stability", "ef": "Daily", "ei": "Graded", "ev": "Grade A", "src": "Kisner", "img": "/static/uploads/bankart.jpg"},
            {"n": "Total Knee Arthroplasty", "c": "Orthopedics", "k": "tka, joint replacement", "d": "Knee replacement rehab.", "et": "NMES", "ep": "Quads", "er": "Activation", "ut": "None", "up": "None", "ur": "None", "ex": "Heel slides, Bikes", "ex_r": "ROM", "ef": "Daily", "ei": "Moderate", "ev": "Grade A", "src": "Kisner", "img": "/static/uploads/tka.jpg"},
            {"n": "Total Hip Arthroplasty", "c": "Orthopedics", "k": "tha, hip", "d": "Hip replacement rehab.", "et": "None", "ep": "None", "er": "None", "ut": "None", "up": "None", "ur": "None", "ex": "Abduction (Standing)", "ex_r": "Strength", "ef": "Daily", "ei": "Moderate", "ev": "Grade A", "src": "Kisner", "img": "/static/uploads/tha.jpg"},
            {"n": "Bicipital Tendinitis", "c": "Orthopedics", "k": "biceps, shoulder", "d": "Long head of biceps pain.", "et": "US", "ep": "Pulsed", "er": "Inflammation", "ut": "None", "up": "None", "ur": "None", "ex": "Speed's test exercise", "ex_r": "Strength", "ef": "3x/week", "ei": "Low", "ev": "Grade B", "src": "Magee", "img": "/static/uploads/biceps.jpg"},
            {"n": "Spondylolisthesis", "c": "Orthopedics", "k": "spine, slip", "d": "Vertebral slippage.", "et": "None", "ep": "Avoid ext", "er": "None", "ut": "Heat", "up": "Lumbar", "ur": "Relaxation", "ex": "Flexion bias (Williams)", "ex_r": "Stability", "ef": "Daily", "ei": "Core", "ev": "Grade B", "src": "Magee", "img": "/static/uploads/spondylo.jpg"},
            {"n": "Stenosis (Lumbar)", "c": "Orthopedics", "k": "narrowing, spine", "d": "Narrowing of spinal canal.", "et": "TENS", "ep": "L4-S1", "er": "Pain", "ut": "None", "up": "None", "ur": "None", "ex": "Flexion exercises", "ex_r": "Open canal", "ef": "Daily", "ei": "Gentle", "ev": "Grade A", "src": "Magee", "img": "/static/uploads/stenosis.jpg"},
            {"n": "Whiplash Injury", "c": "Orthopedics", "k": "wads, neck", "d": "Neck injury from acceleration.", "et": "TENS", "ep": "High rate", "er": "Acute pain", "ut": "None", "up": "None", "ur": "None", "ex": "Eye-head coordination", "ex_r": "Control", "ef": "Daily", "ei": "Pain-free", "ev": "Grade B", "src": "Magee", "img": "/static/uploads/whiplash.jpg"}
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


