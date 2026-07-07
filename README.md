# Kanban Operacional Aramark

App Flask tipo Kanban para gestión visual de tareas operativas del Campamento 5400.

## Funciones principales

- Crear, editar, eliminar y mover tareas por columnas.
- Columnas: Pendiente, En proceso, En revisión, Bloqueado y Finalizado.
- Responsable, correo responsable, área, prioridad y fecha límite.
- Exportación CSV.
- Diseño adaptado a pantalla completa sin barra horizontal inferior.
- Notificaciones por correo en segundo plano.
- Soporte recomendado para Brevo por API HTTPS.
- SMTP queda disponible como respaldo opcional.

## Configuración recomendada en Render para Brevo

En Render, entra a tu servicio web y abre **Environment**. Agrega estas variables:

```env
EMAIL_PROVIDER=brevo
NOTIFY_EMAIL=true
BREVO_API_KEY=TU_API_KEY_DE_BREVO
BREVO_FROM_EMAIL=correo_verificado_en_brevo@dominio.com
BREVO_FROM_NAME=Kanban Operacional Aramark
BREVO_TIMEOUT=8
APP_BASE_URL=https://kanban-aramark.onrender.com
DATABASE_PATH=/var/data/aramark_kanban.db
```

Después presiona **Save, rebuild, and deploy**.

### Importante sobre `BREVO_FROM_EMAIL`

El correo remitente debe estar autorizado/verificado en Brevo. Puede ser un Gmail o un correo corporativo, pero Brevo puede pedir validarlo antes de permitir envíos.

## Botón de prueba

La pantalla principal incluye una sección **Estado de notificaciones** y un botón **Probar correo**. Úsalo para validar Brevo sin crear tareas falsas.

## SMTP opcional

Si en algún momento quieres volver a SMTP, configura:

```env
EMAIL_PROVIDER=smtp
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=tu_correo@gmail.com
SMTP_PASSWORD=clave_de_aplicacion
SMTP_FROM=tu_correo@gmail.com
SMTP_SSL=false
SMTP_TIMEOUT=8
APP_BASE_URL=https://kanban-aramark.onrender.com
```

En Render se recomienda Brevo porque usa HTTPS y evita bloqueos frecuentes de puertos SMTP.
