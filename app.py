from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user

app = Flask(__name__)
app.secret_key = 'super_secret_key_physio_expert' # مفتاح أمان للجلسة

# إعدادات نظام الدخول
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

def get_db_connection():
    conn = sqlite3.connect('physio.db')
    conn.row_factory = sqlite3.Row
    return conn

# كلاس المستخدم
class User(UserMixin):
    def __init__(self, id, email, created_at):
        self.id = id
        self.email = email
        self.created_at = created_at

@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    user_data = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    if user_data:
        return User(user_data['id'], user_data['email'], user_data['created_at'])
    return None

# --- صفحة التسجيل (Register) ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        # تشفير كلمة المرور وتخزين تاريخ اليوم
        hashed_pw = generate_password_hash(password)
        created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        conn = get_db_connection()
        try:
            conn.execute('INSERT INTO users (email, password, created_at) VALUES (?, ?, ?)',
                         (email, hashed_pw, created_at))
            conn.commit()
            flash('Account created! Please log in.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Email already exists!', 'danger')
        finally:
            conn.close()
            
    return render_template('register.html')

# --- صفحة الدخول (Login) ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        conn = get_db_connection()
        user_data = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        conn.close()
        
        if user_data and check_password_hash(user_data['password'], password):
            user_obj = User(user_data['id'], user_data['email'], user_data['created_at'])
            login_user(user_obj)
            return redirect(url_for('home'))
        else:
            flash('Invalid email or password', 'danger')
            
    return render_template('login.html')

# --- تسجيل الخروج ---
@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# --- الصفحة الرئيسية (محمية) ---
@app.route('/', methods=['GET', 'POST'])
@login_required
def home():
    # 1. حساب الفترة المتبقية
    reg_date = datetime.strptime(current_user.created_at, '%Y-%m-%d %H:%M:%S')
    days_elapsed = (datetime.now() - reg_date).days
    days_left = 30 - days_elapsed
    
    # 2. لو الفترة انتهت -> تحويل لصفحة الاشتراك
    if days_left <= 0:
        return redirect(url_for('subscribe'))
    
    # 3. منطق البحث الطبي العادي
    result = None
    if request.method == 'POST':
        search_query = request.form.get('disease', '')
        conn = get_db_connection()
        sql_query = "SELECT * FROM protocols WHERE disease_name LIKE ? OR keywords LIKE ?"
        search_term = '%' + search_query + '%'
        data = conn.execute(sql_query, (search_term, search_term)).fetchone()
        conn.close()
        result = data if data else "Not Found"

    return render_template('index.html', result=result, days_left=days_left, user=current_user)

# --- صفحة الاشتراك (عند انتهاء الفترة) ---
@app.route('/subscribe')
@login_required
def subscribe():
    return render_template('subscribe.html')
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)