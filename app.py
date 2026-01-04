import os
from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user

app = Flask(__name__)
app.secret_key = 'super_secret_key_physio_expert'

# إنشاء قاعدة بيانات محلية بسيطة (SQLite)
DB_PATH = 'physio_expert.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # إنشاء جدول المستخدمين
    cur.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        created_at TEXT NOT NULL
    )''')
    conn.commit()
    conn.close()

# تهيئة قاعدة البيانات عند بدء التشغيل
init_db()

# --- قاعدة بيانات الأمراض المدمجة (تعدل من هنا) ---
PROTOCOLS_DATA = [
    {"disease_name": "Disc Prolapse", "keywords": "back pain, sciatica, disc", "protocol_text": "البروتوكول: الراحة، تمارين الاستطالة، وتقوية الجذع."},
    {"disease_name": "ACL Tear", "keywords": "knee injury, surgery", "protocol_text": "البروتوكول: مدى الحركة، تقوية الكواد، والتوازن."},
    {"disease_name": "Frozen Shoulder", "keywords": "shoulder pain", "protocol_text": "البروتوكول: تحريك المفصل يدوياً والتمارين الحركية."}
]

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id, email, created_at):
        self.id = id
        self.email = email
        self.created_at = created_at

@login_manager.user_loader
def load_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT * FROM users WHERE id = ?', (user_id,))
    user_data = cur.fetchone()
    conn.close()
    if user_data:
        return User(user_data[0], user_data[1], user_data[3])
    return None

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        hashed_pw = generate_password_hash(password)
        created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute('INSERT INTO users (email, password, created_at) VALUES (?, ?, ?)', (email, hashed_pw, created_at))
            conn.commit()
            conn.close()
            flash('تم التسجيل! سجل دخولك الآن', 'success')
            return redirect(url_for('login'))
        except:
            flash('الإيميل مسجل بالفعل', 'danger')
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute('SELECT * FROM users WHERE email = ?', (email,))
        user_data = cur.fetchone()
        conn.close()
        
        if user_data and check_password_hash(user_data[2], password):
            user_obj = User(user_data[0], user_data[1], user_data[3])
            login_user(user_obj)
            return redirect(url_for('home'))
        else:
            flash('بيانات غير صحيحة', 'danger')
    return render_template('login.html')

@app.route('/', methods=['GET', 'POST'])
@login_required
def home():
    reg_date = datetime.strptime(current_user.created_at, '%Y-%m-%d %H:%M:%S')
    days_left = 30 - (datetime.now() - reg_date).days
    if days_left <= 0: return redirect(url_for('subscribe'))
    
    result = None
    if request.method == 'POST':
        query = request.form.get('disease', '').lower()
        for p in PROTOCOLS_DATA:
            if query in p['disease_name'].lower() or query in p['keywords'].lower():
                result = p
                break
        if not result: result = "Not Found"
    return render_template('index.html', result=result, days_left=days_left, user=current_user)

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/subscribe')
def subscribe():
    return render_template('subscribe.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
