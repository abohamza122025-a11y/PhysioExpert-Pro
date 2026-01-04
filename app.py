from flask import Flask, render_template, request, redirect, url_for, flash
import psycopg2
import psycopg2.extras
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user

app = Flask(__name__)
app.secret_key = 'super_secret_key_physio_expert'

# التعديل الجوهري: استخدام رابط الـ Transaction Pooler (المنفذ 6543)
# هذا الرابط يدعم IPv4 ويحل مشكلة Network is unreachable بشكل نهائي
DB_URL = "postgresql://postgres.xaqqxjouxfdxfafvgvoc:Physiosupabase%402026@aws-0-eu-central-1.pooler.supabase.com:6543/postgres?sslmode=require"

def get_db_connection():
    try:
        # اتصال سريع ومباشر مع مهلة 5 ثوانٍ فقط لمنع تعليق الموقع
        conn = psycopg2.connect(DB_URL, connect_timeout=5)
        return conn
    except Exception as e:
        print(f"Database Connection Error: {e}")
        return None

# إعدادات نظام الدخول
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
    conn = get_db_connection()
    if not conn: return None
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute('SELECT * FROM users WHERE id = %s', (user_id,))
        user_data = cur.fetchone()
        cur.close()
        conn.close()
        if user_data:
            return User(user_data['id'], user_data['email'], user_data['created_at'])
    except:
        if conn: conn.close()
    return None

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        if not email or not password:
            flash('الرجاء إدخال البيانات كاملة', 'danger')
            return redirect(url_for('register'))

        hashed_pw = generate_password_hash(password)
        conn = get_db_connection()
        if not conn:
            flash('تعذر الاتصال بقاعدة البيانات حالياً', 'danger')
            return redirect(url_for('register'))

        try:
            cur = conn.cursor()
            # التأكد من تنفيذ الحفظ الفعلي
            cur.execute('INSERT INTO users (email, password) VALUES (%s, %s)', (email, hashed_pw))
            conn.commit()
            cur.close()
            conn.close()
            flash('تم التسجيل بنجاح! سجل دخولك الآن', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            if conn: conn.rollback()
            print(f"Register SQL Error: {e}")
            flash('خطأ: البريد الإلكتروني مسجل بالفعل', 'danger')
        finally:
            if conn: conn.close()
            
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        conn = get_db_connection()
        if not conn:
            flash('خطأ في الاتصال بالسيرفر', 'danger')
            return render_template('login.html')
        
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cur.execute('SELECT * FROM users WHERE email = %s', (email,))
            user_data = cur.fetchone()
            cur.close()
            conn.close()
            
            if user_data and check_password_hash(user_data['password'], password):
                user_obj = User(user_data['id'], user_data['email'], user_data['created_at'])
                login_user(user_obj)
                return redirect(url_for('home'))
            else:
                flash('بيانات الدخول غير صحيحة', 'danger')
        except:
            if conn: conn.close()
            flash('حدث خطأ فني، حاول مجدداً', 'danger')
            
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/', methods=['GET', 'POST'])
@login_required
def home():
    # معالجة التاريخ لضمان عدم حدوث خطأ عند حساب الأيام
    reg_date = current_user.created_at
    if isinstance(reg_date, str):
        # تنظيف التاريخ من أي أجزاء إضافية
        reg_date = datetime.strptime(reg_date.split('.')[0], '%Y-%m-%d %H:%M:%S')
    
    reg_date = reg_date.replace(tzinfo=None)
    days_elapsed = (datetime.now() - reg_date).days
    days_left = 30 - days_elapsed
    
    if days_left <= 0:
        return redirect(url_for('subscribe'))
    
    result = None
    if request.method == 'POST':
        search_query = request.form.get('disease', '')
        conn = get_db_connection()
        if conn:
            try:
                cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
                search_term = '%' + search_query + '%'
                cur.execute("SELECT * FROM protocols WHERE disease_name ILIKE %s OR keywords ILIKE %s", 
                            (search_term, search_term))
                data = cur.fetchone()
                cur.close()
                conn.close()
                result = data if data else "Not Found"
            except:
                if conn: conn.close()
                result = "Error"
    
    return render_template('index.html', result=result, days_left=days_left, user=current_user)

@app.route('/subscribe')
@login_required
def subscribe():
    return render_template('subscribe.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
