# Kanban Operacional Aramark

Aplicación Flask lista para Render con:

- Tablero Kanban operacional.
- PostgreSQL por `DATABASE_URL`.
- Dashboard de acciones urgentes con rango máximo de 7 días.
- Gran calendario mensual de acciones no finalizadas.
- Asignación de una misma acción a varias fechas.
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
5. Agrega una o varias fechas de ejecución/vencimiento para la misma acción.
6. Entra a **Calendario** para ver cada ocurrencia pendiente por día.
7. Al crear, editar o mover la acción de columna, el sistema notifica por correo a todos los responsables asignados con notificación activa.
8. Revisa resultados en **Notificaciones**.

## Despliegue Render

1. Sube todo a GitHub.
2. En Render configura variables de entorno.
3. Usa `Manual Deploy -> Clear build cache & deploy`.
