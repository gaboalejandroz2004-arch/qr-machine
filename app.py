import os
import qrcode
import psycopg2
from psycopg2 import extras
import secrets
from flask import (Flask, render_template, request, send_file,
                   redirect, url_for, session, flash, send_from_directory)
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

# --- RUTAS DE AUTENTICACIÓN ---
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
        
        # Redirección inteligente dependiendo del rol
        if role == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('index'))

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# --- RUTAS PARA USUARIO COMÚN (index.html) ---
@app.route('/', methods=['GET', 'POST'])
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    qr_filename = None

    if request.method == 'POST':
        file = request.files.get('file')
        if file and file.filename != '':
            filename = secure_filename(file.filename)
            token_seguro = secrets.token_urlsafe(16)
            extension_archivo = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
            
            # Guardar archivo físicamente
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            
            # Guardar en DB
            with conn.cursor() as cur:
                u_comun = session['user_id'] if session['role'] != 'admin' else None
                u_admin = session['user_id'] if session['role'] == 'admin' else None
                
                cur.execute("""
                    INSERT INTO archivos (nombre, extension, token, usuario_comun_id, usuario_admin_id) 
                    VALUES (%s, %s, %s, %s, %s)
                """, (filename, extension_archivo, token_seguro, u_comun, u_admin))
                conn.commit()

            # Generar QR
            qr_filename = f"{filename}.png"
            qr_path = os.path.join(app.static_folder, qr_filename)
            link_descarga = f"{BASE_URL}/download/{filename}?token={token_seguro}"
            img = qrcode.make(link_descarga)
            img.save(qr_path)

    # Obtener el historial completo
    with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT a.*, COALESCE(uc.nombre, ua.nombre) as subido_por 
            FROM archivos a
            LEFT JOIN usuarios_comunes uc ON a.usuario_comun_id = uc.id
            LEFT JOIN usuarios_admin ua ON a.usuario_admin_id = ua.id
            ORDER BY a.fecha_subida DESC
        """)
        historial = cur.fetchall()

    conn.close()
    return render_template("index.html", historial=historial, qr_filename=qr_filename)

@app.route('/filter/<extension>')
def filter(extension):
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('index'))
        
    conn = get_db_connection()
    with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT a.*, COALESCE(uc.nombre, ua.nombre) as subido_por 
            FROM archivos a
            LEFT JOIN usuarios_comunes uc ON a.usuario_comun_id = uc.id
            LEFT JOIN usuarios_admin ua ON a.usuario_admin_id = ua.id
            WHERE a.extension = %s
            ORDER BY a.fecha_subida DESC
        """, (extension,))
        historial = cur.fetchall()
    conn.close()
    return render_template("index.html", historial=historial, qr_filename=None)

@app.route('/delete/<int:id_db>')
def delete(id_db):
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('index'))
        
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM archivos WHERE id = %s", (id_db,))
        conn.commit()
    conn.close()
    return redirect(url_for('index'))


# --- RUTAS PARA PANEL DE ADMINISTRADOR (admin.html) ---
@app.route('/admin')
def admin_dashboard():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('index'))
        
    conn = get_db_connection()
    with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
        # Obtener todos los usuarios unidos
        cur.execute("""
            SELECT nombre, apellido, last_login FROM usuarios_comunes
            UNION ALL
            SELECT nombre, apellido, last_login FROM usuarios_admin
            ORDER BY last_login DESC NULLS LAST
        """)
        usuarios = cur.fetchall()
        
        # Obtener archivos subidos
        cur.execute("SELECT id, nombre, token FROM archivos ORDER BY fecha_subida DESC")
        archivos = cur.fetchall()
        
    conn.close()
    return render_template("admin.html", usuarios=usuarios, archivos=archivos)

@app.route('/delete_file/<int:file_id>')
def delete_file(file_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('index'))
        
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM archivos WHERE id = %s", (file_id,))
        conn.commit()
    conn.close()
    return redirect(url_for('admin_dashboard'))


# --- RUTA DE DESCARGA GLOBAL ---
@app.route('/download/<filename>')
def download_file(filename):
    token_recibido = request.args.get('token')
    conn = get_db_connection()
    
    with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
        cur.execute("SELECT token FROM archivos WHERE nombre = %s", (filename,))
        resultado = cur.fetchone()
    conn.close()

    if resultado and token_recibido == resultado['token']:
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
    
    return "Token inválido o archivo no encontrado", 403

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)