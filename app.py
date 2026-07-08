# -*- coding: utf-8 -*-
import csv
import html as html_lib
import io
import json
import os
import sqlite3
import threading
import urllib.error
import urllib.request
from datetime import datetime, date, timedelta

from flask import Flask, Response, flash, jsonify, redirect, render_template, request, url_for

APP_TITLE = "Kanban Operacional Aramark"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_URL = (os.environ.get("DATABASE_URL") or "").strip()
DB_PATH = os.environ.get("DATABASE_PATH", "/var/data/aramark_kanban.db")
if not os.path.exists(os.path.dirname(DB_PATH)):
    DB_PATH = os.path.join(BASE_DIR, "aramark_kanban.db")

STATUSES = [
    ("pendiente", "Pendiente"),
    ("en_proceso", "En proceso"),
    ("revision", "En revisión"),
    ("bloqueado", "Bloqueado"),
    ("finalizado", "Finalizado"),
]
STATUS_LABELS = dict(STATUSES)
STATUS_KEYS = [s[0] for s in STATUSES]
PRIORITIES = ["Alta", "Media", "Baja"]
PRIORITY_RANK = {"Alta": 0, "Media": 1, "Baja": 2}
AREAS = ["Calidad", "Hotelería", "Food", "Facility", "Prevención de riesgos", "RRHH", "Gerencia"]

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "cambiar-esta-clave-en-render")


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def is_postgres():
    return DATABASE_URL.lower().startswith(("postgres://", "postgresql://"))


def get_conn():
    if is_postgres():
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("Falta instalar psycopg. Revisa requirements.txt y vuelve a desplegar en Render.") from exc
        return psycopg.connect(DATABASE_URL, row_factory=dict_row)
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def adapt_sql(sql):
    return sql.replace("?", "%s") if is_postgres() else sql


def row_as_dict(row):
    if row is None:
        return None
    return dict(row)


def query_all(sql, params=()):
    conn = get_conn()
    try:
        if is_postgres():
            with conn.cursor() as cur:
                cur.execute(adapt_sql(sql), tuple(params))
                rows = cur.fetchall()
        else:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [row_as_dict(row) for row in rows]
    finally:
        conn.close()


def query_one(sql, params=()):
    conn = get_conn()
    try:
        if is_postgres():
            with conn.cursor() as cur:
                cur.execute(adapt_sql(sql), tuple(params))
                row = cur.fetchone()
        else:
            row = conn.execute(sql, tuple(params)).fetchone()
        return row_as_dict(row)
    finally:
        conn.close()


def execute_write(sql, params=()):
    conn = get_conn()
    try:
        if is_postgres():
            with conn.cursor() as cur:
                cur.execute(adapt_sql(sql), tuple(params))
                rowcount = cur.rowcount
            conn.commit()
        else:
            cur = conn.execute(sql, tuple(params))
            rowcount = cur.rowcount
            conn.commit()
        return rowcount
    finally:
        conn.close()


def execute_returning(sql, params=()):
    conn = get_conn()
    try:
        if is_postgres():
            with conn.cursor() as cur:
                cur.execute(adapt_sql(sql), tuple(params))
                row = cur.fetchone()
            conn.commit()
            return row_as_dict(row)
        cur = conn.execute(sql, tuple(params))
        conn.commit()
        return {"id": cur.lastrowid}
    finally:
        conn.close()


def execute_script(statements):
    conn = get_conn()
    try:
        if is_postgres():
            with conn.cursor() as cur:
                for sql in statements:
                    cur.execute(sql)
            conn.commit()
        else:
            for sql in statements:
                conn.execute(sql)
            conn.commit()
    finally:
        conn.close()


def sqlite_add_column_if_missing(table, column, definition):
    if is_postgres():
        return
    conn = get_conn()
    try:
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            conn.commit()
    finally:
        conn.close()


