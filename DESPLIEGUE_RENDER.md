# Guía de Despliegue en Render/Railway

## Problemas Identificados y Solucionados

### 1. **Configuración de Base de Datos en Producción**
- Agregué manejo robusto de variables de entorno
- Creé health check endpoint (`/health`)
- Separé lógica de desarrollo vs producción

### 2. **Archivos de Configuración Actualizados**
- `render.yaml`: Configuración específica para Render
- `requirements.txt`: Versiones específicas de dependencias
- `init_production_db.py`: Script de inicialización para producción

## Pasos para Desplegar en Render

### 1. **Configurar Base de Datos**
1. En Render Dashboard, crear una nueva PostgreSQL/MySQL database
2. Anotar las credenciales de conexión

### 2. **Configurar Variables de Entorno**
En el panel de Render, agregar estas variables:
```
ENVIRONMENT=production
MYSQLHOST=tu-host-de-bd
MYSQLUSER=tu-usuario-bd
MYSQLPASSWORD=tu-password-bd
MYSQLDATABASE=qr_machine
MYSQLPORT=3306
```

### 3. **Desplegar la Aplicación**
1. Conectar tu repositorio GitHub a Render
2. Seleccionar "Web Service"
3. Configurar:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`
   - **Health Check Path**: `/health`

### 4. **Inicializar Base de Datos**
Después del primer despliegue, ejecutar:
```bash
python init_production_db.py
```

## Pasos para Railway

### 1. **Conectar Repositorio**
1. Ir a Railway.app
2. "New Project" → "Deploy from GitHub repo"
3. Seleccionar tu repositorio

### 2. **Agregar Base de Datos**
1. "Add Service" → "Database" → "MySQL"
2. Railway generará automáticamente las variables de entorno

### 3. **Configurar Variables Adicionales**
```
ENVIRONMENT=production
```

### 4. **Verificar Despliegue**
Railway detectará automáticamente el `Procfile` y desplegará.

## Verificación del Funcionamiento

### 1. **Health Check**
Visitar: `https://tu-app.onrender.com/health`
Debe retornar: `{"status": "healthy", "database": "connected"}`

### 2. **Página Principal**
Visitar: `https://tu-app.onrender.com/`
Debe redirigir a `/login`

### 3. **Login de Prueba**
- Usuario: `admin`
- Contraseña: `admin123`
- Token: `GABRIEL_2026`

## Solución de Problemas Comunes

### Error 503 - Service Unavailable
- Verificar que las variables de entorno estén configuradas
- Revisar logs en Render/Railway dashboard
- Verificar conexión a base de datos con `/health`

### Error de Conexión a BD
- Verificar credenciales en variables de entorno
- Asegurar que la BD esté en la misma región
- Verificar que el puerto sea correcto (3306 para MySQL)

### Aplicación no inicia
- Revisar `requirements.txt` para dependencias faltantes
- Verificar que `gunicorn` esté instalado
- Revisar logs de build en el dashboard

## Comandos Útiles

### Ver logs en tiempo real (Railway)
```bash
railway logs
```

### Ejecutar comando en producción (Railway)
```bash
railway run python init_production_db.py
```

### Reiniciar servicio (Render)
Usar el botón "Manual Deploy" en el dashboard.

## Notas Importantes

1. **Nunca** hardcodear credenciales en el código
2. Usar siempre variables de entorno para configuración
3. El health check es crucial para que Render detecte que la app está funcionando
4. Los logs están disponibles en los dashboards de ambas plataformas