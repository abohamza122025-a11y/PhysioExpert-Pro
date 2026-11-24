import os
import base64
import pandas as pd
from functools import wraps
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, abort, session
from sqlalchemy import text
from io import BytesIO
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from google import genai
from google.genai import types
import json
import secrets
import hmac
import nh3

# ==========================================
# إعدادات التطبيق
# ==========================================
app = Flask(__name__)

# استخدام متغير البيئة للمفتاح السري، أو قيمة احتياطية عشوائية للأمان
# In hosted environments, never fall back to a public/default signing key.
SECRET_KEY = os.environ.get('SECRET_KEY')
if os.environ.get('RENDER') and (not SECRET_KEY or len(SECRET_KEY) < 32):
    raise RuntimeError("A strong SECRET_KEY (at least 32 characters) must be configured in Render.")
app.secret_key = SECRET_KEY or os.urandom(32)

# Secure session and request defaults. HTTPS-only cookies are enabled on Render.
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=bool(os.environ.get('RENDER')),
    SESSION_COOKIE_SAMESITE='Lax',
    MAX_CONTENT_LENGTH=16 * 1024 * 1024,
)

# ==========================================
# إعدادات الذكاء الاصطناعي (مؤمنة)
# ==========================================
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

# التحقق من وجود المفتاح قبل تشغيل التطبيق
if not GEMINI_API_KEY:
    # هذا التنبيه سيظهر في السجلات (Logs) إذا نسينا وضع المفتاح في Render
    print("Warning: GEMINI_API_KEY not found in environment variables.")
else:
    pass

# Official, actively maintained Google Gen AI SDK client.
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-flash-latest')

# ==========================================
# إعدادات قاعدة البيانات
# ==========================================
db_url = os.environ.get('DATABASE_URL', 'sqlite:///physio.db')

# إصلاح مشكلة اسم قاعدة البيانات في Render (postgres vs postgresql)
# Force SQLAlchemy to use the installed psycopg2 driver.
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace(
        "postgres://",
        "postgresql+psycopg2://",
        1
    )
elif db_url and db_url.startswith("postgresql://"):
    db_url = db_url.replace(
        "postgresql://",
        "postgresql+psycopg2://",
        1
    )
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# ... (كود تصحيح رابط قاعدة البيانات موجود هنا)
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {"pool_pre_ping": True}


# ده السطر القديم اللي موجود عندك، خليه زي ما هو
db = SQLAlchemy(app)

# New clinical library models use separate clinical_* tables.
# They do not replace the legacy User or Protocol models.
from clinical_models import register_clinical_models
CLINICAL_MODELS = register_clinical_models(db)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# CSRF protection for every state-changing POST form.
@app.before_request
def enforce_csrf():
    if request.method == "POST":
        supplied = request.form.get("csrf_token", "")
        expected = session.get("_csrf_token", "")
        if not supplied or not expected or not hmac.compare_digest(supplied, expected):
            abort(400, description="CSRF validation failed.")

@app.context_processor
def inject_csrf_token():
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_urlsafe(32)
    return {"csrf_token": session["_csrf_token"]}

def sanitize_rich_html(value):
    return nh3.clean(
        value or "",
        tags={"b", "strong", "i", "em", "u", "p", "br", "ul", "ol", "li", "h4", "h5", "hr"},
        attributes={},
        url_schemes=set(),
        strip_comments=True,
    )

def read_safe_image_upload(upload):
    if not upload or not upload.filename:
        return ""
    raw = upload.stream.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("Image exceeds the 2 MB limit.")
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif raw.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        raise ValueError("Only valid PNG, JPEG, or WEBP image files are accepted.")
    return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")

