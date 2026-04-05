import os
import qrcode
import psycopg2
from psycopg2 import extras
import secrets
from flask import (Flask, render_template, request, send_file,
                   redirect, url_for, session, flash)
from werkzeug.utils import secure_filename
from urllib.parse import quote
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

# Configuración Flask
app = Flask(__name__, static_folder='static', static_url_path='/static')
app.secret_key = os.environ.get('SECRET_KEY', 'un-secreto-cualquiera-2026')
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'uploads')
app.config['ALLOWED_EXTENSIONS'] = {'pdf', 'doc', 'docx'}

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

BASE_URL = os.environ.get("BASE_URL", "https://qr-machine.onrender.com")

def get_db_connection():
    try:
        conn_url = os.getenv("DATABASE_URL")
        return psycopg2.connect(conn_url)
    except Exception as e:
        print(f"Error de conexión a la base de datos: {e}")
        return None

# --- INICIALIZACIÓN DE TABLAS ---
def init_db():
    conn = get_db_connection()
    if not conn: return
    with conn.cursor() as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usuarios_comunes (
                id SERIAL PRIMARY KEY,
                nombre VARCHAR(50) NOT NULL,
                apellido VARCHAR(50) NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                last_login TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usuarios_admin (
                id SERIAL PRIMARY KEY,
                nombre VARCHAR(50) NOT NULL,
                apellido VARCHAR(50) NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                last_login TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS archivos (
                id SERIAL PRIMARY KEY,
                nombre VARCHAR(255),
                extension VARCHAR(10),
                token VARCHAR(64),
                fecha_subida TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                usuario_comun_id INT,
                usuario_admin_id INT,
                FOREIGN KEY (usuario_comun_id) REFERENCES usuarios_comunes(id) ON DELETE SET NULL,
                FOREIGN KEY (usuario_admin_id) REFERENCES usuarios_admin(id) ON DELETE SET NULL
            )
        """)
    conn.commit()
    conn.close()

init_db()

def _dated_url_for(endpoint, **values):
    if endpoint == 'static':
        filename = values.get('filename')
        if filename:
            file_path = os.path.join(app.static_folder, filename)
            if os.path.exists(file_path):
                values['q'] = int(os.stat(file_path).st_mtime)
    return url_for(endpoint, **values)

@app.context_processor
def override_url_for():
    return dict(url_for=_dated_url_for)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

# --- RUTAS ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        role = request.form.get('role')

        if not username or not password or not role:
            flash("Complete todos los campos")
            return redirect(url_for('login'))

        conn = get_db_connection()
        table = "usuarios_admin" if role == "admin" else "usuarios_comunes"
        
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cursor:
            cursor.execute(f"SELECT id, password_hash FROM {table} WHERE nombre = %s", (username,))
            user = cursor.fetchone()

            if user:
                if not check_password_hash(user["password_hash"], password):
                    flash("Contraseña incorrecta")
                    return redirect(url_for('login'))
                user_id = user["id"]
            else:
                password_hash = generate_password_hash(password)
                cursor.execute(
                    f"INSERT INTO {table} (nombre, apellido, password_hash) VALUES (%s, %s, %s) RETURNING id",
                    (username, "usuario", password_hash)
                )
                user_id = cursor.fetchone()['id']
            
            cursor.execute(f"UPDATE {table} SET last_login = %s WHERE id = %s", (datetime.now(), user_id))
            conn.commit()

        session.update({'user_id': user_id, 'username': username, 'role': role})
        conn.close()
        return redirect(url_for('admin_dashboard' if role == "admin" else 'index'))

    return render_template('login.html')

@app.route('/', methods=['GET', 'POST'])
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    qr_filename = None

    if request.method == 'POST':
        file = request.files.get('file')
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            extension = filename.rsplit('.', 1)[1].lower()
            filepath = os.path.abspath(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            file.save(filepath)
            
            token = secrets.token_urlsafe(32)
            qr_filename = f"{filename}.png"
            qr_path = os.path.abspath(os.path.join(app.root_path, 'static', qr_filename))
            
            qr = qrcode.make(f"{BASE_URL}/download/{quote(filename)}?token={token}")
            qr.save(qr_path)

            with conn.cursor() as cur:
                sql = "INSERT INTO archivos (nombre, extension, token, usuario_admin_id, usuario_comun_id) VALUES (%s,%s,%s,%s,%s)"
                params = (filename, extension, token, 
                          session['user_id'] if session['role'] == 'admin' else None,
                          session['user_id'] if session['role'] != 'admin' else None)
                cur.execute(sql, params)
                conn.commit()

    with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
        if session.get('role') == 'admin':
            cur.execute("""
                SELECT a.*, COALESCE(uc.nombre, ua.nombre) as subido_por
                FROM archivos a
                LEFT JOIN usuarios_comunes uc ON a.usuario_comun_id = uc.id
                LEFT JOIN usuarios_admin ua ON a.usuario_admin_id = ua.id
                ORDER BY a.fecha_subida DESC
            """)
        else:
            cur.execute("SELECT * FROM archivos WHERE usuario_comun_id = %s ORDER BY fecha_subida DESC", (session['user_id'],))
        historial = cur.fetchall()

    conn.close()
    return render_template("index.html", historial=historial, qr_filename=qr_filename)

@app.route('/download/<filename>')
def download(filename):
    token = request.args.get('token')
    if not token: return "Acceso no autorizado", 403

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT token FROM archivos WHERE nombre=%s", (filename,))
        result = cursor.fetchone()
        
    conn.close()
    if not result or token != result[0]:
        return "Token inválido o archivo no encontrado", 403

    filepath = os.path.abspath(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    return send_file(filepath, as_attachment=True)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)