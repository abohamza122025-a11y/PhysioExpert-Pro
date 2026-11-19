import os
import json
import math
import base64
import hashlib
from io import BytesIO
from functools import wraps
from datetime import datetime, timedelta

import pandas as pd
from flask import (Flask, render_template, request, redirect, url_for,
                   flash, send_file)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (LoginManager, UserMixin, login_user, login_required,
                         logout_user, current_user)
from markupsafe import escape
from sqlalchemy import text, inspect
from werkzeug.security import generate_password_hash, check_password_hash
import google.generativeai as genai

# ==========================================
# إعدادات التطبيق
# ==========================================
app = Flask(__name__)

# ==========================================
# سياسة الاشتراك (غيّر الأرقام من هنا فقط)
# ==========================================
TRIAL_DAYS = 30          # التجربة المجانية
SUB_DAYS = 30            # مدة الاشتراك الشهري
PRINT_WAIT_HOURS = 24    # الطباعة تتفعل بعد أول 24 ساعة من الاشتراك المدفوع
MONTHLY_PRICE_EGP = 150
INSTAPAY_ADDRESS = "mahmoudelseleimy@instapay"

# ==========================================
# قاعدة البيانات
# ==========================================
db_url = os.environ.get('DATABASE_URL', 'sqlite:///physio.db')
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

_secret = os.environ.get('SECRET_KEY')
if not _secret:
    print("WARNING: SECRET_KEY is not set. Set it in Render > Environment.")
    _secret = hashlib.sha256(("physio-" + db_url).encode()).hexdigest()
app.secret_key = _secret

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {"pool_pre_ping": True}

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# ==========================================
# الذكاء الاصطناعي
# ==========================================
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')
else:
    print("Warning: GEMINI_API_KEY not found in environment variables.")
    model = None


# --- بيانات الموقع الثابتة ---
@app.context_processor
def inject_global_vars():
    return dict(
        support_email="physioexpert8@gmail.com",
        instapay_address=INSTAPAY_ADDRESS,
        monthly_price=MONTHLY_PRICE_EGP,
        disclaimer="Disclaimer: For educational purposes only."
    )


# --- الفلاتر ---
@app.template_filter('split_list')
def split_list_filter(s):
    if not s:
        return []
    return [item.strip() for item in s.split(',')]


# ==========================================
# الجداول (Models)
# ==========================================
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    subscription_end = db.Column(db.DateTime, nullable=True)
    subscribed_at = db.Column(db.DateTime, nullable=True)
    can_print_override = db.Column('can_print', db.Boolean, default=False)

    # ---------- حالة الاشتراك ----------
    @property
    def trial_end(self):
        return (self.created_at or datetime.utcnow()) + timedelta(days=TRIAL_DAYS)

    @property
    def is_paid(self):
        return bool(self.subscription_end and self.subscription_end > datetime.utcnow())

    @property
    def in_trial(self):
        return (not self.is_paid) and datetime.utcnow() < self.trial_end

    @property
    def has_access(self):
        return bool(self.is_admin or self.is_paid or self.in_trial)

    @property
    def days_left(self):
        if self.is_admin:
            return None
        end = self.subscription_end if self.is_paid else self.trial_end
        secs = (end - datetime.utcnow()).total_seconds()
        return max(math.ceil(secs / 86400), 0)

    @property
    def can_print(self):
        """الطباعة: للأدمن دايمًا. للمشترك بعد 24 ساعة. التجربة المجانية: ممنوعة."""
        if self.is_admin:
            return True
        if not self.is_paid:
            return False
        if self.can_print_override:
            return True
        if self.subscribed_at is None:
            return True
        unlock = self.subscribed_at + timedelta(hours=PRINT_WAIT_HOURS)
        return datetime.utcnow() >= unlock

    @property
    def status_label(self):
        if self.is_admin:
            return "Admin"
        if self.is_paid:
            return f"Paid - {self.days_left} days left"
        if self.in_trial:
            return f"Trial - {self.days_left} days left"
        return "Expired"


