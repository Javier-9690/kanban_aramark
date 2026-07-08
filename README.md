# Kanban Operacional Aramark

Aplicación Flask lista para Render con:

- Tablero Kanban operacional.
- PostgreSQL por `DATABASE_URL`.
- Dashboard de acciones urgentes con rango máximo de 7 días.
- Múltiples responsables por acción.
- Responsables con correo.
- Notificaciones por correo mediante Brevo API.
- Historial de notificaciones por correo.
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
```

## Flujo operativo

1. Entra a **Responsables**.
2. Crea responsables con nombre y correo.
3. Marca `Notificar por correo` si quieres que ese responsable reciba avisos automáticos.
4. Crea una acción y asigna uno o varios responsables.
5. Al crear, editar o mover la acción de columna, el sistema notifica por correo a todos los responsables asignados con notificación activa.
6. Revisa resultados en **Notificaciones**.

## Despliegue Render

1. Sube todo a GitHub.
2. En Render configura variables de entorno.
3. Usa `Manual Deploy -> Clear build cache & deploy`.
