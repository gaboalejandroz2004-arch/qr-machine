#!/usr/bin/env python3
"""
Script para inicializar la base de datos en producción (Render/Railway)
"""
import os
import mysql.connector
from werkzeug.security import generate_password_hash

def get_db_connection():
    """Conectar a la base de datos usando variables de entorno"""
    try:
        return mysql.connector.connect(
            host=os.getenv("MYSQLHOST"),
            user=os.getenv("MYSQLUSER"),
            password=os.getenv("MYSQLPASSWORD"),
            database=os.getenv("MYSQLDATABASE"),
            port=int(os.getenv("MYSQLPORT", 3306))
        )
    except mysql.connector.Error as e:
        print(f"Error de conexión a la base de datos: {e}")
        return None

def create_tables():
    """Crear las tablas necesarias"""
    conn = get_db_connection()
    if not conn:
        print("No se pudo conectar a la base de datos")
        return False
        
    cursor = conn.cursor()
    
    try:
        print("Creando tablas...")
        
        # Crear tabla usuarios_comunes
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usuarios_comunes (
                id INT AUTO_INCREMENT PRIMARY KEY,
                nombre VARCHAR(50) NOT NULL,
                apellido VARCHAR(50) NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                UNIQUE KEY unique_nombre (nombre)
            )
        """)
        
        # Crear tabla usuarios_admin
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usuarios_admin (
                id INT AUTO_INCREMENT PRIMARY KEY,
                nombre VARCHAR(50) NOT NULL,
                apellido VARCHAR(50) NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                UNIQUE KEY unique_nombre (nombre)
            )
        """)
        
        # Crear tabla archivos
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS archivos (
                id INT AUTO_INCREMENT PRIMARY KEY,
                nombre VARCHAR(255) NOT NULL,
                extension VARCHAR(10),
                fecha_subida DATETIME DEFAULT CURRENT_TIMESTAMP,
                usuario_comun_id INT NULL,
                usuario_admin_id INT NULL,
                INDEX idx_usuario_comun (usuario_comun_id),
                INDEX idx_usuario_admin (usuario_admin_id),
                CONSTRAINT fk_arch_comun FOREIGN KEY (usuario_comun_id) 
                    REFERENCES usuarios_comunes(id) ON DELETE SET NULL,
                CONSTRAINT fk_arch_admin FOREIGN KEY (usuario_admin_id) 
                    REFERENCES usuarios_admin(id) ON DELETE SET NULL
            )
        """)
        
        conn.commit()
        print("✓ Tablas creadas exitosamente")
        return True
        
    except Exception as e:
        print(f"Error creando tablas: {e}")
        return False
    finally:
        cursor.close()
        conn.close()

def create_admin_user():
    """Crear usuario administrador por defecto"""
    conn = get_db_connection()
    if not conn:
        return False
        
    cursor = conn.cursor()
    
    try:
        # Verificar si ya existe un admin
        cursor.execute("SELECT COUNT(*) FROM usuarios_admin WHERE nombre = 'admin'")
        if cursor.fetchone()[0] > 0:
            print("Usuario admin ya existe")
            return True
        
        # Crear usuario admin
        admin_password_hash = generate_password_hash("admin123")
        cursor.execute("""
            INSERT INTO usuarios_admin (nombre, apellido, password_hash) 
            VALUES (%s, %s, %s)
        """, ("admin", "system", admin_password_hash))
        
        conn.commit()
        print("✓ Usuario admin creado: usuario='admin', contraseña='admin123', token='GABRIEL_2026'")
        return True
        
    except Exception as e:
        print(f"Error creando usuario admin: {e}")
        return False
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    print("=== INICIALIZACIÓN DE BASE DE DATOS EN PRODUCCIÓN ===")
    
    # Verificar variables de entorno
    required_vars = ["MYSQLHOST", "MYSQLUSER", "MYSQLPASSWORD", "MYSQLDATABASE"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        print(f"Error: Faltan variables de entorno: {', '.join(missing_vars)}")
        exit(1)
    
    print(f"Conectando a: {os.getenv('MYSQLHOST')}:{os.getenv('MYSQLPORT', 3306)}")
    
    if create_tables():
        create_admin_user()
        print("\n=== INICIALIZACIÓN COMPLETADA ===")
        print("Base de datos lista para producción")
    else:
        print("Error en la inicialización")
        exit(1)