class Protocol(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(200), default="General")
    disease_name = db.Column(db.String(200), nullable=False)
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

    evidence_level = db.Column(db.Text)
    source_ref = db.Column(db.Text)

    electrode_image = db.Column(db.Text)
    video_link = db.Column(db.Text)
    notes = db.Column(db.Text, nullable=True)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Admin access required', 'danger')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function


# ==========================================
# تحديث الجداول تلقائيًا عند التشغيل
# ==========================================
def ensure_schema():
    messages = []
    try:
        with app.app_context():
            db.create_all()
            insp = inspect(db.engine)
            wanted = {
                'user': [('can_print', 'BOOLEAN DEFAULT FALSE'),
                         ('subscribed_at', 'TIMESTAMP')],
                'protocol': [('video_link', 'TEXT'), ('notes', 'TEXT')],
            }
            for table, cols in wanted.items():
                if not insp.has_table(table):
                    continue
                existing = {c['name'] for c in insp.get_columns(table)}
                for name, ctype in cols:
                    if name in existing:
                        continue
                    try:
                        with db.engine.begin() as conn:
                            conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN {name} {ctype}'))
                        messages.append(f"added {table}.{name}")
                    except Exception as e:
                        messages.append(f"{table}.{name}: {e}")
    except Exception as e:
        print(f"ensure_schema error: {e}")
        messages.append(str(e))
    return messages


ensure_schema()


# ==========================================
# منع الطباعة (Ctrl+P) لغير المصرّح لهم - من السيرفر
# ==========================================
PRINT_LOCK_CSS = (
    '<style>@media print{body{display:none!important}'
    'html::before{content:"Printing is available for paid subscribers '
    '24 hours after activation.";display:block;padding:40px;font:20px sans-serif}}</style>'
)


@app.after_request
def lock_printing(resp):
    try:
        if (resp.mimetype == 'text/html' and not resp.direct_passthrough
                and current_user.is_authenticated and not current_user.can_print):
            html = resp.get_data(as_text=True)
            if '</head>' in html:
                resp.set_data(html.replace('</head>', PRINT_LOCK_CSS + '</head>', 1))
    except Exception as e:
        print(f"print-lock error: {e}")
    return resp


# ==========================================
# معاملات الموجات فوق الصوتية (Ultrasound) لكل الحالات
# ==========================================
NONE3 = ("None", "None", "None")