# ... هنا يكمل باقي الكود الخاص بالـ Routes والـ Functions ...
# --- بيانات الموقع الثابتة ---
@app.after_request
def add_security_headers(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
    response.headers.setdefault('Content-Security-Policy',
        "default-src 'self' https: data:; img-src 'self' https: data:; "
        "style-src 'self' 'unsafe-inline' https:; script-src 'self' 'unsafe-inline' https:; "
        "font-src 'self' https: data:; frame-ancestors 'self'; base-uri 'self'; form-action 'self'")
    if os.environ.get('RENDER'):
        response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
    return response

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
    # جعلنا التصنيف 200 للأمان
    category = db.Column(db.String(200), default="General") 
    disease_name = db.Column(db.String(200), nullable=False)
    
    # 👇👇 حولنا كل شيء يحتمل الطول إلى db.Text 👇👇
    keywords = db.Column(db.Text)
    description = db.Column(db.Text)
    
    estim_type = db.Column(db.String(200))
    estim_params = db.Column(db.Text)
    estim_role = db.Column(db.Text)
    
    us_type = db.Column(db.String(200))
    us_params = db.Column(db.Text)
    us_role = db.Column(db.Text)
    
    exercises_list = db.Column(db.Text)
    exercises_role = db.Column(db.Text)
    
    ex_frequency = db.Column(db.Text)
    ex_intensity = db.Column(db.Text)
    ex_progression = db.Column(db.Text)
    
    # ⚠️ دي كانت سبب المشكلة الأخيرة، حولناها لـ Text
    evidence_level = db.Column(db.Text) 
    
    source_ref = db.Column(db.Text)
    
    electrode_image = db.Column(db.Text)
    video_link = db.Column(db.Text) # أحياناً الروابط بتكون طويلة
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
# --- دالة الذكاء الاصطناعي (النسخة المحسنة والمفصلة) ---
# --- دالة الذكاء الاصطناعي (نسخة الاستشاري - Pro) ---
def get_ai_protocol(disease_search):
    try:
        # إعدادات لزيادة طول الإجابة وسماحية الإبداع
        # max_output_tokens=3000: يسمح بكتابة مقال طويل جداً
        # temperature=0.7: يجعل التمارين متنوعة وليست محفوظة
        if client is None:
            print("Warning: GEMINI_API_KEY is not configured; AI generation is unavailable.")
            return None

        config = types.GenerateContentConfig(
            temperature=0.7,
            max_output_tokens=3000,
        )

        prompt = f"""
        Act as a Senior Physiotherapist Consultant with 20 years of experience. 
        Create a HIGHLY DETAILED Treatment Protocol for: "{disease_search}".

        CRITICAL INSTRUCTIONS:
        1. DO NOT Summarize. Be verbose and detailed.
        2. Exercises: You MUST provide 6 to 8 distinct exercises.
        3. For EACH exercise, format it exactly like this:
           - <b>Exercise Name</b><br>
           - Sets: [Number] | Reps: [Number]<br>
           - Instructions: [Detailed how-to]<br><br>
        4. Modalities: Be specific (Hz, us, W/cm2).

        OUTPUT FORMAT: Return a raw JSON object ONLY.
        Keys required: 
        "disease_name", 
        "keywords" (comma separated string), 
        "description" (detailed paragraph), 
        "estim_type", "estim_params", "estim_role", 
        "us_type", "us_params", "us_role", 
        "exercises_list" (This must be a single String containing all exercises formatted with HTML tags <br> and <b> as requested above), 
        "exercises_role", 
        "source_ref",
        "video_link" (return null or empty string),
        "electrode_image" (return null or empty string).

        If input is not medical, return JSON with key "error".
        """
        
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=config,
        )
        text_response = response.text.strip()
        
        # تنظيف الرد من علامات الـ Markdown
        if text_response.startswith("```json"): text_response = text_response[7:]
        if text_response.endswith("```"): text_response = text_response[:-3]
        
        data = json.loads(text_response)
        
        if "error" in data: return None
        return data

    except Exception as e:
        print(f"❌ AI Error: {e}")
        return None
# ==========================================
# 3. المسارات (Routes)
# ==========================================

# ⚠️ هام جداً: هذا الرابط بدون حماية لكي يعمل الإصلاح
# Disabled: database schema changes must be handled by reviewed migrations, not a public URL.
@app.route('/admin/update-db-schema')
def update_db_schema():
    abort(404)

# Disabled until the admin UI is changed to POST with CSRF protection.
@app.route('/admin/toggle-print/<int:user_id>', methods=['POST'])
@admin_required
def toggle_print(user_id):
    user = User.query.get_or_404(user_id)
    user.can_print = not user.can_print
    db.session.commit()
    flash(f"Printing permission updated for {user.email}.", "info")
    return redirect(url_for("admin_dashboard"))

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
    # 1. استلام الكلمة من المستخدم
    raw_query = request.args.get('disease') or request.form.get('disease')
    
    if raw_query:
        # 🧼 خطوة التنظيف الشاملة:
        # 1. strip: تشيل المسافات من الأول والآخر
        # 2. split + join: تحول أي مسافات مزدوجة في النص لمسافة واحدة
        clean_query = " ".join(raw_query.strip().split())

        # 🎯 تجهيز مصطلح البحث (علامة % معناها: هات أي حاجة قبلها أو بعدها)
        term = f"%{clean_query}%"

        # 🔍 البحث في قاعدة البيانات
        result = Protocol.query.filter(
            (Protocol.disease_name.ilike(term)) |  # يبحث في الاسم
            (Protocol.keywords.ilike(term))        # يبحث في الكلمات الدلالية
        ).first()

        # 🤖 لو ملقاش في الداتابيز، يسأل الذكاء الاصطناعي بالكلمة النظيفة
        if not result:
            result = get_ai_protocol(clean_query)
    
    if result:
        if isinstance(result, dict):
            result["exercises_list"] = sanitize_rich_html(result.get("exercises_list", ""))
        else:
            result.exercises_list = sanitize_rich_html(result.exercises_list or "")
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

