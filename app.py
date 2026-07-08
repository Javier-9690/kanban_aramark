# -*- coding: utf-8 -*-
import csv
import html as html_lib
import io
import json
import os
import smtplib
import socket
import sqlite3
import threading
import urllib.error
import urllib.request
from datetime import datetime, date, timedelta
from email.message import EmailMessage

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
AREAS = ["Operaciones", "Calidad", "Mantención", "Seguridad", "Bodega", "Habitabilidad", "Administración"]

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "cambiar-esta-clave-en-render")


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def is_postgres():
    return DATABASE_URL.lower().startswith(("postgres://", "postgresql://"))


def db_config_label():
    if is_postgres():
        return "PostgreSQL activo por DATABASE_URL"
    return "SQLite local activo; configura DATABASE_URL para persistencia PostgreSQL"


def get_conn():
    if is_postgres():
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError(
                "Falta instalar psycopg. Revisa requirements.txt y vuelve a desplegar en Render."
            ) from exc
        return psycopg.connect(DATABASE_URL, row_factory=dict_row)
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


def execute_returning(sql, params=()):
    conn = get_conn()
    try:
        if not is_postgres():
            raise RuntimeError("execute_returning solo se usa con PostgreSQL.")
        with conn.cursor() as cur:
            cur.execute(adapt_sql(sql), tuple(params))
            row = cur.fetchone()
        conn.commit()
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
            "CREATE INDEX IF NOT EXISTS idx_tasks_status_position ON tasks(status, position)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks(due_date)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON tasks(assignee)",
        ])
        return

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_conn()
    try:
        conn.execute(
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
            """
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()}
        if "assignee_email" not in columns:
            conn.execute("ALTER TABLE tasks ADD COLUMN assignee_email TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status_position ON tasks(status, position)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks(due_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON tasks(assignee)")
        conn.commit()
    finally:
        conn.close()


def env_text(name, default=""):
    return (os.environ.get(name) or default or "").strip()


def env_bool(name, default=False):
    value = (os.environ.get(name) or "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "si", "sí", "on"}


def notifications_active():
    return env_bool("NOTIFY_EMAIL", default=True)


def app_base_url():
    return env_text("APP_BASE_URL").rstrip("/")


def brevo_sender_email():
    return env_text("BREVO_FROM_EMAIL") or env_text("SMTP_FROM") or env_text("EMAIL_FROM")


def brevo_enabled():
    return bool(env_text("BREVO_API_KEY") and brevo_sender_email())


def smtp_enabled():
    required = ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM"]
    return all(env_text(key) for key in required)


def selected_email_provider():
    if not notifications_active():
        return "disabled"
    preferred = env_text("EMAIL_PROVIDER", "auto").lower()
    if preferred == "brevo":
        return "brevo" if brevo_enabled() else "missing_brevo"
    if preferred == "smtp":
        return "smtp" if smtp_enabled() else "missing_smtp"
    if brevo_enabled():
        return "brevo"
    if smtp_enabled():
        return "smtp"
    return "missing"


def email_enabled():
    return selected_email_provider() in {"brevo", "smtp"}


def email_config_label():
    provider = selected_email_provider()
    if provider == "brevo":
        return "Activo por Brevo API HTTPS"
    if provider == "smtp":
        return "Activo por SMTP"
    if provider == "disabled":
        return "Desactivado por NOTIFY_EMAIL=false"
    if provider == "missing_brevo":
        return "Brevo seleccionado, pero faltan BREVO_API_KEY o BREVO_FROM_EMAIL"
    if provider == "missing_smtp":
        return "SMTP seleccionado, pero faltan variables SMTP"
    return "No configurado"


def create_ipv4_connection(host, port, timeout):
    last_exc = None
    addresses = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
    if not addresses:
        raise OSError(f"No se encontraron direcciones IPv4 para {host}:{port}")
    for family, socktype, proto, _canonname, sockaddr in addresses:
        sock = socket.socket(family, socktype, proto)
        sock.settimeout(timeout)
        try:
            sock.connect(sockaddr)
            return sock
        except OSError as exc:
            last_exc = exc
            try:
                sock.close()
            except Exception:
                pass
    raise last_exc or OSError(f"No se pudo conectar por IPv4 a {host}:{port}")


class SMTPIPv4(smtplib.SMTP):
    def _get_socket(self, host, port, timeout):
        return create_ipv4_connection(host, port, timeout)


class SMTPSSLIPv4(smtplib.SMTP_SSL):
    def _get_socket(self, host, port, timeout):
        raw_socket = create_ipv4_connection(host, port, timeout)
        return self.context.wrap_socket(raw_socket, server_hostname=self._host)


def compose_task_email(task, intro, changes=None):
    base_url = app_base_url()
    task_url = f"{base_url}/editar/{task['id']}" if base_url and task.get("id") else ""
    lines = [
        intro,
        "",
        f"Tarea: {task.get('title') or ''}",
        f"Estado: {STATUS_LABELS.get(task.get('status'), task.get('status') or '')}",
        f"Prioridad: {task.get('priority') or ''}",
        f"Responsable: {task.get('assignee') or ''}",
        f"Área: {task.get('area') or ''}",
        f"Fecha límite: {task.get('due_date') or 'Sin fecha'}",
    ]
    if changes:
        lines.extend(["", "Cambios registrados:"])
        lines.extend([f"- {item}" for item in changes])
    if task_url:
        lines.extend(["", f"Abrir tarea: {task_url}"])
    lines.extend(["", "Kanban Operacional Aramark - Campamento 5400"])
    text_content = "\n".join(lines)

    esc = lambda value: html_lib.escape(str(value or ""))
    change_html = ""
    if changes:
        change_html = "<h3>Cambios registrados</h3><ul>" + "".join(f"<li>{esc(item)}</li>" for item in changes) + "</ul>"
    button_html = f'<p><a href="{esc(task_url)}" style="display:inline-block;background:#ed1b2e;color:#ffffff;padding:10px 14px;border-radius:5px;text-decoration:none;font-weight:bold;">Abrir tarea</a></p>' if task_url else ""
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
            <tr><td style="padding:7px;border-bottom:1px solid #eee;font-weight:bold;">Responsable</td><td style="padding:7px;border-bottom:1px solid #eee;">{esc(task.get('assignee'))}</td></tr>
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


def send_brevo_email_sync(recipient, recipient_name, subject, text_content, html_content):
    api_key = env_text("BREVO_API_KEY")
    sender_email = brevo_sender_email()
    sender_name = env_text("BREVO_FROM_NAME", "Kanban Operacional Aramark")
    timeout = float(env_text("BREVO_TIMEOUT", "8"))
    if not api_key or not sender_email:
        return False, "Brevo no configurado. Falta BREVO_API_KEY o BREVO_FROM_EMAIL."

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
        headers={
            "accept": "application/json",
            "api-key": api_key,
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", "ignore")
            if not (200 <= response.status < 300):
                raise RuntimeError(f"Brevo respondió HTTP {response.status}: {body}")
            app.logger.info("Correo enviado por Brevo a %s. Respuesta: %s", recipient, body[:500])
            return True, "Correo enviado por Brevo."
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "ignore")
        app.logger.exception("Brevo rechazó el correo a %s. HTTP %s: %s", recipient, exc.code, body)
        return False, f"Brevo HTTP {exc.code}: {body[:500]}"
    except Exception as exc:
        app.logger.exception("No se pudo enviar correo por Brevo a %s: %s", recipient, exc)
        return False, str(exc)


def send_smtp_email_sync(recipient, subject, text_content):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = env_text("SMTP_FROM")
    msg["To"] = recipient
    msg.set_content(text_content)

    host = env_text("SMTP_HOST")
    port = int(env_text("SMTP_PORT", "587"))
    timeout = float(env_text("SMTP_TIMEOUT", "4"))
    user = env_text("SMTP_USER")
    password = env_text("SMTP_PASSWORD")
    use_ssl = env_bool("SMTP_SSL", default=False)
    force_ipv4 = env_bool("SMTP_FORCE_IPV4", default=True)

    try:
        smtp_plain_cls = SMTPIPv4 if force_ipv4 else smtplib.SMTP
        smtp_ssl_cls = SMTPSSLIPv4 if force_ipv4 else smtplib.SMTP_SSL
        app.logger.info(
            "Intentando correo SMTP host=%s port=%s ssl=%s ipv4=%s destino=%s",
            host, port, use_ssl, force_ipv4, recipient,
        )
        if use_ssl:
            with smtp_ssl_cls(host, port, timeout=timeout) as smtp:
                smtp.login(user, password)
                smtp.send_message(msg)
        else:
            with smtp_plain_cls(host, port, timeout=timeout) as smtp:
                smtp.starttls()
                smtp.login(user, password)
                smtp.send_message(msg)
        app.logger.info("Correo enviado por SMTP a %s", recipient)
        return True, "Correo enviado por SMTP."
    except Exception as exc:
        app.logger.exception("No se pudo enviar correo por SMTP a %s: %s", recipient, exc)
        return False, str(exc)


def _send_task_email_sync(task, subject, intro, changes=None):
    recipient = (task.get("assignee_email") or "").strip()
    if not recipient:
        return False, "La tarea no tiene correo de responsable."
    if not email_enabled():
        app.logger.warning("Correo no enviado: notificaciones no configuradas. Destinatario: %s", recipient)
        return False, email_config_label()

    text_content, html_content = compose_task_email(task, intro, changes)
    provider = selected_email_provider()
    if provider == "brevo":
        return send_brevo_email_sync(recipient, task.get("assignee") or recipient, subject, text_content, html_content)
    if provider == "smtp":
        return send_smtp_email_sync(recipient, subject, text_content)
    return False, email_config_label()


def send_task_email(task, subject, intro, changes=None):
    if not task:
        return False, "Tarea no disponible."
    recipient = (task.get("assignee_email") or "").strip()
    if not recipient:
        return False, "La tarea no tiene correo de responsable."
    if not email_enabled():
        app.logger.warning("Correo no programado: %s. Destinatario: %s", email_config_label(), recipient)
        return False, email_config_label()

    task_copy = dict(task)
    changes_copy = list(changes or [])

    def worker():
        with app.app_context():
            _send_task_email_sync(task_copy, subject, intro, changes_copy)

    threading.Thread(target=worker, daemon=True).start()
    return True, "Correo programado en segundo plano."


def normalize_status(value):
    return value if value in STATUS_KEYS else "pendiente"


def normalize_priority(value):
    return value if value in PRIORITIES else "Media"


def parse_due_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        return None


def next_position(status):
    row = query_one("SELECT COALESCE(MAX(position), 0) + 1 AS pos FROM tasks WHERE status = ?", (status,))
    return int(row.get("pos") or 1) if row else 1


def row_to_dict(row):
    item = dict(row)
    item["status_label"] = STATUS_LABELS.get(item.get("status"), item.get("status"))
    item["is_overdue"] = False
    item["days_until_due"] = None
    due = parse_due_date(item.get("due_date"))
    if due:
        item["days_until_due"] = (due - date.today()).days
        item["is_overdue"] = item.get("status") != "finalizado" and due < date.today()
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


def form_record(form, current_status="pendiente"):
    title = (form.get("title") or "").strip()
    if not title:
        raise ValueError("El título de la tarea es obligatorio.")
    return {
        "title": title,
        "description": (form.get("description") or "").strip(),
        "status": normalize_status(form.get("status") or current_status),
        "priority": normalize_priority(form.get("priority") or "Media"),
        "assignee": (form.get("assignee") or "").strip(),
        "assignee_email": (form.get("assignee_email") or "").strip(),
        "area": (form.get("area") or "").strip(),
        "due_date": (form.get("due_date") or "").strip(),
    }


def insert_task_record(record):
    values = (
        record["title"], record["description"], record["status"], record["priority"],
        record["assignee"], record["assignee_email"], record["area"], record["due_date"],
        record["position"], record["created_at"], record["updated_at"],
    )
    if is_postgres():
        row = execute_returning(
            """
            INSERT INTO tasks (title, description, status, priority, assignee, assignee_email, area, due_date, position, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            values,
        )
        return int(row["id"])

    conn = get_conn()
    try:
        cur = conn.execute(
            """
            INSERT INTO tasks (title, description, status, priority, assignee, assignee_email, area, due_date, position, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        task_id = cur.lastrowid
        conn.commit()
        return int(task_id)
    finally:
        conn.close()


def create_task_from_form(form):
    record = form_record(form)
    record.update({
        "position": next_position(record["status"]),
        "created_at": now_text(),
        "updated_at": now_text(),
    })
    task_id = insert_task_record(record)
    task = get_task(task_id)
    send_task_email(
        task,
        f"Nueva tarea asignada: {task['title']}",
        "Se te ha asignado una nueva tarea en el Kanban Operacional Aramark.",
    )
    return task


def changes_between(old, new):
    labels = {
        "title": "Título",
        "description": "Descripción",
        "status": "Estado",
        "priority": "Prioridad",
        "assignee": "Responsable",
        "assignee_email": "Correo responsable",
        "area": "Área",
        "due_date": "Fecha límite",
    }
    changes = []
    for key, label in labels.items():
        old_value = old.get(key) or ""
        new_value = new.get(key) or ""
        if key == "status":
            old_value = STATUS_LABELS.get(old_value, old_value)
            new_value = STATUS_LABELS.get(new_value, new_value)
        if old_value != new_value:
            changes.append(f"{label}: {old_value or 'Sin dato'} → {new_value or 'Sin dato'}")
    return changes


def update_task_from_form(task_id, form):
    old_task = get_task(task_id)
    if old_task is None:
        raise ValueError("La tarea no existe.")
    record = form_record(form, current_status=old_task.get("status") or "pendiente")
    record["updated_at"] = now_text()
    execute_write(
        """
        UPDATE tasks
        SET title = ?,
            description = ?,
            status = ?,
            priority = ?,
            assignee = ?,
            assignee_email = ?,
            area = ?,
            due_date = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            record["title"], record["description"], record["status"], record["priority"],
            record["assignee"], record["assignee_email"], record["area"], record["due_date"],
            record["updated_at"], task_id,
        ),
    )
    new_task = get_task(task_id)
    changes = changes_between(old_task, new_task)
    if changes:
        send_task_email(
            new_task,
            f"Actualización de tarea: {new_task['title']}",
            "Una tarea asignada a tu nombre fue actualizada en el Kanban Operacional Aramark.",
            changes,
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
        "EMAIL_CONFIG_LABEL": email_config_label(),
        "DB_CONFIG_LABEL": db_config_label(),
        "IS_POSTGRES": is_postgres(),
    }