US_RULES = {
    "Adhesive Capsulitis": (
        "Therapeutic Ultrasound (Continuous - thermal)",
        "1 MHz | Continuous | 1.0-1.5 W/cm2 | 5-8 min over the capsule with the arm in stretch position | 3-5 sessions/week",
        "Increase capsular extensibility before stretching/mobilization in the stiff stage. In the painful/irritable stage use Pulsed 20% at 0.5-0.8 W/cm2 instead."),
    "Knee Osteoarthritis": (
        "Therapeutic Ultrasound (Optional adjunct)",
        "3 MHz (1 MHz if deep) | Pulsed 20% for flare-ups, Continuous for chronic stiffness | 0.8-1.0 W/cm2 | 5-8 min over the joint line | 3x/week",
        "Short-term pain and stiffness relief to enable exercise. Evidence is limited; exercise remains the core treatment."),
    "Low Back Pain (Mechanical)": (
        "IR Lamp / Ultrasound (optional)",
        "1 MHz | Continuous | 1.0-1.5 W/cm2 | 5-8 min per paraspinal area | 3x/week for 2-3 weeks maximum",
        "Reduce muscle guarding before exercise. Weak evidence, not a stand-alone treatment. Rule out red flags first."),
    "Carpal Tunnel Syndrome": (
        "Therapeutic Ultrasound (Pulsed)",
        "3 MHz | Pulsed 20% | 0.8-1.0 W/cm2 | 5 min over the volar wrist (small head) | 3-5x/week for 2-3 weeks",
        "Reduce inflammation and median nerve irritation. Combine with night splinting and nerve gliding."),
    "Lateral Epicondylitis": (
        "Therapeutic Ultrasound (Pulsed)",
        "3 MHz | Pulsed 20% (acute) or Continuous 1.0 W/cm2 (chronic) | 0.8-1.0 W/cm2 pulsed | 5 min over the common extensor origin | 3x/week",
        "Stimulate tendon repair and reduce pain. Adjunct to eccentric loading, which is the primary treatment."),
    "Stroke (Hemiplegia)": (
        "Therapeutic Ultrasound (Adjunct)",
        "1 MHz | Pulsed 20-50% (painful shoulder) or Continuous (tight tissue) | 0.5-1.0 W/cm2 | 5-8 min per area | 3-5x/week | Reduce dose over areas with impaired sensation",
        "Adjunct for hemiplegic shoulder pain and periarticular tightness before stretching. Evidence is limited."),
    "Bell's Palsy": (
        "Not indicated",
        "Do not apply ultrasound over the face",
        "Use facial exercises and electrical stimulation as per protocol."),
    "Cerebral Palsy (Spastic)": (
        "Not routinely indicated",
        "Avoid over open growth plates; the child may not report excessive heat",
        "Prefer stretching, positioning and NDT-based handling."),
    "Sciatica": (
        "Hot Pack / Ultrasound (optional)",
        "1 MHz | Continuous | 1.0-1.5 W/cm2 | 5-8 min over the gluteal/paraspinal muscle belly | 3x/week | Do not treat over the spinal canal or directly over the irritated nerve root",
        "Reduce muscle guarding before nerve gliding. Adjunct only."),
    "Ankle Sprain": (
        "Therapeutic Ultrasound (Pulsed - subacute)",
        "3 MHz | Pulsed 20% | 0.5-1.0 W/cm2 | 3-5 min over the injured ligament | Start after 48-72 h | 3-5x/week",
        "Support tissue healing in the subacute stage. Avoid thermal (continuous) doses in the acute stage."),
    "Plantar Fasciitis": (
        "Therapeutic Ultrasound / Shockwave (ESWT)",
        "3 MHz | Pulsed 20% at 0.8 W/cm2 (acute) or Continuous 1.0-1.5 W/cm2 (chronic) | 5 min over the medial calcaneal origin | 3x/week",
        "Reduce pain and improve fascia extensibility before stretching. Consider ESWT for chronic cases (more than 6 months)."),
    "Neck Pain (Cervical Spondylosis)": (
        "Hot Pack / Ultrasound (optional)",
        "3 MHz | Continuous | 1.0 W/cm2 | 5 min over the upper trapezius | 3x/week | Never over the anterior neck (thyroid/carotid)",
        "Reduce muscle tension before mobilization and chin-tuck exercises. Adjunct (weak evidence)."),
    "Rotator Cuff Tendinitis": (
        "Therapeutic Ultrasound (Pulsed to Continuous)",
        "1 MHz (3 MHz in thin patients) | Acute: Pulsed 20% at 0.5-1.0 W/cm2 | Chronic: Continuous 1.0-1.5 W/cm2 | 5-8 min | 3-5x/week",
        "Promote tendon healing and pain relief. Adjunct to progressive strengthening."),
    "Patellofemoral Pain Syndrome": (
        "Ice / Ultrasound not a primary modality",
        "Little evidence for ultrasound here. If used: 3 MHz | Pulsed 20% | 0.5-0.8 W/cm2 | 3-5 min around the patellar retinaculum",
        "Prioritise VMO/hip strengthening, taping and load management."),
    "Guillain-Barre Syndrome": (
        "Not indicated",
        "Avoid: sensory loss and autonomic instability increase burn risk",
        "Focus on positioning, PROM to AAROM and fatigue management."),
    "Multiple Sclerosis": (
        "Not indicated",
        "Avoid thermal modalities including continuous ultrasound: heat can worsen symptoms (Uhthoff phenomenon)",
        "Use cooling strategies and energy conservation."),
    "Rheumatoid Arthritis": (
        "Ultrasound (caution)",
        "Never over acutely inflamed joints | Stable joints only: 3 MHz | Pulsed 20% | 0.5 W/cm2 | 3-5 min per small joint",
        "Paraffin wax and gentle ROM for stiffness. Ultrasound is optional."),
    "Scoliosis": NONE3,
    "Achilles Tendinitis": (
        "Therapeutic Ultrasound (Pulsed)",
        "3 MHz | Pulsed 20% | 0.5-1.0 W/cm2 | 3-5 min along the tendon | 3x/week",
        "Adjunct for pain and tendon healing. Eccentric heel drops are the primary treatment."),
    "Fibromyalgia": (
        "Not indicated",
        "No proven benefit for ultrasound",
        "Use heat, TENS and low-impact aerobic exercise."),
    "Meniscus Tear": (
        "Therapeutic Ultrasound (Optional, subacute)",
        "3 MHz | Pulsed 20% | 0.5-1.0 W/cm2 | 5 min over the joint line | Avoid during acute swelling",
        "Pain relief and healing support. Evidence is limited."),
    "ACL Reconstruction": (
        "Not indicated (early post-op)",
        "Avoid while the wound or swelling is present | Later (6+ weeks, wound healed) optional: 3 MHz | Pulsed 20% | 0.5 W/cm2 over painful graft-site tendon",
        "Use cryotherapy and NMES in the early phase."),
    "Piriformis Syndrome": (
        "Therapeutic Ultrasound (Continuous - deep)",
        "1 MHz | Continuous | 1.0-1.5 W/cm2 | 8-10 min over the piriformis belly, then stretch | 3x/week | Keep the head moving, avoid prolonged dwell over the sciatic nerve",
        "Relax the piriformis to reduce sciatic nerve compression."),
    "Thoracic Outlet Syndrome": (
        "Ultrasound (optional)",
        "3 MHz | Continuous | 1.0 W/cm2 | 5 min over the upper trapezius/pectoralis minor | Never over the anterior neck",
        "Relax muscles before scalene and pectoral stretching. Adjunct only."),
    "De Quervain's Tenosynovitis": (
        "Therapeutic Ultrasound (Pulsed)",
        "3 MHz | Pulsed 20% | 0.5-1.0 W/cm2 | 3-5 min over the first dorsal compartment | 3-5x/week for 2-3 weeks",
        "Reduce inflammation of the APL/EPB tendon sheath alongside thumb spica splinting."),
    "Temporomandibular Joint Dysfunction": (
        "Therapeutic Ultrasound (Pulsed - optional)",
        "3 MHz | Pulsed 20% | 0.5-0.8 W/cm2 | 3-5 min over the masseter/lateral TMJ (small head) | Keep away from the eyes and ear",
        "Reduce pain and muscle tension before Rocabado exercises."),
    "Parkinson's Disease": NONE3,
    "Spinal Cord Injury (Paraplegia)": (
        "Not indicated",
        "Avoid over insensate areas (burn risk)",
        "Focus on transfers, strengthening and skin protection."),
    "Traumatic Brain Injury": NONE3,
    "Peripheral Neuropathy": (
        "Not indicated",
        "Avoid thermal modalities over areas of lost sensation (burn risk)",
        "Balance training, foot care and TENS if painful."),
    "Duchenne Muscular Dystrophy": NONE3,
    "Spina Bifida": (
        "Not indicated",
        "Avoid over insensate skin in children",
        "Gait training, positioning and NMES as per protocol."),
    "Torticollis": (
        "Not indicated",
        "Not used in infants",
        "Gentle SCM stretching, positioning and tummy time."),
    "Osgood-Schlatter Disease": (
        "Contraindicated",
        "Do not apply over the open tibial growth plate",
        "Ice, load management and quadriceps/hamstring flexibility."),
    "Chronic Obstructive Pulmonary Disease": NONE3,
    "Myocardial Infarction (Post-Op)": NONE3,
    "Cystic Fibrosis": (
        "Airway clearance (Flutter / PEP)",
        "Device-based: 10-15 breaths per set, 3-4 sets, followed by huffing and cough | 1-2x/day",
        "Mucus clearance. Ultrasound is not used."),
    "Lymphedema": (
        "Not indicated",
        "Avoid thermal ultrasound over a lymphedematous limb",
        "Complete decongestive therapy: compression, drainage and exercise."),
    "Burn Injury": (
        "Not indicated",
        "Avoid over burned or insensate skin",
        "Pain control, positioning and early ROM to prevent contracture."),
    "Pressure Ulcer": (
        "Therapeutic Ultrasound (Adjunct - low evidence)",
        "3 MHz | Pulsed 20% | 0.5 W/cm2 | 3-5 min on intact periwound skin only | Not over infected or necrotic tissue",
        "Adjunct for wound healing. Offloading and positioning remain the priority."),
    "Shin Splints": (
        "Therapeutic Ultrasound (Optional)",
        "3 MHz | Pulsed 20% | 0.5-1.0 W/cm2 | 3-5 min along the posteromedial tibial border | Avoid if a stress fracture is suspected",
        "Pain relief only. Load management is the primary treatment."),
    "Groin Strain": (
        "Therapeutic Ultrasound (Pulsed - subacute)",
        "1 MHz | Pulsed 20% at 1.0 W/cm2 (subacute) or Continuous 1.0-1.5 W/cm2 (chronic) | 5-8 min over the adductors | 3x/week | Keep away from the genital area",
        "Promote healing and extensibility before progressive adductor loading."),
    "Hamstring Strain": (
        "Therapeutic Ultrasound (Optional, subacute)",
        "1 MHz | Pulsed 20% at 1.0 W/cm2 (subacute) or Continuous 1.0-1.5 W/cm2 (chronic tightness) | 5-8 min | 3x/week | Avoid in the first 48-72 h (hematoma)",
        "Support healing and extensibility before eccentric loading."),
    "Bankart Repair": (
        "Not indicated (early post-op)",
        "Avoid during immobilization and wound healing",
        "Follow the surgeon's protocol: pendulums, then progressive closed-chain work."),
    "Total Knee Arthroplasty": (
        "Not indicated over the prosthesis",
        "Avoid thermal ultrasound over cemented implants and the early post-op knee",
        "Cryotherapy, NMES and early ROM."),
    "Total Hip Arthroplasty": (
        "Not indicated over the prosthesis",
        "Avoid thermal ultrasound over cemented implants and the early post-op hip",
        "Follow hip precautions, abductor strengthening and gait training."),
    "Bicipital Tendinitis": (
        "Therapeutic Ultrasound (Pulsed)",
        "3 MHz | Pulsed 20% (acute) or Continuous 1.0 W/cm2 (chronic) | 0.8-1.0 W/cm2 pulsed | 3-5 min over the bicipital groove | 3x/week",
        "Reduce pain and inflammation. Adjunct to graded strengthening."),
    "Spondylolisthesis": (
        "Hot Pack",
        "15-20 min over the lumbar paraspinals | Ultrasound is not indicated",
        "Reduce muscle guarding before core stabilisation (flexion bias)."),
    "Stenosis (Lumbar)": (
        "Hot Pack",
        "15-20 min over the lumbar paraspinals | Ultrasound is not indicated",
        "Reduce muscle guarding before flexion-based exercises."),
    "Whiplash Injury": (
        "Not indicated (acute phase)",
        "Avoid in the first 72 h | Later (optional): 3 MHz | Continuous | 1.0 W/cm2 | 5 min over the upper trapezius | Never over the anterior neck",
        "Early gentle ROM, deep neck flexor training and posture education."),
}

