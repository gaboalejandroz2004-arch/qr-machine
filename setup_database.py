#!/usr/bin/env python3
"""
Script para configurar la base de datos y crear usuarios de prueba
"""
import os
import mysql.connector
from werkzeug.security import generate_password_hash

def get_db_connection():
    """Conectar a la base de datos"""
    try:
        return mysql.connector.connect(
            host=os.getenv("MYSQLHOST", "localhost"),
            user=os.getenv("MYSQLUSER", "root"),
            password=os.getenv("MYSQLPASSWORD", "29012004"),
            database=os.getenv("MYSQLDATABASE", "qr_machine"),
            port=int(os.getenv("MYSQLPORT", 3306))
        )
    except mysql.connector.Error as e:
        print(f"Error de conexión a la base de datos: {e}")
        return None

def create_tables():
    """Crear las tablas necesarias si no existen"""
    conn = get_db_connection()
    if not conn:
        print("No se pudo conectar a la base de datos")
        return False
        
    cursor = conn.cursor()
    
    try:
        # Crear tabla usuarios_comunes
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usuarios_comunes (
                id INT AUTO_INCREMENT PRIMARY KEY,
                nombre VARCHAR(50) NOT NULL,
                apellido VARCHAR(50) NOT NULL,
                password_hash VARCHAR(255) NOT NULL
            )
        """)
        
        # Crear tabla usuarios_admin
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usuarios_admin (
                id INT AUTO_INCREMENT PRIMARY KEY,
                nombre VARCHAR(50) NOT NULL,
                apellido VARCHAR(50) NOT NULL,
                password_hash VARCHAR(255) NOT NULL
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

def create_test_users():
    """Crear usuarios de prueba"""
    conn = get_db_connection()
    if not conn:
        return False
        
    cursor = conn.cursor()
    
    try:
        # Verificar si ya existen usuarios
        cursor.execute("SELECT COUNT(*) FROM usuarios_admin")
        admin_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM usuarios_comunes")
        user_count = cursor.fetchone()[0]
        
        if admin_count == 0:
            # Crear usuario admin de prueba
            admin_password_hash = generate_password_hash("admin123")
            cursor.execute("""
                INSERT INTO usuarios_admin (nombre, apellido, password_hash) 
                VALUES (%s, %s, %s)
            """, ("admin", "test", admin_password_hash))
            print("✓ Usuario admin creado: usuario='admin', contraseña='admin123', token='GABRIEL_2026'")
        
        if user_count == 0:
            # Crear usuario común de prueba
            user_password_hash = generate_password_hash("user123")
            cursor.execute("""
                INSERT INTO usuarios_comunes (nombre, apellido, password_hash) 
                VALUES (%s, %s, %s)
            """, ("user", "test", user_password_hash))
            print("✓ Usuario común creado: usuario='user', contraseña='user123'")
        
        conn.commit()
        return True
        
    except Exception as e:
        print(f"Error creando usuarios de prueba: {e}")
        return False
    finally:
        cursor.close()
        conn.close()

def test_connection():
    """Probar la conexión a la base de datos"""
    print("Probando conexión a la base de datos...")
    conn = get_db_connection()
    if conn:
        print("✓ Conexión exitosa")
        conn.close()
        return True
    else:
        print("✗ Error de conexión")
        return False

if __name__ == "__main__":
    print("=== CONFIGURACIÓN DE BASE DE DATOS ===")
    
    if not test_connection():
        print("No se puede continuar sin conexión a la base de datos")
        exit(1)
    
    if create_tables():
        create_test_users()
        print("\n=== CONFIGURACIÓN COMPLETADA ===")
        print("Ahora puedes iniciar sesión con:")
        print("- Admin: usuario='admin', contraseña='admin123', token='GABRIEL_2026'")
        print("- Usuario: usuario='user', contraseña='user123'")
    else:
        print("Error en la configuración")
        exit(1)