@app.route("/")
def index():
    filters = {
        "q": request.args.get("q", ""),
        "area": request.args.get("area", ""),
        "priority": request.args.get("priority", ""),
        "assignee": request.args.get("assignee", ""),
    }
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
    )


@app.route("/crear", methods=["POST"])
def crear():
    try:
        create_task_from_form(request.form)
        flash("Tarea creada correctamente.", "success")
    except Exception as exc:
        app.logger.exception("Error al crear tarea")
        flash(f"Error al crear tarea: {exc}", "error")
    return redirect(url_for("index"))


@app.route("/editar/<int:task_id>", methods=["GET", "POST"])
def editar(task_id):
    task = get_task(task_id)
    if task is None:
        flash("La tarea solicitada no existe.", "error")
        return redirect(url_for("index"))
    if request.method == "POST":
        try:
            update_task_from_form(task_id, request.form)
            flash("Tarea actualizada correctamente.", "success")
            return redirect(url_for("index"))
        except Exception as exc:
            app.logger.exception("Error al actualizar tarea")
            flash(f"Error al actualizar tarea: {exc}", "error")
            task = {**task, **request.form}
    return render_template("edit.html", title=f"Editar tarea - {APP_TITLE}", task=task)


@app.route("/eliminar/<int:task_id>", methods=["POST"])
def eliminar(task_id):
    execute_write("DELETE FROM tasks WHERE id = ?", (task_id,))
    flash("Tarea eliminada.", "success")
    return redirect(url_for("index"))