def init_db():
    if is_postgres():
        execute_script([
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                status TEXT NOT NULL DEFAULT 'pendiente',
                priority TEXT NOT NULL DEFAULT 'Media',
                assignee TEXT,
                assignee_email TEXT,
                area TEXT,
                due_date TEXT,
                position INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS assignee_email TEXT",
            """
            CREATE TABLE IF NOT EXISTS responsables (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT,
                area TEXT,
                notify_email BOOLEAN NOT NULL DEFAULT TRUE,
                active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            "ALTER TABLE responsables ADD COLUMN IF NOT EXISTS notify_email BOOLEAN NOT NULL DEFAULT TRUE",
            "ALTER TABLE responsables ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE",
            """
            CREATE TABLE IF NOT EXISTS task_responsibles (
                task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                responsible_id INTEGER NOT NULL REFERENCES responsables(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                PRIMARY KEY (task_id, responsible_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS notification_logs (
                id SERIAL PRIMARY KEY,
                channel TEXT NOT NULL,
                event_type TEXT NOT NULL,
                task_id INTEGER,
                responsible_id INTEGER,
                recipient TEXT,
                result TEXT NOT NULL,
                detail TEXT,
                created_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_tasks_status_position ON tasks(status, position)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks(due_date)",
            "CREATE INDEX IF NOT EXISTS idx_resp_name ON responsables(name)",
            "CREATE INDEX IF NOT EXISTS idx_task_resp_task ON task_responsibles(task_id)",
            "CREATE INDEX IF NOT EXISTS idx_notify_logs_task ON notification_logs(task_id)",
        ])
        return

    execute_script([
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT NOT NULL DEFAULT 'pendiente',
            priority TEXT NOT NULL DEFAULT 'Media',
            assignee TEXT,
            assignee_email TEXT,
            area TEXT,
            due_date TEXT,
            position INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS responsables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT,
            area TEXT,
            notify_email INTEGER NOT NULL DEFAULT 1,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS task_responsibles (
            task_id INTEGER NOT NULL,
            responsible_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (task_id, responsible_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS notification_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT NOT NULL,
            event_type TEXT NOT NULL,
            task_id INTEGER,
            responsible_id INTEGER,
            recipient TEXT,
            result TEXT NOT NULL,
            detail TEXT,
            created_at TEXT NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_tasks_status_position ON tasks(status, position)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks(due_date)",
        "CREATE INDEX IF NOT EXISTS idx_resp_name ON responsables(name)",
        "CREATE INDEX IF NOT EXISTS idx_task_resp_task ON task_responsibles(task_id)",
        "CREATE INDEX IF NOT EXISTS idx_notify_logs_task ON notification_logs(task_id)",
    ])
    sqlite_add_column_if_missing("tasks", "assignee_email", "TEXT")
    sqlite_add_column_if_missing("responsables", "notify_email", "INTEGER NOT NULL DEFAULT 1")
    sqlite_add_column_if_missing("responsables", "active", "INTEGER NOT NULL DEFAULT 1")


def env_text(name, default=""):
    return (os.environ.get(name) or default or "").strip()


def env_bool(name, default=False):
    value = (os.environ.get(name) or "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "si", "sí", "on"}


def bool_to_db(value):
    if is_postgres():
        return bool(value)
    return 1 if value else 0


def db_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).lower() in {"1", "true", "yes", "si", "sí", "on"}


def notifications_active():
    return env_bool("NOTIFY_EMAIL", default=True)



def app_base_url():
    return env_text("APP_BASE_URL").rstrip("/")


def brevo_sender_email():
    return env_text("BREVO_FROM_EMAIL") or env_text("EMAIL_FROM")


def brevo_enabled():
    return bool(env_text("BREVO_API_KEY") and brevo_sender_email())


def email_enabled():
    return notifications_active() and brevo_enabled()




def parse_due_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        return None


def normalize_status(value):
    return value if value in STATUS_KEYS else "pendiente"


def normalize_priority(value):
    return value if value in PRIORITIES else "Media"


def next_position(status):
    row = query_one("SELECT COALESCE(MAX(position), 0) + 1 AS pos FROM tasks WHERE status = ?", (status,))
    return int(row.get("pos") or 1) if row else 1


def active_responsibles():
    rows = query_all("SELECT * FROM responsables WHERE active = ? ORDER BY name", (bool_to_db(True),))
    for r in rows:
        r["notify_email"] = db_bool(r.get("notify_email"))
        r["active"] = db_bool(r.get("active"))
    return rows


def all_responsibles():
    rows = query_all("SELECT * FROM responsables ORDER BY active DESC, name")
    for r in rows:
        r["notify_email"] = db_bool(r.get("notify_email"))
        r["active"] = db_bool(r.get("active"))
    return rows


def get_responsible(responsible_id):
    row = query_one("SELECT * FROM responsables WHERE id = ?", (responsible_id,))
    if row:
        row["notify_email"] = db_bool(row.get("notify_email"))
        row["active"] = db_bool(row.get("active"))
    return row


def get_task_responsibles(task_id):
    rows = query_all(
        """
        SELECT r.* FROM responsables r
        JOIN task_responsibles tr ON tr.responsible_id = r.id
        WHERE tr.task_id = ?
        ORDER BY r.name
        """,
        (task_id,),
    )
    for r in rows:
        r["notify_email"] = db_bool(r.get("notify_email"))
        r["active"] = db_bool(r.get("active"))
    return rows


def refresh_task_legacy_fields(task_id):
    responsibles = get_task_responsibles(task_id)
    names = ", ".join([r.get("name") or "" for r in responsibles if r.get("name")])
    emails = ", ".join([r.get("email") or "" for r in responsibles if r.get("email")])
    execute_write("UPDATE tasks SET assignee = ?, assignee_email = ? WHERE id = ?", (names, emails, task_id))


def assign_responsibles(task_id, responsible_ids):
    ids = []
    for value in responsible_ids or []:
        try:
            rid = int(value)
            if rid not in ids:
                ids.append(rid)
        except (TypeError, ValueError):
            continue
    execute_write("DELETE FROM task_responsibles WHERE task_id = ?", (task_id,))
    for rid in ids:
        execute_write(
            "INSERT INTO task_responsibles (task_id, responsible_id, created_at) VALUES (?, ?, ?)",
            (task_id, rid, now_text()),
        )
    refresh_task_legacy_fields(task_id)
    return ids


def row_to_dict(row):
    item = dict(row)
    item["status_label"] = STATUS_LABELS.get(item.get("status"), item.get("status"))
    item["is_overdue"] = False
    item["days_until_due"] = None
    due = parse_due_date(item.get("due_date"))
    if due:
        item["days_until_due"] = (due - date.today()).days
        item["is_overdue"] = item.get("status") != "finalizado" and due < date.today()
    responsibles = get_task_responsibles(item.get("id")) if item.get("id") else []
    item["responsibles"] = responsibles
    item["responsible_ids"] = [str(r["id"]) for r in responsibles]
    item["responsible_names"] = ", ".join([r.get("name") or "" for r in responsibles if r.get("name")]) or item.get("assignee") or ""
    item["responsible_emails"] = ", ".join([r.get("email") or "" for r in responsibles if r.get("email")]) or item.get("assignee_email") or ""
    return item


def load_tasks(filters=None):
    filters = filters or {}
    where = []
    params = []
    q = (filters.get("q") or "").strip()
    area = (filters.get("area") or "").strip()
    priority = (filters.get("priority") or "").strip()
    assignee = (filters.get("assignee") or "").strip()
    like_operator = "ILIKE" if is_postgres() else "LIKE"

    if q:
        where.append(f"(title {like_operator} ? OR description {like_operator} ? OR assignee {like_operator} ? OR assignee_email {like_operator} ? OR area {like_operator} ?)")
        like = f"%{q}%"
        params.extend([like, like, like, like, like])
    if area:
        where.append("area = ?")
        params.append(area)
    if priority:
        where.append("priority = ?")
        params.append(priority)
    if assignee:
        where.append(f"assignee {like_operator} ?")
        params.append(f"%{assignee}%")

    sql = "SELECT * FROM tasks"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY status, position, updated_at DESC"
    rows = query_all(sql, params)
    return [row_to_dict(row) for row in rows]


def board_from_tasks(tasks):
    board = {key: [] for key, _ in STATUSES}
    for task in tasks:
        board.setdefault(task["status"], []).append(task)
    return board


def metrics_from_tasks(tasks):
    total = len(tasks)
    finalizados = sum(1 for t in tasks if t["status"] == "finalizado")
    bloqueados = sum(1 for t in tasks if t["status"] == "bloqueado")
    vencidos = sum(1 for t in tasks if t.get("is_overdue"))
    avance = round((finalizados / total) * 100, 1) if total else 0.0
    return {"total": total, "finalizados": finalizados, "bloqueados": bloqueados, "vencidos": vencidos, "avance": avance}


def urgent_dashboard_from_tasks(tasks, window_days=7):
    today = date.today()
    end_date = today + timedelta(days=window_days)
    urgent = []
    for task in tasks:
        if task.get("status") == "finalizado":
            continue
        due = parse_due_date(task.get("due_date"))
        if not due:
            continue
        if due <= end_date:
            days = (due - today).days
            item = dict(task)
            item["days_until_due"] = days
            if days < 0:
                item["urgency_label"] = "Vencida"
                item["urgency_class"] = "danger"
            elif days == 0:
                item["urgency_label"] = "Vence hoy"
                item["urgency_class"] = "danger"
            elif days <= 3:
                item["urgency_label"] = f"Vence en {days} día{'s' if days != 1 else ''}"
                item["urgency_class"] = "warning"
            else:
                item["urgency_label"] = f"Vence en {days} días"
                item["urgency_class"] = "normal"
            urgent.append(item)

    urgent.sort(key=lambda t: (
        0 if t.get("days_until_due", 0) < 0 else 1,
        t.get("days_until_due", 9999),
        0 if t.get("status") == "bloqueado" else 1,
        PRIORITY_RANK.get(t.get("priority"), 9),
        (t.get("area") or ""),
        (t.get("title") or "").lower(),
    ))
    return {
        "today": today.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "window_days": window_days,
        "tasks": urgent,
        "overdue": sum(1 for t in urgent if t.get("days_until_due", 0) < 0),
        "due_today": sum(1 for t in urgent if t.get("days_until_due") == 0),
        "due_week": sum(1 for t in urgent if 0 <= (t.get("days_until_due") or 0) <= window_days),
        "high_priority": sum(1 for t in urgent if t.get("priority") == "Alta"),
        "blocked": sum(1 for t in urgent if t.get("status") == "bloqueado"),
    }


def get_task(task_id):
    row = query_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    return row_to_dict(row) if row else None


def task_url(task):
    base_url = app_base_url()
    return f"{base_url}/editar/{task['id']}" if base_url and task.get("id") else ""


def compose_notification_text(task, intro, changes=None):
    lines = [
        intro,
        "",
        f"Tarea: {task.get('title') or ''}",
        f"Estado: {STATUS_LABELS.get(task.get('status'), task.get('status') or '')}",
        f"Prioridad: {task.get('priority') or ''}",
        f"Responsables: {task.get('responsible_names') or task.get('assignee') or 'Sin responsable'}",
        f"Área: {task.get('area') or 'Sin área'}",
        f"Fecha límite: {task.get('due_date') or 'Sin fecha'}",
    ]
    if changes:
        lines.extend(["", "Cambios registrados:"])
        lines.extend([f"- {item}" for item in changes])
    if task_url(task):
        lines.extend(["", f"Abrir tarea: {task_url(task)}"])
    lines.extend(["", "Kanban Operacional Aramark - Campamento 5400"])
    return "\n".join(lines)


def compose_task_email(task, intro, changes=None):
    text_content = compose_notification_text(task, intro, changes)
    esc = lambda value: html_lib.escape(str(value or ""))
    change_html = ""
    if changes:
        change_html = "<h3>Cambios registrados</h3><ul>" + "".join(f"<li>{esc(item)}</li>" for item in changes) + "</ul>"
    url = task_url(task)
    button_html = f'<p><a href="{esc(url)}" style="display:inline-block;background:#ed1b2e;color:#ffffff;padding:10px 14px;border-radius:5px;text-decoration:none;font-weight:bold;">Abrir tarea</a></p>' if url else ""
    html_content = f"""
    <html>
      <body style="font-family:Arial,Helvetica,sans-serif;color:#303030;line-height:1.45;">
        <div style="border-top:6px solid #ed1b2e;background:#ffffff;padding:18px;border:1px solid #eee;max-width:680px;">
          <h2 style="margin-top:0;color:#202020;">Kanban Operacional Aramark</h2>
          <p>{esc(intro)}</p>
          <table style="border-collapse:collapse;width:100%;font-size:14px;">
            <tr><td style="padding:7px;border-bottom:1px solid #eee;font-weight:bold;">Tarea</td><td style="padding:7px;border-bottom:1px solid #eee;">{esc(task.get('title'))}</td></tr>
            <tr><td style="padding:7px;border-bottom:1px solid #eee;font-weight:bold;">Estado</td><td style="padding:7px;border-bottom:1px solid #eee;">{esc(STATUS_LABELS.get(task.get('status'), task.get('status') or ''))}</td></tr>
            <tr><td style="padding:7px;border-bottom:1px solid #eee;font-weight:bold;">Prioridad</td><td style="padding:7px;border-bottom:1px solid #eee;">{esc(task.get('priority'))}</td></tr>
            <tr><td style="padding:7px;border-bottom:1px solid #eee;font-weight:bold;">Responsables</td><td style="padding:7px;border-bottom:1px solid #eee;">{esc(task.get('responsible_names') or task.get('assignee'))}</td></tr>
            <tr><td style="padding:7px;border-bottom:1px solid #eee;font-weight:bold;">Área</td><td style="padding:7px;border-bottom:1px solid #eee;">{esc(task.get('area'))}</td></tr>
            <tr><td style="padding:7px;border-bottom:1px solid #eee;font-weight:bold;">Fecha límite</td><td style="padding:7px;border-bottom:1px solid #eee;">{esc(task.get('due_date') or 'Sin fecha')}</td></tr>
          </table>
          {change_html}
          {button_html}
          <p style="font-size:12px;color:#777;margin-top:18px;">Campamento 5400 · Notificación automática.</p>
        </div>
      </body>
    </html>
    """
    return text_content, html_content


def log_notification(channel, event_type, task_id, responsible_id, recipient, result, detail=""):
    try:
        execute_write(
            """
            INSERT INTO notification_logs (channel, event_type, task_id, responsible_id, recipient, result, detail, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (channel, event_type, task_id, responsible_id, recipient, result, detail[:1000] if detail else "", now_text()),
        )
    except Exception as exc:
        app.logger.warning("No se pudo registrar log de notificación: %s", exc)


def send_brevo_email_sync(recipient, recipient_name, subject, text_content, html_content, task_id=None, responsible_id=None, event_type="task"):
    api_key = env_text("BREVO_API_KEY")
    sender_email = brevo_sender_email()
    sender_name = env_text("BREVO_FROM_NAME", "Kanban Operacional Aramark")
    timeout = float(env_text("BREVO_TIMEOUT", "8"))
    if not api_key or not sender_email:
        log_notification("email", event_type, task_id, responsible_id, recipient, "error", "Falta BREVO_API_KEY o BREVO_FROM_EMAIL")
        return False, "Brevo no configurado."
    payload = {
        "sender": {"name": sender_name, "email": sender_email},
        "to": [{"email": recipient, "name": recipient_name or recipient}],
        "subject": subject,
        "htmlContent": html_content,
        "textContent": text_content,
    }
    reply_to = env_text("BREVO_REPLY_TO")
    if reply_to:
        payload["replyTo"] = {"email": reply_to}
    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=json.dumps(payload).encode("utf-8"),
        headers={"accept": "application/json", "api-key": api_key, "content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", "ignore")
            if not (200 <= response.status < 300):
                raise RuntimeError(f"Brevo respondió HTTP {response.status}: {body}")
            log_notification("email", event_type, task_id, responsible_id, recipient, "enviado", body[:500])
            app.logger.info("Correo enviado por Brevo a %s", recipient)
            return True, "Correo enviado por Brevo."
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "ignore")
        log_notification("email", event_type, task_id, responsible_id, recipient, "error", f"HTTP {exc.code}: {body[:800]}")
        app.logger.exception("Brevo rechazó el correo a %s. HTTP %s: %s", recipient, exc.code, body)
        return False, f"Brevo HTTP {exc.code}: {body[:500]}"
    except Exception as exc:
        log_notification("email", event_type, task_id, responsible_id, recipient, "error", str(exc))
        app.logger.exception("No se pudo enviar correo por Brevo a %s: %s", recipient, exc)
        return False, str(exc)


def notify_task(task, subject, intro, changes=None, event_type="task", event_label="Actualización de acción"):
    if not task:
        return
    task_copy = dict(task)
    responsibles = task_copy.get("responsibles") or get_task_responsibles(task_copy.get("id"))
    changes_copy = list(changes or [])

    def worker():
        with app.app_context():
            text_content, html_content = compose_task_email(task_copy, intro, changes_copy)
            for responsible in responsibles:
                rid = responsible.get("id")
                if email_enabled() and db_bool(responsible.get("notify_email")) and responsible.get("email"):
                    send_brevo_email_sync(
                        responsible.get("email"),
                        responsible.get("name"),
                        subject,
                        text_content,
                        html_content,
                        task_id=task_copy.get("id"),
                        responsible_id=rid,
                        event_type=event_type,
                    )

    threading.Thread(target=worker, daemon=True).start()


def responsible_record_from_form(form):
    name = (form.get("name") or "").strip()
    if not name:
        raise ValueError("El nombre del responsable es obligatorio.")
    return {
        "name": name,
        "email": (form.get("email") or "").strip(),
        "area": (form.get("area") or "").strip(),
        "notify_email": bool_to_db(form.get("notify_email") == "on"),
        "active": bool_to_db(form.get("active") == "on"),
    }


def task_record_from_form(form, current_status="pendiente"):
    title = (form.get("title") or "").strip()
    if not title:
        raise ValueError("El título de la tarea es obligatorio.")
    return {
        "title": title,
        "description": (form.get("description") or "").strip(),
        "status": normalize_status(form.get("status") or current_status),
        "priority": normalize_priority(form.get("priority") or "Media"),
        "area": (form.get("area") or "").strip(),
        "due_date": (form.get("due_date") or "").strip(),
    }


def insert_task_record(record):
    row = execute_returning(
        """
        INSERT INTO tasks (title, description, status, priority, assignee, assignee_email, area, due_date, position, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """ if is_postgres() else """
        INSERT INTO tasks (title, description, status, priority, assignee, assignee_email, area, due_date, position, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record["title"], record["description"], record["status"], record["priority"],
            "", "", record["area"], record["due_date"], record["position"], record["created_at"], record["updated_at"],
        ),
    )
    return int(row["id"])


def create_task_from_form(form):
    record = task_record_from_form(form)
    record.update({"position": next_position(record["status"]), "created_at": now_text(), "updated_at": now_text()})
    task_id = insert_task_record(record)
    assign_responsibles(task_id, form.getlist("responsible_ids"))
    task = get_task(task_id)
    notify_task(
        task,
        f"Nueva acción asignada: {task['title']}",
        "Se creó una nueva acción en el Kanban Operacional Aramark.",
        event_type="creacion",
        event_label="Nueva acción creada",
    )
    return task


def changes_between(old, new, old_resps=None, new_resps=None):
    labels = {"title": "Título", "description": "Descripción", "status": "Estado", "priority": "Prioridad", "area": "Área", "due_date": "Fecha límite"}
    changes = []
    for key, label in labels.items():
        old_value = old.get(key) or ""
        new_value = new.get(key) or ""
        if key == "status":
            old_value = STATUS_LABELS.get(old_value, old_value)
            new_value = STATUS_LABELS.get(new_value, new_value)
        if old_value != new_value:
            changes.append(f"{label}: {old_value or 'Sin dato'} → {new_value or 'Sin dato'}")
    old_names = ", ".join([r.get("name") or "" for r in (old_resps or []) if r.get("name")])
    new_names = ", ".join([r.get("name") or "" for r in (new_resps or []) if r.get("name")])
    if old_names != new_names:
        changes.append(f"Responsables: {old_names or 'Sin responsable'} → {new_names or 'Sin responsable'}")
    return changes


def update_task_from_form(task_id, form):
    old_task = get_task(task_id)
    if old_task is None:
        raise ValueError("La tarea no existe.")
    old_resps = get_task_responsibles(task_id)
    record = task_record_from_form(form, current_status=old_task.get("status") or "pendiente")
    record["updated_at"] = now_text()
    execute_write(
        """
        UPDATE tasks
        SET title = ?, description = ?, status = ?, priority = ?, area = ?, due_date = ?, updated_at = ?
        WHERE id = ?
        """,
        (record["title"], record["description"], record["status"], record["priority"], record["area"], record["due_date"], record["updated_at"], task_id),
    )
    assign_responsibles(task_id, form.getlist("responsible_ids"))
    new_task = get_task(task_id)
    new_resps = get_task_responsibles(task_id)
    changes = changes_between(old_task, new_task, old_resps, new_resps)
    if changes:
        notify_task(
            new_task,
            f"Actualización de acción: {new_task['title']}",
            "Una acción del Kanban Operacional Aramark fue actualizada.",
            changes,
            event_type="actualizacion",
            event_label="Acción actualizada",
        )
    return new_task


@app.after_request
def force_utf8_headers(response):
    if response.mimetype in {"text/html", "text/css", "text/csv", "application/json", "text/javascript", "application/javascript"}:
        response.headers["Content-Type"] = f"{response.mimetype}; charset=utf-8"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.context_processor
def inject_globals():
    return {
        "STATUSES": STATUSES,
        "PRIORITIES": PRIORITIES,
        "AREAS": AREAS,
        "STATUS_LABELS": STATUS_LABELS,
        "EMAIL_ENABLED": email_enabled(),
    }


@app.route("/")
def index():
    filters = {"q": request.args.get("q", ""), "area": request.args.get("area", ""), "priority": request.args.get("priority", ""), "assignee": request.args.get("assignee", "")}
    all_tasks = load_tasks()
    filtered_tasks = load_tasks(filters)
    board = board_from_tasks(filtered_tasks)
    metrics = metrics_from_tasks(all_tasks)
    urgent_dashboard = urgent_dashboard_from_tasks(all_tasks, window_days=7)
    return render_template(
        "index.html",
        title=APP_TITLE,
        board=board,
        metrics=metrics,
        filters=filters,
        urgent_dashboard=urgent_dashboard,
        responsibles=active_responsibles(),
    )


@app.route("/crear", methods=["POST"])
def crear():
    try:
        create_task_from_form(request.form)
        flash("Acción creada correctamente.", "success")
    except Exception as exc:
        app.logger.exception("Error al crear acción")
        flash(f"Error al crear acción: {exc}", "error")
    return redirect(url_for("index"))


@app.route("/editar/<int:task_id>", methods=["GET", "POST"])
def editar(task_id):
    task = get_task(task_id)
    if task is None:
        flash("La acción solicitada no existe.", "error")
        return redirect(url_for("index"))
    if request.method == "POST":
        try:
            update_task_from_form(task_id, request.form)
            flash("Acción actualizada correctamente.", "success")
            return redirect(url_for("index"))
        except Exception as exc:
            app.logger.exception("Error al actualizar acción")
            flash(f"Error al actualizar acción: {exc}", "error")
            task = {**task, **request.form}
    return render_template("edit.html", title=f"Editar acción - {APP_TITLE}", task=task, responsibles=active_responsibles())


@app.route("/eliminar/<int:task_id>", methods=["POST"])
def eliminar(task_id):
    execute_write("DELETE FROM task_responsibles WHERE task_id = ?", (task_id,))
    execute_write("DELETE FROM tasks WHERE id = ?", (task_id,))
    flash("Acción eliminada.", "success")
    return redirect(url_for("index"))


def move_task_to_status(task_id, status):
    try:
        task_id = int(task_id)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "ID de acción inválido."}), 400
    if status not in STATUS_KEYS:
        return jsonify({"ok": False, "error": "Estado inválido."}), 400
    old_task = get_task(task_id)
    if old_task is None:
        return jsonify({"ok": False, "error": "La acción no existe o ya fue eliminada. Recarga el tablero."}), 404
    rowcount = execute_write("UPDATE tasks SET status = ?, position = ?, updated_at = ? WHERE id = ?", (status, next_position(status), now_text(), task_id))
    if rowcount == 0:
        return jsonify({"ok": False, "error": "No se encontró la acción al actualizar."}), 404
    task = get_task(task_id)
    if task and old_task.get("status") != status:
        notify_task(
            task,
            f"Cambio de estado: {task['title']}",
            "Una acción del Kanban Operacional Aramark cambió de estado.",
            [f"Estado: {STATUS_LABELS.get(old_task.get('status'), old_task.get('status'))} → {STATUS_LABELS.get(status, status)}"],
            event_type="cambio_estado",
            event_label="Cambio de estado",
        )
    return jsonify({"ok": True, "task_id": task_id, "status": status, "status_label": STATUS_LABELS[status]})


@app.route("/api/mover", methods=["POST"])
def mover_api():
    payload = request.get_json(silent=True) or request.form
    return move_task_to_status(payload.get("task_id"), payload.get("status"))


@app.route("/mover/<int:task_id>", methods=["GET", "POST"])
def mover(task_id):
    if request.method == "GET":
        flash("Movimiento no aplicado: usa arrastrar y soltar desde el tablero.", "error")
        return redirect(url_for("index"))
    payload = request.get_json(silent=True) or request.form
    return move_task_to_status(task_id, payload.get("status"))


@app.route("/responsables", methods=["GET", "POST"])
def responsables():
    if request.method == "POST":
        try:
            record = responsible_record_from_form(request.form)
            row = execute_returning(
                """
                INSERT INTO responsables (name, email, area, notify_email, active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                RETURNING id
                """ if is_postgres() else """
                INSERT INTO responsables (name, email, area, notify_email, active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (record["name"], record["email"], record["area"], record["notify_email"], record["active"], now_text(), now_text()),
            )
            flash("Responsable creado correctamente.", "success")
        except Exception as exc:
            app.logger.exception("Error al crear responsable")
            flash(f"Error al crear responsable: {exc}", "error")
        return redirect(url_for("responsables"))
    return render_template("responsables.html", title=f"Responsables - {APP_TITLE}", responsibles=all_responsibles())


@app.route("/responsables/<int:responsible_id>/editar", methods=["GET", "POST"])
def editar_responsable(responsible_id):
    responsible = get_responsible(responsible_id)
    if responsible is None:
        flash("El responsable no existe.", "error")
        return redirect(url_for("responsables"))
    if request.method == "POST":
        try:
            record = responsible_record_from_form(request.form)
            execute_write(
                """
                UPDATE responsables
                SET name = ?, email = ?, area = ?, notify_email = ?, active = ?, updated_at = ?
                WHERE id = ?
                """,
                (record["name"], record["email"], record["area"], record["notify_email"], record["active"], now_text(), responsible_id),
            )
            for link in query_all("SELECT task_id FROM task_responsibles WHERE responsible_id = ?", (responsible_id,)):
                refresh_task_legacy_fields(link["task_id"])
            flash("Responsable actualizado correctamente.", "success")
            return redirect(url_for("responsables"))
        except Exception as exc:
            app.logger.exception("Error al actualizar responsable")
            flash(f"Error al actualizar responsable: {exc}", "error")
    return render_template("responsable_edit.html", title=f"Editar responsable - {APP_TITLE}", responsible=responsible)


@app.route("/responsables/<int:responsible_id>/eliminar", methods=["POST"])
def eliminar_responsable(responsible_id):
    affected = query_all("SELECT task_id FROM task_responsibles WHERE responsible_id = ?", (responsible_id,))
    execute_write("DELETE FROM task_responsibles WHERE responsible_id = ?", (responsible_id,))
    execute_write("DELETE FROM responsables WHERE id = ?", (responsible_id,))
    for row in affected:
        refresh_task_legacy_fields(row["task_id"])
    flash("Responsable eliminado.", "success")
    return redirect(url_for("responsables"))


@app.route("/notificaciones")
def notificaciones():
    logs = query_all("SELECT * FROM notification_logs ORDER BY created_at DESC, id DESC LIMIT 100")
    return render_template("notificaciones.html", title=f"Notificaciones - {APP_TITLE}", logs=logs)


@app.route("/exportar/csv")
def exportar_csv():
    tasks = load_tasks()
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["id", "title", "description", "status", "priority", "responsables", "correos", "area", "due_date", "created_at", "updated_at"])
    writer.writeheader()
    for task in tasks:
        writer.writerow({
            "id": task.get("id", ""),
            "title": task.get("title", ""),
            "description": task.get("description", ""),
            "status": task.get("status", ""),
            "priority": task.get("priority", ""),
            "responsables": task.get("responsible_names", ""),
            "correos": task.get("responsible_emails", ""),
            "area": task.get("area", ""),
            "due_date": task.get("due_date", ""),
            "created_at": task.get("created_at", ""),
            "updated_at": task.get("updated_at", ""),
        })
    content = output.getvalue().encode("utf-8-sig")
    return Response(content, content_type="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=kanban_aramark.csv"})


@app.route("/health")
def health():
    return {
        "status": "ok",
        "app": APP_TITLE,
        "database": "postgresql" if is_postgres() else "sqlite",
        "email": email_enabled(),
    }


init_db()

if __name__ == "__main__":
    app.run(debug=True)