TENS_CONV = (
    "TENS (Conventional)",
    "80-100 Hz | 100-200 us | Sensory-level intensity | 20-30 min | Daily",
    "Pain relief (gate-control mechanism)")

EST_OVERRIDES = {
    "Carpal Tunnel Syndrome": TENS_CONV,
    "Plantar Fasciitis": TENS_CONV,
    "Rotator Cuff Tendinitis": TENS_CONV,
    "Achilles Tendinitis": TENS_CONV,
    "Piriformis Syndrome": TENS_CONV,
    "De Quervain's Tenosynovitis": TENS_CONV,
    "Temporomandibular Joint Dysfunction": TENS_CONV,
    "Bicipital Tendinitis": TENS_CONV,
}


def find_rule_key(name):
    """يطابق اسم الحالة مع المفتاح (مطابقة تامة ثم مطابقة جزئية)."""
    if not name:
        return None
    n = name.strip().lower()
    for k in US_RULES:
        if k.lower() == n:
            return k
    n_base = n.split('(')[0].strip()
    for k in US_RULES:
        k_low = k.lower()
        k_base = k_low.split('(')[0].strip()
        if k_base and (k_base in n or (n_base and n_base in k_low)):
            return k
    return None


def apply_us_rule(p):
    key = find_rule_key(p.disease_name)
    if not key:
        return False
    p.us_type, p.us_params, p.us_role = US_RULES[key]
    est = EST_OVERRIDES.get(key)
    if est and (p.estim_type or '').strip().lower() in ('us', 'ultrasound', 'ultrasound/other'):
        p.estim_type, p.estim_params, p.estim_role = est
    return True