# Password reset is POST-only; password is never placed in a URL.
@app.route('/admin/reset-user-password/<int:user_id>', methods=['POST'])
@admin_required
def manual_reset(user_id):
    user = User.query.get_or_404(user_id)
    new_password = request.form.get("new_password", "")
    if len(new_password) < 12:
        flash("Password must be at least 12 characters.", "danger")
        return redirect(url_for("admin_dashboard"))
    user.password = generate_password_hash(new_password, method="pbkdf2:sha256")
    db.session.commit()
    flash(f"Password updated for {user.email}.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route('/admin/add-manual', methods=['POST'])
@admin_required
def add_manual():
    try:
        image_data = read_safe_image_upload(request.files.get("electrode_image"))
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("admin_dashboard"))

    form = request.form
    disease_name = form.get("disease_name", "").strip()
    if not disease_name:
        flash("Disease name is required.", "danger")
        return redirect(url_for("admin_dashboard"))

    p = Protocol(
        disease_name=disease_name,
        category=form.get("category", "General").strip() or "General",
        keywords=form.get("keywords", "").strip(),
        description=form.get("description", "").strip(),
        estim_type=form.get("estim_type", "").strip(),
        estim_params=form.get("estim_params", "").strip(),
        estim_role=form.get("estim_role", "").strip(),
        # These fields are optional because the current admin form does not include them.
        us_type=form.get("us_type", "").strip(),
        us_params=form.get("us_params", "").strip(),
        us_role=form.get("us_role", "").strip(),
        exercises_list=sanitize_rich_html(form.get("exercises_list", "")),
        exercises_role=form.get("exercises_role", "").strip(),
        ex_frequency=form.get("ex_frequency"),
        ex_intensity=form.get("ex_intensity"),
        ex_progression=form.get("ex_progression"),
        evidence_level=form.get("evidence_level", "Grade A"),
        source_ref=form.get("source_ref", "").strip(),
        video_link=form.get("video_link", "").strip(),
        notes=form.get("notes", "").strip(),
        electrode_image=image_data,
    )
    try:
        db.session.add(p)
        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception("Unable to add manual protocol")
        flash("Unable to save the protocol. Please review the entered data.", "danger")
        return redirect(url_for("admin_dashboard"))

    flash("Manual Protocol Added Successfully!", "success")
    return redirect(url_for("admin_dashboard"))

@app.route('/admin/edit/<int:id>', methods=['GET', 'POST'])
@admin_required
def edit_protocol(id):
    p = Protocol.query.get_or_404(id)
    if request.method == 'POST':
        form = request.form
        p.disease_name = form.get('disease_name', p.disease_name).strip()
        p.category = form.get('category', p.category)
        p.description = form.get('description', p.description)
        p.keywords = form.get('keywords', p.keywords)
        p.estim_type = form.get('estim_type', p.estim_type)
        p.estim_params = form.get('estim_params', p.estim_params)
        p.estim_role = form.get('estim_role', p.estim_role)
        p.us_type = form.get('us_type', p.us_type)
        p.us_params = form.get('us_params', p.us_params)
        p.us_role = form.get('us_role', p.us_role)
        p.exercises_list = sanitize_rich_html(form.get('exercises_list', p.exercises_list or ''))
        p.exercises_role = form.get('exercises_role', p.exercises_role)
        p.ex_frequency = form.get('ex_frequency', p.ex_frequency)
        # Preserve these existing values unless a future form explicitly submits them.
        if 'ex_intensity' in form:
            p.ex_intensity = form.get('ex_intensity')
        if 'ex_progression' in form:
            p.ex_progression = form.get('ex_progression')
        if 'evidence_level' in form:
            p.evidence_level = form.get('evidence_level')
        p.source_ref = form.get('source_ref', p.source_ref)
        p.video_link = form.get('video_link', p.video_link)
        p.notes = form.get('notes', p.notes)

        try:
            uploaded_image = read_safe_image_upload(request.files.get("electrode_image"))
            if uploaded_image:
                p.electrode_image = uploaded_image
        except ValueError as exc:
            flash(str(exc), "danger")
            return render_template("edit_protocol.html", protocol=p), 400

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception("Unable to update protocol %s", id)
            flash("Unable to update the protocol. Please review the entered data.", "danger")
            return render_template("edit_protocol.html", protocol=p), 400

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

