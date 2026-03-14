import os
import qrcode
import mysql.connector
import secrets
from flask import (Flask, render_template, request, send_file,
                   redirect, url_for, session, flash)
from werkzeug.utils import secure_filename
from urllib.parse import quote
from werkzeug.security import generate_password_hash, check_password_hash
from PyPDF2 import PdfReader
from docx import Document

# Configuración Flask
app = Flask(__name__, static_folder='static', static_url_path='/static')
app.secret_key = 'un‑secreto‑cualquiera'            # <------ necesario para sesiones
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['ALLOWED_EXTENSIONS'] = {'pdf', 'doc', 'docx'}

UPLOAD_FOLDER = os.path.join(app.root_path, 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

if not os.path.exists(os.path.join(app.root_path, 'static')):
    os.makedirs(os.path.join(app.root_path, 'static'), exist_ok=True)

BASE_URL = os.environ.get("BASE_URL", "https://qr-machine.onrender.com")

# Para invalidar caché de archivos estáticos (CSS)
@app.context_processor
def override_url_for():
    return dict(url_for=_dated_url_for)

def _dated_url_for(endpoint, **values):
    if endpoint == 'static':
        filename = values.get('filename')
        if filename:
            file_path = os.path.join(app.static_folder, filename)
            if os.path.exists(file_path):
                values['q'] = int(os.stat(file_path).st_mtime)
    return url_for(endpoint, **values)

def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("MYSQLHOST", "localhost"),
        user=os.getenv("MYSQLUSER", "root"),
        password=os.getenv("MYSQLPASSWORD", "29012004"),
        database=os.getenv("MYSQLDATABASE", "qr_machine"),
        port=int(os.getenv("MYSQLPORT", 3306))
    )

# 2. Inicializar conexión y tablas
db = get_db_connection()
cursor = db.cursor()

# 3. Crear tablas (solo si no existen)
cursor.execute("""
    CREATE TABLE IF NOT EXISTS usuarios_comunes (
        id INT AUTO_INCREMENT PRIMARY KEY,
        nombre VARCHAR(50) NOT NULL,
        apellido VARCHAR(50) NOT NULL,
        password_hash VARCHAR(255) NOT NULL
    )
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS usuarios_admin (
        id INT AUTO_INCREMENT PRIMARY KEY,
        nombre VARCHAR(50) NOT NULL,
        apellido VARCHAR(50) NOT NULL,
        password_hash VARCHAR(255) NOT NULL
    )
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS archivos (
        id INT AUTO_INCREMENT PRIMARY KEY,
        nombre VARCHAR(255),
        extension VARCHAR(10),
        token VARCHAR(64),
        fecha_subida DATETIME DEFAULT CURRENT_TIMESTAMP,
        usuario_comun_id INT,
        usuario_admin_id INT,
        FOREIGN KEY (usuario_comun_id) REFERENCES usuarios_comunes(id) ON DELETE SET NULL,
        FOREIGN KEY (usuario_admin_id) REFERENCES usuarios_admin(id) ON DELETE SET NULL
    )
""")

db.commit()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

# Autenticación
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        admin_token = request.form.get('admin_token') 

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True, buffered=True)
        
        # IMPORTANTE: Usamos la tabla 'usuarios_comunes' que creaste al inicio
        cursor.execute("SELECT * FROM usuarios_comunes WHERE nombre = %s AND password_hash = %s", (username, password))
        user = cursor.fetchone()
        
        if user and user['password_hash'] == password: 
            session['user_id'] = user['id']
            
            # Si el token es correcto, le damos rango de admin
            if admin_token == "GABRIEL_2026":
                session['role'] = 'admin'
                return redirect(url_for('admin_dashboard'))
            else:
                session['role'] = 'user'
                return redirect(url_for('index'))
        
        flash("Credenciales incorrectas")
        return redirect(url_for('login'))
        
    return render_template('login.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    # Aquí va tu lógica actual de guardar archivo y generar QR
    #
    return "QR Generado y archivo subido con éxito"

@app.route('/admin/dashboard')
def admin_dashboard():
    if session.get('role') != 'admin':
        return "Acceso denegado", 403
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)
    
    # Ver archivos subidos (Lista para eliminar)
    cursor.execute("SELECT * FROM archivos")
    archivos = cursor.fetchall()
    
    # Ver usuarios que han iniciado sesión (Log de accesos)
    cursor.execute("SELECT username, last_login FROM usuarios")
    usuarios = cursor.fetchall()
    
    conn.close()
    return render_template('admin.html', archivos=archivos, usuarios=usuarios)

