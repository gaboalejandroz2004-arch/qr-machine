import os
import qrcode
import mysql.connector
import secrets
from flask import (Flask, render_template, request, send_file,
                   redirect, url_for, session, flash)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from PyPDF2 import PdfReader
from docx import Document

# Configuración Flask
app = Flask(__name__, static_folder='static', static_url_path='/static')
app.secret_key = 'un‑secreto‑cualquiera'            # necesario para sesiones
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['ALLOWED_EXTENSIONS'] = {'pdf', 'doc', 'docx'}

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# También para la carpeta static por si acaso
if not os.path.exists('static'):
    os.makedirs('static')

BASE_URL = os.environ.get("BASE_URL", "http://localhost:5000")

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
# Nota: Quitamos la parte de 'CREATE DATABASE' porque en la nube ya te la dan
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
        nombre = request.form['nombre'].strip()
        apellido = request.form['apellido'].strip()
        password = request.form['password']
        full_name = f"{nombre} {apellido}".lower()

        # usuario administrador fijo
        if full_name == 'gabriel administrador' and password == 'gabo2004':
            cursor.execute("SELECT id FROM usuarios_admin WHERE nombre=%s AND apellido=%s",
                           (nombre, apellido))
            admin = cursor.fetchone()
            if not admin:
                hash_pw = generate_password_hash(password)
                cursor.execute("""INSERT INTO usuarios_admin 
                                  (nombre, apellido, password_hash)
                                  VALUES (%s, %s, %s)""",
                               (nombre, apellido, hash_pw))
                db.commit()
                admin_id = cursor.lastrowid
            else:
                admin_id = admin[0]
            session['user_id'] = admin_id
            session['role'] = 'admin'
            session['nombre'] = nombre
            session['apellido'] = apellido
            return redirect(url_for('index'))

        # usuario común: consulta o registro
        cursor.execute("""SELECT id, password_hash
                          FROM usuarios_comunes
                          WHERE nombre=%s AND apellido=%s""",
                       (nombre, apellido))
        usuario = cursor.fetchone()
        if usuario:
            uid, pw_hash = usuario
            if check_password_hash(pw_hash, password):
                session['user_id'] = uid
                session['role'] = 'user'
                session['nombre'] = nombre
                session['apellido'] = apellido
                return redirect(url_for('index'))
            else:
                flash('Contraseña incorrecta')
        else:
            # registro automático
            hash_pw = generate_password_hash(password)
            cursor.execute("""INSERT INTO usuarios_comunes
                              (nombre, apellido, password_hash)
                              VALUES (%s, %s, %s)""",
                           (nombre, apellido, hash_pw))
            db.commit()
            session['user_id'] = cursor.lastrowid
            session['role'] = 'user'
            session['nombre'] = nombre
            session['apellido'] = apellido
            return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# 4. Rutas principales
@app.route('/', methods=['GET', 'POST'])
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    qr_filename = None  # Variable para pasar el QR a la plantilla

    if request.method == 'POST':
        file = request.files['file']
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            extension = filename.rsplit('.', 1)[1].lower()
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            token = secrets.token_urlsafe(32)

            # Generar QR apuntando a la descarga del archivo (para redirigir a lector estándar)
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(f"{BASE_URL}/download/{filename}?token={token}")  # URL de descarga
            qr.make(fit=True)
            img = qr.make_image(fill='black', back_color='white')
            qr_filename = f"{filename}.png"
            qr_path = os.path.join('static', qr_filename)
            img.save(qr_path)

            # Guardado en DB según el rol
            sql = "INSERT INTO archivos (nombre, extension, token, usuario_admin_id, usuario_comun_id) VALUES (%s,%s,%s,%s,%s)"

            if session.get('role') == 'admin':
                cursor.execute(sql, (filename, extension, token, session['user_id'], None))
            else:
                cursor.execute(sql, (filename, extension, token, None, session['user_id']))

            db.commit()

            # No redirigir, renderizar con el QR visible

    # Historial de columnas (igual que antes)
    if session.get('role') == 'admin':
        cursor.execute("""
            SELECT a.nombre, a.extension, a.fecha_subida, a.id,
                   COALESCE(uc.nombre, ua.nombre) as subido_por
            FROM archivos a
            LEFT JOIN usuarios_comunes uc ON a.usuario_comun_id = uc.id
            LEFT JOIN usuarios_admin ua ON a.usuario_admin_id = ua.id
            ORDER BY a.fecha_subida DESC
        """)
    else:
        cursor.execute("""SELECT nombre, extension, fecha_subida, id
                          FROM archivos WHERE usuario_comun_id = %s
                          ORDER BY fecha_subida DESC""",
                       (session['user_id'],))
    
    historial = cursor.fetchall()
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

@app.route('/delete/<int:id_db>')
def delete(id_db):
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    # Busca el nombre del archivo antes de borrar el registro
    cursor.execute("SELECT nombre FROM archivos WHERE id = %s", (id_db,))
    archivo = cursor.fetchone()
    
    if archivo:
        nombre_fichero = archivo[0]
        # Borrar el registro de la DB
        cursor.execute("DELETE FROM archivos WHERE id = %s", (id_db,))
        db.commit()
        
        # Borrar el archivo físico y su QR
        try:
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], nombre_fichero))
            os.remove(os.path.join('static', f"{nombre_fichero}.png"))
        except OSError:
            pass 

    return redirect(url_for('index'))

@app.route('/download/<filename>')
def download(filename):

    token = request.args.get('token')

    # Si no hay token, bloquear
    if not token:
        return "Acceso no autorizado", 403

    # Buscar token del archivo
    cursor.execute("SELECT token FROM archivos WHERE nombre=%s", (filename,))
    result = cursor.fetchone()

    if not result:
        return "Archivo no encontrado", 404

    stored_token = result[0]

    # Verificar token
    if token != stored_token:
        return "Token inválido", 403

    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

    if not os.path.exists(filepath):
        return "Archivo no encontrado", 404

    return send_file(filepath, as_attachment=True)

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)