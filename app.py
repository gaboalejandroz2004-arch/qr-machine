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
    if request.method == 'POST':
        file = request.files['file']
        if file:
            filename = file.filename
            # 1. Generar un token único para este archivo
            token_seguro = secrets.token_urlsafe(16)
            
            # 2. Guardar el archivo físicamente
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            
            # 3. Guardar en Neon (incluyendo el token)
            cur = conn.cursor()
            query = """
                INSERT INTO archivos (nombre, extension, fecha_subida, subido_por, token) 
                VALUES (%s, %s, NOW(), %s, %s)
            """
            cur.execute(query, (filename, 'pdf', session['username'], token_seguro))
            conn.commit()
            cur.close()

            # 4. Generar la URL del QR con ese token
            qr_filename = f"{filename}.png"
            base_url = os.environ.get("BASE_URL")
            link_descarga = f"{base_url}/download/{filename}?token={token_seguro}"

@app.route('/download/<filename>')
def download_file(filename):
    # Obtener el token que viene en la URL del QR
    token_recibido = request.args.get('token')
    
    cur = conn.cursor()
    # Buscamos en la base de datos si el archivo existe y cuál es su token
    cur.execute("SELECT token FROM archivos WHERE nombre = %s", (filename,))
    resultado = cur.fetchone()
    cur.close()

    if resultado:
        # 'resultado' es un diccionario gracias a RealDictCursor
        token_real = resultado['token']
        
        if token_recibido == token_real:
            # Si coinciden, permitimos la descarga
            return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
    
    # Si no coinciden o no existe el archivo
    return "Token inválido o archivo no encontrado", 403

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    # No pongas db.cursor() aquí afuera
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)