def move_task_to_status(task_id, status):
    try:
        task_id = int(task_id)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "ID de tarea inválido."}), 400

    if status not in STATUS_KEYS:
        return jsonify({"ok": False, "error": "Estado inválido."}), 400

    old_task = get_task(task_id)
    if old_task is None:
        return jsonify({"ok": False, "error": "La tarea no existe o ya fue eliminada. Recarga el tablero."}), 404

    rowcount = execute_write(
        "UPDATE tasks SET status = ?, position = ?, updated_at = ? WHERE id = ?",
        (status, next_position(status), now_text(), task_id),
    )
    if rowcount == 0:
        return jsonify({"ok": False, "error": "No se encontró la tarea al actualizar."}), 404

    task = get_task(task_id)
    if task and old_task.get("status") != status:
        send_task_email(
            task,
            f"Cambio de estado: {task['title']}",
            "Una tarea asignada a tu nombre cambió de estado en el Kanban Operacional Aramark.",
            [f"Estado: {STATUS_LABELS.get(old_task.get('status'), old_task.get('status'))} → {STATUS_LABELS.get(status, status)}"],
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


@app.route("/exportar/csv")
def exportar_csv():
    tasks = load_tasks()
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["id", "title", "description", "status", "priority", "assignee", "assignee_email", "area", "due_date", "created_at", "updated_at"],
    )
    writer.writeheader()
    for task in tasks:
        writer.writerow({key: task.get(key, "") for key in writer.fieldnames})
    content = output.getvalue().encode("utf-8-sig")
    return Response(content, content_type="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=kanban_aramark.csv"})


@app.route("/notificaciones/probar", methods=["POST"])
def probar_notificaciones():
    test_email = (request.form.get("test_email") or "").strip()
    if not test_email:
        flash("Debes ingresar un correo para la prueba.", "error")
        return redirect(url_for("index"))
    fake_task = {
        "id": 0,
        "title": "Prueba de notificación",
        "description": "Correo de prueba del Kanban Operacional Aramark.",
        "status": "pendiente",
        "priority": "Media",
        "assignee": "Usuario de prueba",
        "assignee_email": test_email,
        "area": "Operaciones",
        "due_date": "",
    }
    ok, message = _send_task_email_sync(
        fake_task,
        "Prueba de correo - Kanban Operacional Aramark",
        "Este es un correo de prueba para verificar las notificaciones del Kanban Operacional Aramark.",
    )
    if ok:
        flash(f"Correo de prueba enviado a {test_email}.", "success")
    else:
        flash(f"No se pudo enviar el correo de prueba: {message}", "error")
    return redirect(url_for("index"))


@app.route("/health")
def health():
    return {"status": "ok", "app": APP_TITLE, "database": "postgresql" if is_postgres() else "sqlite"}


init_db()

if __name__ == "__main__":
    app.run(debug=True)
