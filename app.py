import os
import re
import math
import base64
import pandas as pd
from functools import wraps
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, abort, session
from sqlalchemy import text, inspect
from html import escape as html_escape
from html.parser import HTMLParser
from markupsafe import escape
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

# ==========================================
# سياسة الاشتراك (غيّر الأرقام من هنا فقط)
# ==========================================
TRIAL_DAYS = 30          # التجربة المجانية
SUB_DAYS = 30            # مدة الاشتراك الشهري
PRINT_WAIT_HOURS = 24    # الطباعة تتفتح بعد أول 24 ساعة من الاشتراك المدفوع

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

from sqlalchemy.engine import make_url

db_url = os.environ.get('DATABASE_URL', 'sqlite:///physio.db')

if db_url.startswith(('postgres://', 'postgresql://', 'postgresql+psycopg://', 'postgresql+psycopg2://')):
    parsed_url = make_url(db_url)
    db_url = parsed_url.set(
        drivername='postgresql+psycopg2'
    ).render_as_string(hide_password=False)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
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
    # class على <p> مسموح (علشان phase-goal بتاع أهداف المراحل). باقي الـ attributes ممنوعة.
    return nh3.clean(
        value or "",
        tags={"b", "strong", "i", "em", "u", "p", "br", "ul", "ol", "li", "h4", "h5", "hr"},
        attributes={"p": {"class"}},
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
    "Scoliosis": (
        "None", "None",
        "None"),
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


US_RULES.update({
    "Quadriceps Muscle Strain": (
        "Therapeutic Ultrasound (Optional, subacute)",
        "1 MHz | Pulsed 20% at 1.0 W/cm2 (subacute) or Continuous 1.0-1.5 W/cm2 (chronic tightness) | 5-8 min | 3x/week | Avoid in the first 48-72 h (hematoma)",
        "Support healing and extensibility before progressive loading."),
    "Osteoporosis": (
        "Not indicated",
        "Avoid thermal ultrasound over the spine and fragile bone sites",
        "Weight-bearing and resistance exercise, balance training and posture education."),
    "Post-COVID-19 Rehabilitation": NONE3,
    "Stress Fracture (Post-Immobilization)": (
        "Not indicated",
        "Avoid conventional therapeutic ultrasound over an unhealed stress fracture",
        "Graded return to loading as cleared by the physician."),
    "Anterior Shoulder Instability": (
        "Not indicated",
        "No role in stabilisation rehab; avoid thermal doses over an irritable joint",
        "Rotator cuff and scapular stabilisation, proprioception and graded return to activity."),
    "Pulmonary Fibrosis": NONE3,
    "Cervical Radiculopathy": (
        "Ultrasound (optional)",
        "3 MHz | Continuous | 1.0 W/cm2 | 5 min over the upper trapezius/levator scapulae | Never over the anterior neck or directly over the irritated nerve root",
        "Relax muscle guarding before mobilization and nerve gliding. Adjunct only; evidence is weak."),
    "Fall Risk in Older Adults": NONE3,
    "Greater Trochanteric Pain Syndrome": (
        "Therapeutic Ultrasound (Optional)",
        "1 MHz | Pulsed 20% | 1.0 W/cm2 | 5-8 min over the greater trochanter | 3x/week",
        "Short-term pain relief. Load management and hip abductor strengthening are the primary treatment."),
    "Hip Osteoarthritis": (
        "Not routinely indicated",
        "Limited evidence and the joint is deep | Avoid over a hip prosthesis",
        "Exercise therapy, education and weight management."),
    "Lumbar Disc Herniation": (
        "Hot Pack / Ultrasound (optional)",
        "1 MHz | Continuous | 1.0-1.5 W/cm2 | 5-8 min over the paraspinal muscles | 3x/week | Not over the spinal canal | Avoid with progressive neurological deficit",
        "Reduce muscle guarding before directional-preference exercises. Adjunct only."),
    "Medial Epicondylitis": (
        "Therapeutic Ultrasound (Pulsed)",
        "3 MHz | Pulsed 20% (acute) or Continuous 1.0 W/cm2 (chronic) | 0.8-1.0 W/cm2 pulsed | 5 min over the common flexor origin | Keep away from the ulnar nerve at the medial elbow | 3x/week",
        "Stimulate tendon repair and reduce pain. Adjunct to progressive loading."),
    "Patellar Tendinopathy (Jumper's Knee)": (
        "Therapeutic Ultrasound (Pulsed)",
        "3 MHz | Pulsed 20% | 0.5-1.0 W/cm2 | 3-5 min over the inferior pole of the patella | 3x/week",
        "Adjunct for pain. Progressive tendon loading (isometric to heavy slow resistance) is the primary treatment."),
    "Post-Coronary Artery Bypass Grafting (CABG)": NONE3,
    "Rotator Cuff Tear (Partial)": (
        "Therapeutic Ultrasound (Optional adjunct)",
        "3 MHz (1 MHz if deep) | Pulsed 20% | 0.5-1.0 W/cm2 | 5 min over the supraspinatus tendon | 3x/week",
        "Pain relief only. Evidence for healing a tear is limited; progressive strengthening is the primary treatment."),
    "Sacroiliac Joint Dysfunction": (
        "Therapeutic Ultrasound (Optional)",
        "1 MHz | Continuous | 1.0-1.5 W/cm2 | 5-8 min over the SI region and gluteal muscles | 3x/week | Avoid in pregnancy",
        "Reduce muscle guarding before stabilisation exercises. Adjunct only."),
    "Subacromial Impingement": (
        "Therapeutic Ultrasound (Pulsed)",
        "1 MHz (3 MHz if thin) | Pulsed 20% | 0.5-1.0 W/cm2 | 5 min around the subacromial space | 3x/week",
        "Adjunct for pain relief. Scapular control and cuff strengthening are the primary treatment."),
    "Supraspinatus Tendinopathy": (
        "Therapeutic Ultrasound (Pulsed to Continuous)",
        "1 MHz (3 MHz in thin patients) | Acute: Pulsed 20% at 0.5-1.0 W/cm2 | Chronic: Continuous 1.0-1.5 W/cm2 | 5-8 min | 3x/week",
        "Promote tendon healing and pain relief. Adjunct to progressive loading."),
    "Developmental Delay": (
        "Not indicated",
        "Not used in infants and young children",
        "Handling, positioning, play-based developmental activities and family education."),
    "Vestibular Hypofunction": NONE3,
    "Chronic Heart Failure (Stable)": NONE3,
})

# بدائل الكهرباء للحالات اللي كان فيها Ultrasound مكتوب غلط في خانة الكهرباء
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


def _norm_name(s):
    s = (s or '').strip().lower()
    for a, b in (('\u2019', "'"), ('\u2018', "'"), ('\u2013', '-'), ('\u2014', '-'), ('\u00e9', 'e')):
        s = s.replace(a, b)
    return s


def find_rule_key(name):
    """يطابق اسم الحالة مع المفتاح (مطابقة تامة ثم مطابقة جزئية)."""
    n = _norm_name(name)
    if not n:
        return None
    for k in US_RULES:
        if _norm_name(k) == n:
            return k
    n_base = n.split('(')[0].strip()
    for k in US_RULES:
        k_low = _norm_name(k)
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




# --- 2. الجداول (Models) ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    subscription_end = db.Column(db.DateTime, nullable=True)
    # تاريخ بداية الاشتراك المدفوع (لحساب أول 24 ساعة قبل الطباعة)
    subscribed_at = db.Column(db.DateTime, nullable=True)
    # عمود can_print القديم بقى "استثناء يدوي من الأدمن" للمشتركين فقط
    can_print_override = db.Column('can_print', db.Boolean, default=False)

    @property
    def trial_end(self):
        return (self.created_at or datetime.utcnow()) + timedelta(days=TRIAL_DAYS)

    @property
    def is_paid(self):
        return bool(
            self.subscription_end
            and self.subscription_end > datetime.utcnow()
        )

    @property
    def in_trial(self):
        return (
            not self.is_paid
            and datetime.utcnow() < self.trial_end
        )

    @property
    def has_access(self):
        return bool(self.is_admin or self.is_paid or self.in_trial)

    @property
    def days_left(self):
        if self.is_admin:
            return None

        end = self.subscription_end if self.is_paid else self.trial_end
        remaining = (end - datetime.utcnow()).total_seconds()

        return max(int((remaining + 86399) // 86400), 0)

    @property
    def can_print(self):
        """الطباعة: للأدمن دايمًا. للمشترك بعد 24 ساعة. التجربة المجانية: ممنوعة."""
        if self.is_admin:
            return True
        if not self.is_paid:
            return False
        if self.can_print_override:
            return True
        if self.subscribed_at is None:      # مشتركين قدام قبل إضافة التاريخ
            return True
        return datetime.utcnow() >= self.subscribed_at + timedelta(hours=PRINT_WAIT_HOURS)

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

# ==========================================
# تحديث الأعمدة الناقصة تلقائيًا عند التشغيل (بدون مسح بيانات)
# ==========================================
def ensure_columns():
    try:
        insp = inspect(db.engine)
        wanted = {
            'user': [('can_print', 'BOOLEAN DEFAULT FALSE'), ('subscribed_at', 'TIMESTAMP')],
            'protocol': [('video_link', 'TEXT'), ('notes', 'TEXT')],
        }
        for table, cols in wanted.items():
            existing = {c['name'] for c in insp.get_columns(table)}
            for name, ctype in cols:
                if name in existing:
                    continue
                try:
                    with db.engine.begin() as conn:
                        conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN {name} {ctype}'))
                    print(f"schema: added {table}.{name}")
                except Exception as e:
                    print(f"schema: {table}.{name}: {e}")
    except Exception as e:
        print(f"schema check failed: {e}")

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

# زر "Early print": استثناء يدوي للمشتركين فقط (قبل مرور 24 ساعة)
@app.route('/admin/toggle-print/<int:user_id>', methods=['POST'])
@admin_required
def toggle_print(user_id):
    user = User.query.get_or_404(user_id)
    user.can_print_override = not bool(user.can_print_override)
    db.session.commit()
    flash(f"Early-print exception updated for {user.email} (applies to paid users only).", "info")
    return redirect(url_for("admin_dashboard"))


# ---------- تفعيل / إلغاء الاشتراك (بعد تحويل InstaPay) ----------
@app.route('/admin/activate/<int:user_id>', methods=['POST'])
@admin_required
def admin_activate(user_id):
    u = User.query.get_or_404(user_id)
    now = datetime.utcnow()
    if u.is_paid:
        # تجديد وهو لسه مشترك: نمدد من تاريخ الانتهاء ومنلمسش تاريخ بداية الاشتراك
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


# ---------- تصحيح معاملات الـ Ultrasound في جدول البروتوكولات القديم ----------
@app.route('/admin/fix-ultrasound', methods=['POST'])
@admin_required
def fix_ultrasound():
    updated, unmatched = 0, []
    for p in Protocol.query.all():
        if apply_us_rule(p):
            updated += 1
        else:
            unmatched.append(p.disease_name)
    db.session.commit()
    msg = f'Ultrasound parameters updated for {updated} protocols.'
    if unmatched:
        msg += ' Not matched: ' + ', '.join(unmatched[:15]) + (' ...' if len(unmatched) > 15 else '')
    flash(msg, 'success' if not unmatched else 'warning')
    return redirect(url_for('admin_dashboard'))


# ==========================================
# Clinical Library: search + presentation adapter
# ==========================================
def _clinical_text(value):
    return " ".join(str(value or "").strip().casefold().split())


def _clinical_condition_score(condition, query):
    """Match canonical names, aliases, and preserved source names in EN/AR."""
    q = _clinical_text(query)
    if not q:
        return 0
    names = []
    canonical = condition.canonical_name or {}
    if isinstance(canonical, dict):
        names.extend([canonical.get("en", ""), canonical.get("ar", "")])
    aliases = condition.aliases or []
    if isinstance(aliases, list):
        for alias in aliases:
            if isinstance(alias, dict):
                names.extend([alias.get("en", ""), alias.get("ar", "")])
    source_records = condition.source_records or []
    if isinstance(source_records, list):
        names.extend(r.get("original_name", "") for r in source_records if isinstance(r, dict))

    best = 0
    for name in names:
        n = _clinical_text(name)
        if not n:
            continue
        if q == n:
            best = max(best, 100)
        elif q in n:
            best = max(best, 80)
        elif n in q:
            best = max(best, 65)
    return best


def _clinical_protocol_result(condition, protocol):
    """Adapt the normalized clinical tables to the existing index.html contract."""
    Models = CLINICAL_MODELS
    Phase = Models["ClinicalProtocolPhase"]
    Exercise = Models["ClinicalExercise"]
    PhaseExercise = Models["ClinicalPhaseExercise"]

    content = protocol.content_en or {}
    presentation = content.get("clinical_presentation") or {}
    notes = content.get("clinical_notes") or {}
    summary = content.get("summary") or {}
    electro = content.get("electrotherapy") or []
    ultrasound = content.get("ultrasound") or {}

    # Escape source strings before creating the small HTML fragment consumed by the template.
    phase_html = []
    phases = (Phase.query.filter_by(protocol_id=protocol.protocol_id)
              .order_by(Phase.sort_order.asc()).all())
    for phase in phases:
        phase_content = phase.content_en or {}
        phase_name = html_escape(str(phase_content.get("name") or phase.phase_key or "Phase"))
        phase_goal = html_escape(str(phase_content.get("goal") or ""))
        phase_html.append(f"<h4>{phase_name}{(': ' + phase_goal) if phase_goal else ''}</h4><ul>")
        linked = (db.session.query(Exercise, PhaseExercise)
                  .join(PhaseExercise, PhaseExercise.exercise_id == Exercise.exercise_id)
                  .filter(PhaseExercise.phase_id == phase.phase_id)
                  .order_by(PhaseExercise.sort_order.asc()).all())
        for exercise, link in linked:
            ex = exercise.content_en or {}
            ex_name = html_escape(str(ex.get("name") or "Exercise"))
            instructions = html_escape(str(ex.get("instructions") or ""))
            dosage = html_escape(str(ex.get("dosage") or ""))
            phase_html.append("<li><b>" + ex_name + "</b>" +
                              ("<span>" + instructions + "</span>" if instructions else "") +
                              ("<i>" + dosage + "</i>" if dosage else "") + "</li>")
        phase_html.append("</ul>")

    electro_types, electro_params, electro_goals = [], [], []
    for item in electro if isinstance(electro, list) else []:
        if not isinstance(item, dict):
            continue
        if item.get("type"):
            electro_types.append(str(item["type"]))
        if item.get("parameters"):
            electro_params.append(str(item["parameters"]))
        if item.get("placement_guide"):
            electro_params.append("Placement: " + str(item["placement_guide"]))
        if item.get("goal"):
            electro_goals.append(str(item["goal"]))

    ultrasound_regimens = ultrasound.get("regimens") or []
    ultrasound_lines = []
    if ultrasound.get("summary"):
        ultrasound_lines.append(str(ultrasound["summary"]))
    for regimen in ultrasound_regimens:
        if isinstance(regimen, dict):
            ultrasound_lines.append(" | ".join(f"{k}: {v}" for k, v in regimen.items() if v not in (None, "")))
        else:
            ultrasound_lines.append(str(regimen))
    ultrasound_lines.extend(str(x) for x in (ultrasound.get("cautions") or []))

    canonical = condition.canonical_name or {}
    display_name = (canonical.get("ar") or canonical.get("en") or protocol.source_condition_name
                    if isinstance(canonical, dict) else protocol.source_condition_name)
    short_summary = summary.get("definition_short") or ""
    description = presentation.get("definition") or short_summary
    notes_text = "\n\n".join(part for part in [
        "Diagnosis: " + str(notes.get("assessment_diagnosis", "")) if notes.get("assessment_diagnosis") else "",
        "Manual Therapy: " + str(notes.get("manual_therapy", "")) if notes.get("manual_therapy") else "",
        "Precautions: " + str(notes.get("precautions", "")) if notes.get("precautions") else "",
        "Ultrasound cautions: " + "; ".join(str(x) for x in (ultrasound.get("cautions") or [])) if ultrasound.get("cautions") else "",
    ] if part)

    return {
        "disease_name": display_name,
        "category": protocol.specialty or condition.specialty or "General",
        "keywords": ", ".join([display_name, protocol.source_condition_name or "", protocol.specialty or ""]),
        "description": description,
        "estim_type": ", ".join(electro_types),
        "estim_params": "\n".join(electro_params),
        "estim_role": "\n".join(electro_goals),
        "us_type": ultrasound.get("status") or ("Ultrasound" if ultrasound else ""),
        "us_params": "\n".join(ultrasound_lines),
        "us_role": ultrasound.get("goal") or "",
        "exercises_list": "".join(phase_html),
        "exercises_role": "Progressive rehabilitation phases",
        "ex_frequency": "",
        "ex_intensity": "",
        "ex_progression": "",
        "evidence_level": "",
        "source_ref": content.get("scientific_reference") or "",
        "electrode_image": "",
        "video_link": "",
        "notes": notes_text,
        "clinical_warning": "هذا البروتوكول قيد المراجعة ولم يحصل على اعتماد سريري. يجب مراجعته وتكييفه مع تقييم المريض والإرشادات المعتمدة قبل الاستخدام.",
        "clinical_status": protocol.clinical_approval_status or "not_approved",
        "is_clinical_library": True,
        "source_record_id": protocol.source_record_id,
    }


def find_clinical_protocol(query):
    """Search the 80-item registry in both languages and resolve via condition_id."""
    Models = CLINICAL_MODELS
    conditions = Models["ClinicalCondition"].query.all()
    scored = [( _clinical_condition_score(c, query), c) for c in conditions]
    scored = [(score, condition) for score, condition in scored if score > 0]
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)

    # Try the best-matching condition first. For consolidated diagnoses, prefer
    # the source protocol whose original name best matches the user's wording.
    best_score, condition = scored[0]
    protocols = Models["ClinicalProtocol"].query.filter_by(condition_id=condition.condition_id).all()
    if not protocols:
        return None
    q = _clinical_text(query)
    protocols.sort(key=lambda p: (100 if q == _clinical_text(p.source_condition_name) else
                                  80 if q in _clinical_text(p.source_condition_name) else 0), reverse=True)
    return _clinical_protocol_result(condition, protocols[0])


def search_protocol(q):
    """أفضل نتيجة: اسم مطابق، ثم كلمة مفتاحية مطابقة، ثم يبدأ بالكلمة، ثم يحتويها."""
    ql = _norm_name(q)
    rows = Protocol.query.filter(
        (Protocol.disease_name.ilike(f"%{q}%")) | (Protocol.keywords.ilike(f"%{q}%"))
    ).all()
    if not rows:
        return None

    def rank(p):
        n = _norm_name(p.disease_name)
        kws = [_norm_name(k) for k in (p.keywords or '').split(',')]
        if n == ql:
            return 0
        if ql in kws:
            return 1
        if n.startswith(ql):
            return 2
        if ql in n:
            return 3
        return 4
    rows.sort(key=lambda p: (rank(p), len(p.disease_name or '')))
    return rows[0]



@app.route('/', methods=['GET', 'POST'])
def home():
    # الزائر غير المسجل يشوف صفحة الهبوط
    if not current_user.is_authenticated:
        return render_template('landing.html')

    if not current_user.has_access:
        return redirect(url_for('subscription_expired'))

    days_left = "Unlimited (Admin)" if current_user.is_admin else current_user.days_left
    result = None
    raw_query = request.args.get('disease') or request.form.get('disease')

    if raw_query:
        clean_query = " ".join(raw_query.strip().split())

        # 1) المكتبة السريرية الجديدة: canonical names + aliases EN/AR.
        try:
            result = find_clinical_protocol(clean_query)
        except Exception as exc:
            # Keep the legacy system available, but expose the failure in logs.
            app.logger.exception("Clinical library search failed: %s", exc)
            result = None

        # 2) Legacy protocol table remains as a fallback (الأقرب للاسم أولًا).
        if not result:
            result = search_protocol(clean_query)

        # 3) Preserve the existing AI fallback for terms absent from both libraries.
        if not result:
            result = get_ai_protocol(clean_query)

        if result and not isinstance(result, dict):
            result.exercises_list = sanitize_rich_html(result.exercises_list or "")
        elif isinstance(result, dict) and not result.get("is_clinical_library"):
            result["exercises_list"] = sanitize_rich_html(result.get("exercises_list", ""))

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

# ==========================================
# قالب الإكسيل (تحميل + استيراد) - صف لكل تمرين
# ==========================================
COND_COLS = ['disease_name', 'category', 'keywords', 'description',
             'estim_type', 'estim_params', 'estim_role',
             'us_type', 'us_params', 'us_role',
             'ex_frequency', 'ex_intensity', 'ex_progression', 'exercises_role',
             'evidence_level', 'source_ref',
             'diagnosis', 'manual_therapy', 'precautions', 'other_notes', 'action']
EX_COLS = ['disease_name', 'phase', 'phase_goal', 'exercise', 'instructions', 'dosage']
COND_WIDTHS = {'disease_name': 30, 'category': 16, 'keywords': 28, 'description': 55,
               'estim_type': 20, 'estim_params': 38, 'estim_role': 28,
               'us_type': 26, 'us_params': 50, 'us_role': 40,
               'ex_frequency': 14, 'ex_intensity': 16, 'ex_progression': 30, 'exercises_role': 30,
               'evidence_level': 14, 'source_ref': 28,
               'diagnosis': 45, 'manual_therapy': 45, 'precautions': 45, 'other_notes': 35, 'action': 12}
EX_WIDTHS = {'disease_name': 30, 'phase': 26, 'phase_goal': 30, 'exercise': 28,
             'instructions': 60, 'dosage': 22}
NOTE_HEADS = [('Diagnosis', 'diagnosis'), ('Manual Therapy', 'manual_therapy'),
              ('Precautions', 'precautions')]


def split_notes(t):
    """يقسم نص الملاحظات إلى Diagnosis / Manual Therapy / Precautions / باقي."""
    t = t or ''
    found = []
    for label, key in NOTE_HEADS:
        m = re.search(r'(^|\n)\s*' + re.escape(label) + r'\s*:', t, re.I)
        if m:
            found.append((m.start(), m.end(), key))
    out = {'diagnosis': '', 'manual_therapy': '', 'precautions': '', 'other_notes': ''}
    if not found:
        out['other_notes'] = t.strip()
        return out
    found.sort()
    out['other_notes'] = t[:found[0][0]].strip()
    for i, (s, e, key) in enumerate(found):
        stop = found[i + 1][0] if i + 1 < len(found) else len(t)
        out[key] = t[e:stop].strip()
    return out


def join_notes(diagnosis, manual, precautions, other):
    parts = []
    if other:
        parts.append(other)
    if diagnosis:
        parts.append(f"Diagnosis: {diagnosis}")
    if manual:
        parts.append(f"Manual Therapy: {manual}")
    if precautions:
        parts.append(f"Precautions: {precautions}")
    return "\n\n".join(parts)


class _ExParser(HTMLParser):
    """يحوّل HTML التمارين (h4 + li) إلى صفوف."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.phase = ''
        self.goal = ''
        self._h4 = None
        self._goal = None
        self._li = None
        self._in = None

    def handle_starttag(self, tag, attrs):
        if tag == 'h4':
            self._h4 = ''
        elif tag == 'p' and 'phase-goal' in (dict(attrs).get('class') or ''):
            self._goal = ''
        elif tag == 'li':
            self._li = {'b': '', 'i': '', 't': ''}
        elif tag in ('b', 'i') and self._li is not None:
            self._in = tag

    def handle_endtag(self, tag):
        if tag == 'h4' and self._h4 is not None:
            txt = self._h4.strip()
            self._h4 = None
            if ': ' in txt:
                self.phase, self.goal = [x.strip() for x in txt.split(': ', 1)]
            else:
                self.phase, self.goal = txt, ''
        elif tag == 'p' and self._goal is not None:
            self.goal = re.sub(r'^\s*Goal:\s*', '', self._goal.strip())
            self._goal = None
        elif tag in ('b', 'i'):
            self._in = None
        elif tag == 'li' and self._li is not None:
            li, self._li = self._li, None
            instr = re.sub(r'^\s*:\s*', '', li['t']).strip()
            dose = re.sub(r'^\(|\)$', '', li['i'].strip()).strip()
            self.rows.append((self.phase, self.goal, li['b'].strip(), instr, dose))

    def handle_data(self, data):
        if self._h4 is not None:
            self._h4 += data
        elif self._goal is not None:
            self._goal += data
        elif self._li is not None:
            if self._in == 'b':
                self._li['b'] += data
            elif self._in == 'i':
                self._li['i'] += data
            else:
                self._li['t'] += data


def exercises_to_rows(html_text):
    """يرجّع صفوف (phase, goal, exercise, instructions, dosage)."""
    s = html_text or ''
    if not s.strip():
        return []
    if '<li' in s.lower():
        p = _ExParser()
        p.feed(s)
        return [(ph or 'Phase 1', goal, n, i, d) for ph, goal, n, i, d in p.rows if n]
    if '<' in s:
        txt = re.sub(r'<br\s*/?>', '\n', s, flags=re.I)
        txt = re.sub(r'<[^>]+>', '', txt).strip()
        return [('Phase 1', '', 'Exercise program', txt, '')] if txt else []
    if '\n' in s or len(s) > 200:
        return [('Phase 1', '', 'Exercise program', s.strip(), '')]
    return [('Phase 1', '', x.strip(), '', '') for x in s.split(',') if x.strip()]


def rows_to_exercises_html(rows):
    """صفوف الإكسيل -> نفس شكل HTML بتاع ملف JSON (مراحل + تمارين + جرعات)."""
    order, groups = [], {}
    for r in rows:
        key = r.get('phase') or 'Exercises'
        if key not in groups:
            groups[key] = {'goal': '', 'items': []}
            order.append(key)
        if r.get('phase_goal') and not groups[key]['goal']:
            groups[key]['goal'] = r['phase_goal']
        groups[key]['items'].append(r)
    html = ""
    for key in order:
        g = groups[key]
        html += f"<h4>{escape(key)}</h4>"
        if g['goal']:
            html += f'<p class="phase-goal">Goal: {escape(g["goal"])}</p>'
        html += "<ul>"
        for r in g['items']:
            html += f"<li><b>{escape(r['exercise'])}</b>"
            if r.get('instructions'):
                html += f": {escape(r['instructions'])}"
            if r.get('dosage'):
                html += f" <i>({escape(r['dosage'])})</i>"
            html += "</li>"
        html += "</ul><hr>"
    return html


def build_template_workbook(protocols):
    """يبني ملف إكسيل جاهز للتعديل من بيانات الموقع الحالية."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    font = Font(name='Arial', size=10)
    head_font = Font(name='Arial', size=10, bold=True, color='FFFFFF')
    head_fill = PatternFill('solid', start_color='1E3C72')
    wrap = Alignment(wrap_text=True, vertical='top')

    wb = Workbook()

    # ---------- Guide ----------
    g = wb.active
    g.title = 'Guide'
    g.sheet_view.rightToLeft = True
    lines = [
        ("دليل ملء الملف", True),
        ("1) ورقة Conditions: صف لكل حالة (التعريف، الكهرباء، الملاحظات، المرجع...).", False),
        ("2) ورقة Exercises: صف لكل تمرين. لإضافة تمرين جديد أضف صف جديد واكتب اسم الحالة (disease_name) بالظبط زي ما هو.", False),
        ("3) المراحل: اكتب نفس اسم المرحلة في كل تمارينها (مثال: Phase 1: Freezing) وهتظهر في الموقع كأكورديون.", False),
        ("4) الخلية الفاضية في Conditions = الموقع يحتفظ بالقيمة القديمة. الاستثناء: خانات الملاحظات (diagnosis و manual_therapy و precautions و other_notes) بتتجمع وتحل محل الملاحظات القديمة.", False),
        ("5) لو الحالة ليها صفوف في Exercises، قائمة تمارينها القديمة بتتبدل بالكامل بالصفوف دي.", False),
        ("6) اسم حالة جديد = حالة جديدة بتتضاف. تغيير اسم حالة موجودة = حالة جديدة، والقديمة تفضل زي ما هي.", False),
        ("7) معاملات الـ Ultrasound اتركها فاضية أو كما هي، لأن القواعد الجاهزة في الموقع بتظبطها (/admin/fix-ultrasound).", False),
        ("7-أ) عمود action: اكتب delete لحذف الحالة نهائيًا من الموقع. اكتب - (شرطة) في أي خلية لمسح قيمتها.", False),
        ("8) بعد التعديل: لوحة الأدمن > Import Data > ارفع الملف.", False),
        ("", False),
        ("مثال لصف في ورقة Exercises (مثال فقط، لا يتم استيراده):", True),
    ]
    for i, (txt, bold) in enumerate(lines, start=1):
        c = g.cell(row=i, column=1, value=txt)
        c.font = Font(name='Arial', size=12 if bold else 10, bold=bold)
        c.alignment = Alignment(wrap_text=True, vertical='top')
    g.column_dimensions['A'].width = 110

    ex_header_row = len(lines) + 2
    for j, name in enumerate(EX_COLS, start=1):
        c = g.cell(row=ex_header_row, column=j, value=name)
        c.font = head_font
        c.fill = head_fill
    example = ['Adhesive Capsulitis', 'Phase 1: Freezing', 'Control pain and keep range',
               'Pendulum (Codman)', 'Lean forward with support, let the arm hang and swing in small circles.',
               '2 min, 3x/day']
    for j, v in enumerate(example, start=1):
        c = g.cell(row=ex_header_row + 1, column=j, value=v)
        c.font = font
        c.alignment = wrap
    for j in range(2, len(EX_COLS) + 1):
        g.column_dimensions[get_column_letter(j)].width = 28

    # ---------- Conditions ----------
    ws = wb.create_sheet('Conditions')
    for j, name in enumerate(COND_COLS, start=1):
        c = ws.cell(row=1, column=j, value=name)
        c.font = head_font
        c.fill = head_fill
        ws.column_dimensions[get_column_letter(j)].width = COND_WIDTHS.get(name, 24)
    ws.freeze_panes = 'B2'

    # ---------- Exercises ----------
    we = wb.create_sheet('Exercises')
    for j, name in enumerate(EX_COLS, start=1):
        c = we.cell(row=1, column=j, value=name)
        c.font = head_font
        c.fill = head_fill
        we.column_dimensions[get_column_letter(j)].width = EX_WIDTHS.get(name, 24)
    we.freeze_panes = 'B2'

    r_c, r_e = 2, 2
    for p in protocols:
        notes = split_notes(p.notes)
        values = {
            'disease_name': p.disease_name, 'category': p.category, 'keywords': p.keywords,
            'description': p.description, 'estim_type': p.estim_type, 'estim_params': p.estim_params,
            'estim_role': p.estim_role, 'us_type': p.us_type, 'us_params': p.us_params,
            'us_role': p.us_role, 'ex_frequency': p.ex_frequency, 'ex_intensity': p.ex_intensity,
            'ex_progression': p.ex_progression, 'exercises_role': p.exercises_role,
            'evidence_level': p.evidence_level, 'source_ref': p.source_ref, **notes,
        }
        for j, name in enumerate(COND_COLS, start=1):
            c = ws.cell(row=r_c, column=j, value=values.get(name) or None)
            c.font = font
            c.alignment = wrap
        r_c += 1

        for ph, goal, ex_name, instr, dose in exercises_to_rows(p.exercises_list):
            for j, v in enumerate([p.disease_name, ph, goal or None, ex_name, instr or None, dose or None], start=1):
                c = we.cell(row=r_e, column=j, value=v)
                c.font = font
                c.alignment = wrap
            r_e += 1

    out = BytesIO()
    wb.save(out)
    out.seek(0)
    return out


def _cell(v):
    if v is None:
        return ''
    try:
        if pd.isna(v):
            return ''
    except Exception:
        pass
    s = str(v).strip()
    return '' if s.lower() == 'nan' else s


def parse_template_workbook(xls):
    """يقرا ورقتين Conditions و Exercises ويرجّع (conditions, exercises_by_name)."""
    cond = xls.parse('Conditions', dtype=str)
    ex = xls.parse('Exercises', dtype=str)
    cond.columns = [str(c).strip() for c in cond.columns]
    ex.columns = [str(c).strip() for c in ex.columns]

    conditions = []
    for _, r in cond.iterrows():
        d = {c: _cell(r.get(c)) for c in COND_COLS}
        if d['disease_name']:
            conditions.append(d)

    ex_map = {}
    for _, r in ex.iterrows():
        name = _cell(r.get('disease_name'))
        exercise = _cell(r.get('exercise'))
        if not name or not exercise:
            continue
        ex_map.setdefault(name.lower(), []).append({
            'phase': _cell(r.get('phase')), 'phase_goal': _cell(r.get('phase_goal')),
            'exercise': exercise, 'instructions': _cell(r.get('instructions')),
            'dosage': _cell(r.get('dosage')),
        })
    return conditions, ex_map


def _import_template_workbook(xls):
    conditions, ex_map = parse_template_workbook(xls)
    simple = ['category', 'keywords', 'description', 'estim_type', 'estim_params', 'estim_role',
              'us_type', 'us_params', 'us_role', 'ex_frequency', 'ex_intensity', 'ex_progression',
              'exercises_role', 'evidence_level', 'source_ref']
    created = updated = deleted = 0
    handled = set()

    for d in conditions:
        name = d['disease_name']
        handled.add(name.lower())
        p = Protocol.query.filter(db.func.lower(Protocol.disease_name) == name.lower()).first()

        if d.get('action', '').strip().lower() == 'delete':
            if p:
                db.session.delete(p)
                deleted += 1
            continue

        is_new = p is None
        if is_new:
            p = Protocol(disease_name=name, category='General')
            db.session.add(p)
            created += 1
        else:
            updated += 1

        for col in simple:
            if d[col] == '-':
                setattr(p, col, '')
            elif d[col]:
                setattr(p, col, d[col])

        raw_notes = [d[k] for k in ('diagnosis', 'manual_therapy', 'precautions', 'other_notes')]
        if any(raw_notes):
            vals = ['' if v == '-' else v for v in raw_notes]
            p.notes = join_notes(*vals)

        rows = ex_map.get(name.lower())
        if rows:
            p.exercises_list = sanitize_rich_html(rows_to_exercises_html(rows))

        if is_new and not p.keywords:
            p.keywords = f"{name}, {p.category}"
        us_now = (p.us_params or '').strip().lower()
        if not us_now or 'refer to' in us_now:
            apply_us_rule(p)

    orphans = sorted(set(ex_map) - handled)
    return created, updated, deleted, orphans


def _import_legacy_df(df):
    """الشكل القديم: صف واحد لكل حالة (CSV أو ورقة واحدة)."""
    df.columns = df.columns.str.strip()

    def get_val(row, col_name):
        val = row.get(col_name)
        return "" if (pd.isna(val) or str(val).strip() == 'nan') else str(val).strip()

    updated = created = 0
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
        p.estim_type = "Electrical Stimulation"
        p.us_params = get_val(row, 'us_params')
        p.us_type = "Ultrasound"
        p.exercises_list = sanitize_rich_html(get_val(row, 'exercises_list'))
        p.exercises_role = get_val(row, 'exercises_role')
        p.ex_frequency = get_val(row, 'ex_frequency')
        p.ex_intensity = get_val(row, 'ex_intensity')
        p.ex_progression = get_val(row, 'ex_progression')
        p.evidence_level = get_val(row, 'evidence_level')
        if not p.us_params:
            apply_us_rule(p)
    return created, updated



@app.route('/admin/download-template')
@admin_required
def download_template():
    protocols = Protocol.query.order_by(Protocol.category, Protocol.disease_name).all()
    out = build_template_workbook(protocols)
    return send_file(
        out,
        download_name='physio_protocols_template.xlsx',
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
        # Only .xlsx workbooks are accepted; reject CSV and macro-enabled formats.
        if not file.filename.lower().endswith('.xlsx'):
            raise ValueError("Upload an .xlsx file only.")
        file.stream.seek(0)
        if file.stream.read(4) != b'PK\x03\x04':
            raise ValueError("Invalid XLSX file.")
        file.stream.seek(0)

        xls = pd.ExcelFile(file, engine='openpyxl')
        sheets = set(xls.sheet_names)
        check = ['Conditions', 'Exercises'] if {'Conditions', 'Exercises'} <= sheets else [xls.sheet_names[0]]
        for name in check:
            probe = xls.parse(name, dtype=str)
            if len(probe.index) > 5000 or len(probe.columns) > 40:
                raise ValueError("Workbook exceeds the allowed size (5,000 rows / 40 columns).")

        orphans, deleted = [], 0
        if {'Conditions', 'Exercises'} <= sheets:
            created, updated, deleted, orphans = _import_template_workbook(xls)
        else:
            created, updated = _import_legacy_df(xls.parse(xls.sheet_names[0]))

        db.session.commit()
        flash(f'Done! Created {created}, Updated {updated}, Deleted {deleted} protocols.', 'success')
        if orphans:
            flash('Exercises ignored (name not found in Conditions sheet): ' + ', '.join(orphans[:10]), 'warning')

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
    disease = (request.values.get('disease') or '').strip()[:200]
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('home', disease=disease) if disease else url_for('home'))
        flash('Login Failed. Check email/password', 'danger')
        return render_template('login.html', email=email, disease=disease), 401
    return render_template('login.html', disease=disease)


@app.route('/forgot-password')
def forgot_password(): return render_template('forgot_password.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    disease = (request.values.get('disease') or '').strip()[:200]
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        if len(password) < 12:
            flash('Password must be at least 12 characters.', 'danger')
            return render_template('register.html', email=email, disease=disease), 400
        if not email or len(email) > 150 or '@' not in email:
            flash('Enter a valid email address.', 'danger')
            return render_template('register.html', email=email, disease=disease), 400
        if User.query.filter_by(email=email).first():
            flash('This email is already registered. Please log in.', 'danger')
            return render_template('register.html', email=email, disease=disease), 400
        try:
            user = User(email=email, password=generate_password_hash(password, method='pbkdf2:sha256'))
            db.session.add(user)
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash('Unable to create account. Please try again.', 'danger')
            return render_template('register.html', email=email, disease=disease), 400
        login_user(user)
        return redirect(url_for('home', disease=disease) if disease else url_for('home'))
    return render_template('register.html', disease=disease)


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
with app.app_context():
    db.create_all()
    ensure_columns()
    _admin_email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
    if _admin_email:
        _u = User.query.filter(db.func.lower(User.email) == _admin_email).first()
        if _u and not _u.is_admin:
            _u.is_admin = True
            db.session.commit()
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=False)