import pandas as pd # تأكد إن المكتبة دي معمولة import فوق

@app.route('/admin/import-excel', methods=['POST'])
@admin_required
def import_excel():
    if 'excel_file' not in request.files:
        flash('No file selected', 'danger'); return redirect(url_for('admin_dashboard'))
    
    file = request.files['excel_file']
    if file.filename == '':
        flash('No selected file', 'warning'); return redirect(url_for('admin_dashboard'))

    try:
        # Only .xlsx workbooks are accepted; reject CSV and macro-enabled formats.
        if not file.filename.lower().endswith('.xlsx'):
            raise ValueError("Upload an .xlsx file only.")
        file.stream.seek(0)
        if file.stream.read(4) != b'PK\x03\x04':
            raise ValueError("Invalid XLSX file.")
        file.stream.seek(0)
        df = pd.read_excel(file, engine='openpyxl')
        if len(df.index) > 5000 or len(df.columns) > 40:
            raise ValueError("Workbook exceeds the allowed size (5,000 rows / 40 columns).")
        df.columns = df.columns.str.strip()

        def get_val(row, col_name):
            val = row.get(col_name)
            return "" if (pd.isna(val) or str(val).strip() == 'nan') else str(val).strip()

        updated = 0; created = 0

        for _, row in df.iterrows():
            d_name = get_val(row, 'disease_name')
            if not d_name: continue

            p = Protocol.query.filter_by(disease_name=d_name).first()
            if not p:
                p = Protocol(disease_name=d_name); db.session.add(p); created += 1
            else:
                updated += 1

            # --- البيانات الأساسية ---
            p.category = get_val(row, 'category') or 'General'
            p.keywords = get_val(row, 'keywords')
            p.description = get_val(row, 'description')
            p.source_ref = get_val(row, 'source_ref')

            # --- الأجهزة (Estim & US) ---
            p.estim_params = get_val(row, 'estim_params')
            p.estim_type = "Electrical Stimulation" # قيمة ثابتة لأنها مش في الملف
            p.us_params = get_val(row, 'us_params')
            p.us_type = "Ultrasound" # قيمة ثابتة

            # --- التمارين وتفاصيلها (الخانات الخاصة) ---
            p.exercises_list = sanitize_rich_html(get_val(row, 'exercises_list'))
            p.exercises_role = get_val(row, 'exercises_role')
            
            # 👇 هنا التعديل: قراءة الأعمدة الجديدة وحفظها في مكانها
            p.ex_frequency = get_val(row, 'ex_frequency')
            p.ex_intensity = get_val(row, 'ex_intensity')
            p.ex_progression = get_val(row, 'ex_progression')
            p.evidence_level = get_val(row, 'evidence_level')

        db.session.commit()
        flash(f'Done! Created {created}, Updated {updated} protocols.', 'success')

    except Exception as e:
        db.session.rollback()
        print(f"Excel Error: {e}")
        flash(f'Error: {str(e)}', 'danger')

    return redirect(url_for('admin_dashboard'))

# Disabled: deletion by GET is unsafe. Replace with POST + CSRF-protected form.
@app.route('/admin/delete/<int:id>', methods=['POST'])
@admin_required
def delete_protocol(id):
    protocol = Protocol.query.get_or_404(id)
    db.session.delete(protocol)
    db.session.commit()
    flash("Protocol deleted.", "warning")
    return redirect(url_for("admin_dashboard"))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
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
            email = request.form.get('email', '').strip().lower()
            password = request.form.get('password', '')
            if len(password) < 12:
                flash('Password must be at least 12 characters.', 'danger')
                return render_template('register.html'), 400
            if not email or len(email) > 150 or '@' not in email:
                flash('Enter a valid email address.', 'danger')
                return render_template('register.html'), 400
            pw = generate_password_hash(password, method='pbkdf2:sha256')
            db.session.add(User(email=email, password=pw))
            db.session.commit()
            return redirect(url_for('login'))
        except Exception:
            db.session.rollback()
            flash('Unable to create account. The email may already exist.', 'danger')
    return render_template('register.html')

@app.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))
# Disabled: this legacy GET endpoint overwrites legacy protocols by flattening phases.
@app.route('/admin/update-content')
@login_required
def update_content():
    abort(405)

# Permanently disabled: the old route executed db.drop_all() and embedded admin credentials.
@app.route('/setup-sys-secure-hmna12-4-2026')
def setup_system():
    abort(404)

# ==========================================
# دالة استيراد ملف JSON المولد (للعمل على Render)
# ==========================================
# Disabled: legacy importer writes flattened data through GET and can overwrite records.
@app.route('/admin/import-generated-json')
@login_required
def import_generated_json():
    abort(405)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=False)
