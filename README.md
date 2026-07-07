# Kanban Operacional Aramark

Aplicación web Flask lista para Render.com, con estética corporativa roja y logos Aramark / Escondida BHP.

## Funciones

- Tablero Kanban con columnas: Pendiente, En proceso, En revisión, Bloqueado y Finalizado.
- Crear, editar, eliminar y mover tareas con arrastrar y soltar.
- Campos por tarea: título, descripción, estado, prioridad, responsable, correo del responsable, área y fecha límite.
- Métricas superiores: total de tareas, finalizadas, bloqueadas, vencidas y avance.
- Filtros por búsqueda, área, prioridad y responsable.
- Exportación CSV.
- Notificaciones por correo al responsable cuando se crea, asigna, edita o mueve una tarea, siempre que SMTP esté configurado.
- Persistencia SQLite en disco de Render (`/var/data/aramark_kanban.db`).

## Despliegue en Render

1. Sube todos los archivos a un repositorio de GitHub.
2. En Render crea un **Web Service** desde ese repositorio.
3. Render leerá `render.yaml` automáticamente.
4. Ejecuta **Manual Deploy → Clear build cache & deploy** si reemplazas una versión anterior.

## Comandos locales

```bash
pip install -r requirements.txt
python app.py
```

Luego abre `http://127.0.0.1:5000`.


## Configuración de correos

La app permite registrar el **correo del responsable** en cada tarea. Para que Render envíe correos debes configurar estas variables de entorno:

| Variable | Descripción |
|---|---|
| `SMTP_HOST` | Servidor SMTP, por ejemplo `smtp.gmail.com` o el SMTP corporativo. |
| `SMTP_PORT` | Puerto SMTP. Usualmente `587` con TLS. |
| `SMTP_USER` | Usuario de la cuenta SMTP. |
| `SMTP_PASSWORD` | Contraseña o app password de la cuenta SMTP. |
| `SMTP_FROM` | Correo remitente visible. |
| `SMTP_SSL` | `true` solo si usas SMTP SSL directo, normalmente en puerto 465. Con puerto 587 dejar `false`. |
| `APP_BASE_URL` | URL pública de la app en Render, para incluir link directo a la tarea. |
| `SMTP_TIMEOUT` | Tiempo máximo de espera SMTP en segundos. Recomendado: `4` u `8`. |
| `SMTP_FORCE_IPV4` | Fuerza conexión IPv4 para evitar errores `[Errno 101] Network is unreachable`. Recomendado: `true`. |

Si estas variables no están configuradas, la aplicación sigue funcionando normalmente, pero mostrará un aviso y no enviará notificaciones.

## Edición de tareas

El botón **Editar** abre una página dedicada para evitar problemas de modales dentro de tarjetas arrastrables. Desde ahí se modifican responsable, correo, prioridad, estado, área y fecha límite.


## Movimiento de tareas

El arrastre de tarjetas usa el endpoint `/api/mover` con JSON `{task_id, status}`. También se mantiene `/mover/<id>` por compatibilidad. Esta versión evita errores intermitentes tipo Not Found al mover tarjetas porque valida el ID de tarea y el estado antes de actualizar.


## Rendimiento al crear tareas

El envío de correos se realiza en segundo plano para que crear, editar o mover una tarea no quede esperando la respuesta del servidor SMTP.

Variable opcional:

```env
SMTP_TIMEOUT=4
```

Si el servidor de correo corporativo demora o rechaza la conexión, la tarea igual queda guardada inmediatamente y el error se registra en los logs de Render.

### Gmail recomendado en Render

Si usas Gmail, comienza con esta configuración:

```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=465
SMTP_USER=tu_gmail@gmail.com
SMTP_PASSWORD=clave_de_aplicacion_sin_espacios
SMTP_FROM=tu_gmail@gmail.com
SMTP_SSL=true
SMTP_TIMEOUT=8
SMTP_FORCE_IPV4=true
APP_BASE_URL=https://kanban-aramark.onrender.com
```

Esta versión fuerza IPv4 por defecto. Si en los logs aparece `Network is unreachable`, normalmente significa que el contenedor no logra abrir conexión al servidor SMTP. Si con `SMTP_FORCE_IPV4=true` sigue fallando, conviene usar un proveedor de correo por API HTTPS.