# Opcion de borrado de archivos (modo administrador)
@app.route('/admin/delete/<int:file_id>')
def delete_file(file_id):
    if session.get('role') != 'admin':
        return "Acceso denegado", 403

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT nombre FROM archivos WHERE id = %s", (file_id,))
    archivo = cursor.fetchone()

    if archivo:
        nombre_archivo = archivo['nombre']
        cursor.execute("DELETE FROM archivos WHERE id = %s", (file_id,))
        conn.commit()

        # Borrar archivos físicos
        try:
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], nombre_archivo))
            os.remove(os.path.join(app.root_path, 'static', f"{nombre_archivo}.png"))
        except:
            pass

    cursor.close()
    conn.close()
    return redirect(url_for('admin_dashboard'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# 4. Rutas principales
@app.route('/', methods=['GET', 'POST'])
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # CREAR CONEXIÓN DENTRO DE LA FUNCIÓN
    conn = get_db_connection()
    cur = conn.cursor()

    qr_filename = None  

    if request.method == 'POST':
        file = request.files.get('file')
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            extension = filename.rsplit('.', 1)[1].lower()
            
            # --- CAMBIO 1: Forzar ruta absoluta para el archivo subido ---
            filepath = os.path.abspath(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            file.save(filepath)
            
            token = secrets.token_urlsafe(32)

            # Generar QR
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            filename_encoded = quote(filename)
            qr.add_data(f"{BASE_URL}/download/{filename_encoded}?token={token}")
            qr.make(fit=True)
            img = qr.make_image(fill='black', back_color='white')
            
            # --- CAMBIO 2: Forzar ruta absoluta para la imagen del QR ---
            qr_filename = f"{filename}.png"
            qr_path = os.path.abspath(os.path.join(app.root_path, 'static', qr_filename))
            img.save(qr_path)

            # --- CAMBIO 3: Asegurar el commit a la base de datos ---
            sql = "INSERT INTO archivos (nombre, extension, token, usuario_admin_id, usuario_comun_id) VALUES (%s,%s,%s,%s,%s)"
            if session.get('role') == 'admin':
                cur.execute(sql, (filename, extension, token, session['user_id'], None))
            else:
                cur.execute(sql, (filename, extension, token, None, session['user_id']))
            
            conn.commit() # Asegúrate de que esta línea esté presente
            
    # Obtener historial
    if session.get('role') == 'admin':
        cur.execute("""
            SELECT a.nombre, a.extension, a.fecha_subida, a.id,
                COALESCE(uc.nombre, ua.nombre) as subido_por
            FROM archivos a
            LEFT JOIN usuarios_comunes uc ON a.usuario_comun_id = uc.id
            LEFT JOIN usuarios_admin ua ON a.usuario_admin_id = ua.id
            ORDER BY a.fecha_subida DESC
        """)
    else:
        cur.execute("""SELECT nombre, extension, fecha_subida, id
                          FROM archivos WHERE usuario_comun_id = %s
                          ORDER BY fecha_subida DESC""",
                       (session['user_id'],))
    
    historial = cur.fetchall()
    
    # CERRAR CONEXIÓN AL TERMINAR
    cur.close()
    conn.close()
    
    return render_template("index.html", historial=historial, qr_filename=qr_filename)

@app.route('/filter/<extension>')
def filter_by_extension(extension):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if session.get('role') == 'admin':
        cursor.execute("""SELECT nombre, extension, fecha_subida, id
                          FROM archivos WHERE extension = %s
                          ORDER BY fecha_subida DESC""", (extension,))
    else:
        cursor.execute("""SELECT nombre, extension, fecha_subida, id
                          FROM archivos WHERE extension = %s AND usuario_comun_id = %s
                          ORDER BY fecha_subida DESC""",
                       (extension, session['user_id']))
    filtered = cursor.fetchall()
    return render_template("index.html", historial=filtered)

@app.route('/download/<filename>')
def download(filename):
    token = request.args.get('token')

    # Si no hay token, bloquear
    if not token:
        return "Acceso no autorizado", 403

    # 1. Crear conexión y cursor con BUFFER (Esto evita el error de tus logs)
    conn = get_db_connection()
    cursor = conn.cursor(buffered=True) # El parámetro buffered=True es la clave

    try:
        # Buscar token del archivo
        cursor.execute("SELECT token FROM archivos WHERE nombre=%s", (filename,))
        result = cursor.fetchone()

        if not result:
            return "Archivo no encontrado en la base de datos", 404

        stored_token = result[0]

        # Verificar token
        if token != stored_token:
            return "Token inválido", 403

        # 2. Usar ruta absoluta para evitar FileNotFoundError en Render
        filepath = os.path.abspath(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        if not os.path.exists(filepath):
            return "El archivo físico no existe en el servidor", 404

        return send_file(filepath, as_attachment=True)

    except Exception as e:
        print(f"Error: {e}")
        return "Error interno del servidor", 500
    finally:
        # 3. Siempre cerrar cursor y conexión
        cursor.close()
        conn.close()

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)