# ==========================================
# الذكاء الاصطناعي
# ==========================================
def get_ai_protocol(disease_search):
    if not model:
        return None
    try:
        config = genai.types.GenerationConfig(
            temperature=0.7,
            max_output_tokens=3000
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

        response = model.generate_content(prompt, generation_config=config)
        text_response = response.text.strip()

        if text_response.startswith("```json"):
            text_response = text_response[7:]
        elif text_response.startswith("```"):
            text_response = text_response[3:]
        if text_response.endswith("```"):
            text_response = text_response[:-3]

        data = json.loads(text_response.strip())

        if "error" in data:
            return None
        return data

    except Exception as e:
        print(f"AI Error: {e}")
        return None


# ==========================================
# المسارات (Routes)
# ==========================================

@app.route('/admin/update-db-schema')
@admin_required
def update_db_schema():
    msgs = ensure_schema()
    body = "<br>".join(escape(m) for m in msgs) or "Nothing to add, schema is up to date."
    return f"<h1>Schema check done</h1><p>{body}</p><a href='/admin'>Dashboard</a>"


@app.route('/admin/toggle-print/<int:user_id>')
@admin_required
def toggle_print(user_id):
    user = User.query.get_or_404(user_id)
    user.can_print_override = not bool(user.can_print_override)
    db.session.commit()
    status = "Enabled" if user.can_print_override else "Disabled"
    flash(f'Early-print exception {status} for {user.email} (applies to paid users only)', 'info')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/activate/<int:user_id>', methods=['POST'])
@admin_required
def admin_activate(user_id):
    u = User.query.get_or_404(user_id)
    now = datetime.utcnow()
    if u.is_paid:
        u.subscription_end = u.subscription_end + timedelta(days=SUB_DAYS)
    else:
        u.subscribed_at = now
        u.subscription_end = now + timedelta(days=SUB_DAYS)
    db.session.commit()
    flash(f'Subscription active for {u.email} until {u.subscription_end:%Y-%m-%d}', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/cancel-subscription/<int:user_id>', methods=['POST'])
@admin_required
def admin_cancel_subscription(user_id):
    u = User.query.get_or_404(user_id)
    u.subscription_end = None
    u.subscribed_at = None
    u.can_print_override = False
    db.session.commit()
    flash(f'Subscription cancelled for {u.email}', 'warning')
    return redirect(url_for('admin_dashboard'))


@app.route('/', methods=['GET', 'POST'])
def home():
    if not current_user.is_authenticated:
        return render_template('landing.html')

    if not current_user.has_access:
        return redirect(url_for('subscription_expired'))

    days_left = "Unlimited (Admin)" if current_user.is_admin else current_user.days_left

    result = None
    raw_query = request.args.get('disease') or request.form.get('disease')

    if raw_query:
        clean_query = " ".join(raw_query.strip().split())
        term = f"%{clean_query}%"

        result = Protocol.query.filter(
            (Protocol.disease_name.ilike(term)) |
            (Protocol.keywords.ilike(term))
        ).first()

        if not result:
            result = get_ai_protocol(clean_query)

    return render_template('index.html', result=result, user=current_user, days_left=days_left)


@app.route('/subscription')
def subscription_expired():
    return render_template('subscribe.html')


@app.route('/terms')
def terms():
    return (
        "<div style='max-width:760px;margin:40px auto;font-family:sans-serif;line-height:1.8;direction:rtl'>"
        "<h1>الشروط والأحكام - Physio Expert Pro</h1>"
        "<p>المحتوى المعروض على المنصة مخصص للأغراض التعليمية والمرجعية لأخصائيي وطلبة العلاج الطبيعي، ولا يُغني عن التقييم الإكلينيكي المباشر للمريض.</p>"
        "<p>تُتاح تجربة مجانية لمدة 30 يومًا بدون طباعة، ويُفعّل الاشتراك الشهري بقيمة 150 جنيهًا عبر InstaPay مع إمكانية الإلغاء والاسترداد خلال 24 ساعة من التفعيل.</p>"
        "<a href='/'>العودة للرئيسية</a></div>"
    )


@app.route('/privacy')
def privacy():
    return (
        "<div style='max-width:760px;margin:40px auto;font-family:sans-serif;line-height:1.8;direction:rtl'>"
        "<h1>سياسة الخصوصية - Physio Expert Pro</h1>"
        "<p>نستخدم البريد الإلكتروني وكلمة المرور المشفرة لإدارة حسابك واشتراكك فقط، ولا نشارك بياناتك الشخصية مع أي طرف ثالث.</p>"
        "<a href='/'>العودة للرئيسية</a></div>"
    )


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
        if 'ex_intensity' in request.form:
            p.ex_intensity = request.form.get('ex_intensity')
        if 'ex_progression' in request.form:
            p.ex_progression = request.form.get('ex_progression')
        if 'evidence_level' in request.form:
            p.evidence_level = request.form.get('evidence_level')
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
        flash('No file selected', 'danger')
        return redirect(url_for('admin_dashboard'))

    file = request.files['excel_file']
    if file.filename == '':
        flash('No selected file', 'warning')
        return redirect(url_for('admin_dashboard'))

    try:
        if file.filename.endswith('.csv'):
            df = pd.read_csv(file)
        else:
            df = pd.read_excel(file)

        df.columns = df.columns.str.strip()

        def get_val(row, col_name):
            val = row.get(col_name)
            return "" if (pd.isna(val) or str(val).strip() == 'nan') else str(val).strip()

        updated = 0
        created = 0

        for _, row in df.iterrows():
            d_name = get_val(row, 'disease_name')
            if not d_name:
                continue

            p = Protocol.query.filter_by(disease_name=d_name).first()
            if not p:
                p = Protocol(disease_name=d_name)
                db.session.add(p)
                created += 1
            else:
                updated += 1

            p.category = get_val(row, 'category') or 'General'
            p.keywords = get_val(row, 'keywords')
            p.description = get_val(row, 'description')
            p.source_ref = get_val(row, 'source_ref')

            p.estim_params = get_val(row, 'estim_params')
            p.estim_type = get_val(row, 'estim_type') or "Electrical Stimulation"
            p.us_params = get_val(row, 'us_params')
            p.us_type = get_val(row, 'us_type') or "Ultrasound"

            p.exercises_list = get_val(row, 'exercises_list')
            p.exercises_role = get_val(row, 'exercises_role')

            p.ex_frequency = get_val(row, 'ex_frequency')
            p.ex_intensity = get_val(row, 'ex_intensity')
            p.ex_progression = get_val(row, 'ex_progression')
            p.evidence_level = get_val(row, 'evidence_level')

            if not p.us_params:
                apply_us_rule(p)

        db.session.commit()
        flash(f'Done! Created {created}, Updated {updated} protocols.', 'success')

    except Exception as e:
        db.session.rollback()
        print(f"Excel Error: {e}")
        flash(f'Error: {str(e)}', 'danger')

    return redirect(url_for('admin_dashboard'))


@app.route('/admin/delete/<int:id>')
@admin_required
def delete_protocol(id):
    p = Protocol.query.get_or_404(id)
    db.session.delete(p)
    db.session.commit()
    flash('Protocol Deleted', 'warning')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/fix-ultrasound')
@admin_required
def fix_ultrasound():
    updated, unmatched = 0, []
    for p in Protocol.query.all():
        if apply_us_rule(p):
            updated += 1
        else:
            unmatched.append(p.disease_name)
    db.session.commit()
    un = "<br>".join(escape(n) for n in unmatched) or "None"
    return (f"<h1>Ultrasound parameters updated for {updated} protocols</h1>"
            f"<h3>Not matched (edit manually or send me the names):</h3><p>{un}</p>"
            f"<a href='/admin'>Dashboard</a>")


# ---------- استيراد ملف JSON ----------
def _format_exercises_html(ex_data):
    html = ""
    for p_key in ["phase_1", "phase_2", "phase_3"]:
        phase = ex_data.get(p_key)
        if phase:
            html += f"<h4>{phase.get('name', p_key.title())}: {phase.get('goal', '')}</h4><ul>"
            for ex in phase.get('exercises', []):
                html += (f"<li><b>{ex.get('name')}</b>: {ex.get('instructions')} "
                         f"<i>({ex.get('dosage')})</i></li>")
            html += "</ul><hr>"
    return html


def _format_notes(notes_data):
    if not notes_data:
        return ""
    return (f"Diagnosis: {notes_data.get('assessment_diagnosis', '')}\n\n"
            f"Manual Therapy: {notes_data.get('manual_therapy', '')}\n\n"
            f"Precautions: {notes_data.get('precautions', '')}")


@app.route('/admin/import-generated-json')
@admin_required
def import_generated_json():
    json_filename = os.environ.get('PROTOCOLS_JSON_FILE', 'final_physio_protocols.json')
    file_path = os.path.join(app.root_path, json_filename)
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data_list = json.load(f)

        added_count = 0
        updated_count = 0

        for item in data_list:
            d_name = item.get('condition_name')
            if not d_name:
                continue
            existing = Protocol.query.filter_by(disease_name=d_name).first()

            if existing:
                p = existing
                updated_count += 1
            else:
                p = Protocol()
                added_count += 1

            p.disease_name = d_name
            p.category = item.get('category', 'General')
            p.description = item.get('clinical_presentation', {}).get('definition', '')
            p.keywords = f"{d_name}, {p.category}, {p.description[:50]}"

            electro_list = item.get('electrotherapy') or [{}]
            electro = electro_list[0]
            p.estim_type = electro.get('type', 'TENS/FES')
            p.estim_params = electro.get('parameters', 'See notes')
            p.estim_role = electro.get('goal', 'Pain relief')

            p.exercises_list = _format_exercises_html(item.get('therapeutic_exercises', {}))
            p.exercises_role = "Rehabilitation Progression"
            p.source_ref = item.get('scientific_reference', 'Kisner & Colby')
            p.notes = _format_notes(item.get('clinical_notes', {}))

            if not apply_us_rule(p) and not existing:
                p.us_type = "Ultrasound"
                p.us_params = ""

            if not existing:
                db.session.add(p)

        db.session.commit()
        flash(f'Successfully Imported! Added: {added_count}, Updated: {updated_count}', 'success')
        return redirect(url_for('admin_dashboard'))

    except FileNotFoundError:
        return f"<h1>Error: File '{escape(json_filename)}' not found in {escape(app.root_path)}.</h1>"
    except Exception as e:
        db.session.rollback()
        return f"<h1>Error: {escape(str(e))}</h1>"


@app.route('/admin/update-content')
@admin_required
def update_content():
    return redirect(url_for('import_generated_json'))


# ---------- تسجيل الدخول والتسجيل ----------
@app.route('/login', methods=['GET', 'POST'])
def login():
    disease_q = request.args.get('disease') or request.form.get('disease') or ''
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form['email']).first()
        if user and check_password_hash(user.password, request.form['password']):
            login_user(user)
            if disease_q:
                return redirect(url_for('home', disease=disease_q))
            return redirect(url_for('home'))
        else:
            flash('Login Failed. Check email/password', 'danger')
    return render_template('login.html', disease=disease_q)


@app.route('/forgot-password')
def forgot_password():
    return render_template('forgot_password.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    disease_q = request.args.get('disease') or request.form.get('disease') or ''
    if request.method == 'POST':
        try:
            pw = generate_password_hash(request.form['password'], method='pbkdf2:sha256')
            new_user = User(email=request.form['email'], password=pw)
            db.session.add(new_user)
            db.session.commit()
            login_user(new_user)
            if disease_q:
                return redirect(url_for('home', disease=disease_q))
            return redirect(url_for('home'))
        except Exception:
            db.session.rollback()
            flash('Email already exists', 'danger')
    return render_template('register.html', disease=disease_q)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


if __name__ == '__main__':
    app.run(debug=False)
