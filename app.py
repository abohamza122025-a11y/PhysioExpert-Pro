from flask import Flask, render_template, request, redirect, url_for, flash
import psycopg2
import psycopg2.extras
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user

app = Flask(__name__)
app.secret_key = 'super_secret_key_physio_expert'

# تم تعديل الرابط لاستخدام %40 بدلاً من @ في كلمة السر لحل مشكلة الاتصال
DB_URL = "postgresql://postgres:Physiosupabase%402026@db.xaqqxjouxfdxfafvgvoc.supabase.co:5432/postgres"

def get_db_connection():
    # محاولة الاتصال بقاعدة البيانات
    conn = psycopg2.connect(DB_URL)
    return conn

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
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute('SELECT * FROM users WHERE id = %s', (user_id,))
        user_data = cur.fetchone()
        cur.close()
        conn.close()
        if user_data:
            return User(user_data['id'], user_data['email'], user_data['created_at'])
    except:
        return None
    return None

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        hashed_pw = generate_password_hash(password)
        created_at = datetime.now()
        
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute('INSERT INTO users (email, password, created_at) VALUES (%s, %s, %s)',
                        (email, hashed_pw, created_at))
            conn.commit()
            flash('Account created! Please log in.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            conn.rollback()
            flash('Email already exists or Database Error!', 'danger')
        finally:
            cur.close()
            conn.close()
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        try:
            conn = get_db_connection()
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
                flash('Invalid email or password', 'danger')
        except Exception as e:
            flash('Database Connection Error!', 'danger')
            
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/', methods=['GET', 'POST'])
@login_required
def home():
    # التأكد من تنسيق الوقت لحساب الفترة المتبقية
    reg_date = current_user.created_at
    
    # تحويل من نص إلى تاريخ إذا لزم الأمر، وإزالة المنطقة الزمنية للحساب
    if isinstance(reg_date, str):
        reg_date = datetime.strptime(reg_date, '%Y-%m-%d %H:%M:%S')
    
    # إزالة التوقيت المحلي للمقارنة الصحيحة
    reg_date = reg_date.replace(tzinfo=None)
    
    days_elapsed = (datetime.now() - reg_date).days
    days_left = 30 - days_elapsed
    
    if days_left <= 0:
        return redirect(url_for('subscribe'))
    
    result = None
    if request.method == 'POST':
        search_query = request.form.get('disease', '')
        try:
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            search_term = '%' + search_query + '%'
            cur.execute("SELECT * FROM protocols WHERE disease_name LIKE %s OR keywords LIKE %s", 
                        (search_term, search_term))
            data = cur.fetchone()
            cur.close()
            conn.close()
            result = data if data else "Not Found"
        except:
            result = "Database Error"

    return render_template('index.html', result=result, days_left=days_left, user=current_user)

@app.route('/subscribe')
@login_required
def subscribe():
    return render_template('subscribe.html')

if __name__ == '__main__':
    # بورت 10000 هو الافتراضي لـ Render
    app.run(host='0.0.0.0', port=10000)
