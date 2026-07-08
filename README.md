# Kanban Operacional Aramark

Aplicación Flask lista para Render con:

- Tablero Kanban operacional.
- PostgreSQL por `DATABASE_URL`.
- Dashboard de acciones urgentes con rango máximo de 7 días.
- Múltiples responsables por acción.
- Responsables con correo y teléfono WhatsApp.
- Notificaciones por correo mediante Brevo API.
- Notificaciones opcionales por WhatsApp mediante Brevo Transactional WhatsApp.
- Historial de notificaciones.
- Exportación CSV.

## Variables principales en Render

```env
DATABASE_URL=INTERNAL_DATABASE_URL_DE_RENDER_POSTGRESQL
APP_BASE_URL=https://kanban-aramark.onrender.com
SECRET_KEY=clave_segura

EMAIL_PROVIDER=brevo
NOTIFY_EMAIL=true
BREVO_API_KEY=API_KEY_DE_BREVO
BREVO_FROM_EMAIL=jriveraaguilera@gmail.com
BREVO_FROM_NAME=Kanban Operacional Aramark
BREVO_TIMEOUT=8

NOTIFY_WHATSAPP=false
BREVO_WHATSAPP_TEMPLATE_ID=ID_TEMPLATE_APROBADA
BREVO_WHATSAPP_SENDER_NUMBER=NUMERO_WHATSAPP_BREVO
BREVO_WHATSAPP_LANGUAGE=es
BREVO_WHATSAPP_TIMEOUT=8
```

Para activar WhatsApp cambia:

```env
NOTIFY_WHATSAPP=true
```

## Formato de teléfonos

Para Chile usa formato internacional:

```text
+56912345678
```

## Flujo operativo

1. Entra a **Responsables**.
2. Crea responsables con nombre, correo y WhatsApp.
3. Marca `Notificar por correo` y/o `Notificar por WhatsApp`.
4. Crea una acción y asigna uno o varios responsables.
5. Al crear, editar o mover la acción de columna, el sistema notifica a todos los responsables asignados según sus preferencias.
6. Revisa resultados en **Notificaciones**.

## Despliegue Render

1. Sube todo a GitHub.
2. En Render configura variables de entorno.
3. Usa `Manual Deploy -> Clear build cache & deploy`.

## Nota WhatsApp

Brevo WhatsApp requiere que la cuenta de WhatsApp esté activada en Brevo y que la plantilla esté aprobada. El primer mensaje enviado por API debe usar `Template ID`.
