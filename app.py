# -*- coding: utf-8 -*-
import csv
import io
import os
import smtplib
import sqlite3
from datetime import datetime, date
from email.message import EmailMessage

from flask import Flask, Response, flash, jsonify, redirect, render_template, request, send_file, url_for

APP_TITLE = "Kanban Operacional Aramark"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
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
AREAS = ["Operaciones", "Calidad", "Mantención", "Seguridad", "Bodega", "Habitabilidad", "Administración"]

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "cambiar-esta-clave-en-render")


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_conn() as conn:
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
        # Migración segura para bases antiguas ya creadas en Render.
        columns = {row[1] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()}
        if "assignee_email" not in columns:
            conn.execute("ALTER TABLE tasks ADD COLUMN assignee_email TEXT")
        conn.commit()



def email_enabled():
    """Devuelve True si la app tiene configuración SMTP suficiente para enviar correos."""
    required = ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM"]
    return all((os.environ.get(key) or "").strip() for key in required)


def app_base_url():
    return (os.environ.get("APP_BASE_URL") or "").strip().rstrip("/")


def send_task_email(task, subject, intro, changes=None):
    """Envía una notificación por correo al responsable de la tarea.

    En Render debes configurar SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD,
    SMTP_FROM y opcionalmente APP_BASE_URL. Si no están configuradas, la app
    sigue funcionando y solo registra el evento en logs.
    """
    recipient = (task.get("assignee_email") or "").strip()
    if not recipient:
        return False, "La tarea no tiene correo de responsable."
    if not email_enabled():
        app.logger.warning("Correo no enviado: SMTP no configurado. Destinatario: %s", recipient)
        return False, "SMTP no configurado."

    base_url = app_base_url()
    task_url = f"{base_url}/editar/{task['id']}" if base_url else ""
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

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ.get("SMTP_FROM")
    msg["To"] = recipient
    msg.set_content("\n".join(lines))

    host = os.environ.get("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    use_ssl = (os.environ.get("SMTP_SSL") or "").lower() in {"1", "true", "yes", "si", "sí"}

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=10) as smtp:
                smtp.login(user, password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=10) as smtp:
                smtp.starttls()
                smtp.login(user, password)
                smtp.send_message(msg)
        return True, "Correo enviado."
    except Exception as exc:
        app.logger.exception("No se pudo enviar correo de tarea %s: %s", task.get("id"), exc)
        return False, str(exc)


def normalize_status(value):
    return value if value in STATUS_KEYS else "pendiente"


def normalize_priority(value):
    return value if value in PRIORITIES else "Media"


def next_position(status):
    with get_conn() as conn:
        row = conn.execute("SELECT COALESCE(MAX(position), 0) + 1 AS pos FROM tasks WHERE status = ?", (status,)).fetchone()
    return int(row["pos"] or 1)


def row_to_dict(row):
    item = dict(row)
    item["status_label"] = STATUS_LABELS.get(item["status"], item["status"])
    item["is_overdue"] = False
    if item.get("due_date") and item.get("status") != "finalizado":
        try:
            item["is_overdue"] = datetime.strptime(item["due_date"], "%Y-%m-%d").date() < date.today()
        except ValueError:
            item["is_overdue"] = False
    return item


def load_tasks(filters=None):
    filters = filters or {}
    where = []
    params = []
    q = (filters.get("q") or "").strip()
    area = (filters.get("area") or "").strip()
    priority = (filters.get("priority") or "").strip()
    assignee = (filters.get("assignee") or "").strip()

    if q:
        where.append("(title LIKE ? OR description LIKE ? OR assignee LIKE ? OR assignee_email LIKE ? OR area LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like, like, like])
    if area:
        where.append("area = ?")
        params.append(area)
    if priority:
        where.append("priority = ?")
        params.append(priority)
    if assignee:
        where.append("assignee LIKE ?")
        params.append(f"%{assignee}%")

    sql = "SELECT * FROM tasks"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY status, position, updated_at DESC"

    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
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


def get_task(task_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
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


def create_task_from_form(form):
    record = form_record(form)
    record.update({
        "position": next_position(record["status"]),
        "created_at": now_text(),
        "updated_at": now_text(),
    })
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO tasks (title, description, status, priority, assignee, assignee_email, area, due_date, position, created_at, updated_at)
            VALUES (:title, :description, :status, :priority, :assignee, :assignee_email, :area, :due_date, :position, :created_at, :updated_at)
            """,
            record,
        )
        task_id = cur.lastrowid
        conn.commit()
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
    record["id"] = task_id
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE tasks
            SET title = :title,
                description = :description,
                status = :status,
                priority = :priority,
                assignee = :assignee,
                assignee_email = :assignee_email,
                area = :area,
                due_date = :due_date,
                updated_at = :updated_at
            WHERE id = :id
            """,
            record,
        )
        conn.commit()
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
    return {"STATUSES": STATUSES, "PRIORITIES": PRIORITIES, "AREAS": AREAS, "STATUS_LABELS": STATUS_LABELS, "EMAIL_ENABLED": email_enabled()}


@app.route("/")
def index():
    filters = {
        "q": request.args.get("q", ""),
        "area": request.args.get("area", ""),
        "priority": request.args.get("priority", ""),
        "assignee": request.args.get("assignee", ""),
    }
    tasks = load_tasks(filters)
    board = board_from_tasks(tasks)
    metrics = metrics_from_tasks(tasks)
    return render_template("index.html", title=APP_TITLE, board=board, metrics=metrics, filters=filters)


@app.route("/crear", methods=["POST"])
def crear():
    try:
        create_task_from_form(request.form)
        flash("Tarea creada correctamente.", "success")
    except Exception as exc:
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
            flash(f"Error al actualizar tarea: {exc}", "error")
            task = {**task, **request.form}
    return render_template("edit.html", title=f"Editar tarea - {APP_TITLE}", task=task)


@app.route("/eliminar/<int:task_id>", methods=["POST"])
def eliminar(task_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
    flash("Tarea eliminada.", "success")
    return redirect(url_for("index"))


def move_task_to_status(task_id, status):
    """Mueve una tarea de forma segura y devuelve respuesta JSON consistente."""
    try:
        task_id = int(task_id)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "ID de tarea inválido."}), 400

    if status not in STATUS_KEYS:
        return jsonify({"ok": False, "error": "Estado inválido."}), 400

    old_task = get_task(task_id)
    if old_task is None:
        return jsonify({"ok": False, "error": "La tarea no existe o ya fue eliminada. Recarga el tablero."}), 404

    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE tasks SET status = ?, position = ?, updated_at = ? WHERE id = ?",
            (status, next_position(status), now_text(), task_id),
        )
        conn.commit()
        if cur.rowcount == 0:
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
    # Compatibilidad con versiones antiguas del JavaScript. Si el navegador llega por GET,
    # se evita una pantalla Not Found y se vuelve al tablero.
    if request.method == "GET":
        flash("Movimiento no aplicado: usa arrastrar y soltar desde el tablero.", "error")
        return redirect(url_for("index"))
    payload = request.get_json(silent=True) or request.form
    return move_task_to_status(task_id, payload.get("status"))


@app.route("/exportar/csv")
def exportar_csv():
    tasks = load_tasks()
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["id", "title", "description", "status", "priority", "assignee", "assignee_email", "area", "due_date", "created_at", "updated_at"])
    writer.writeheader()
    for task in tasks:
        writer.writerow({key: task.get(key, "") for key in writer.fieldnames})
    content = output.getvalue().encode("utf-8-sig")
    return Response(content, content_type="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=kanban_aramark.csv"})


@app.route("/health")
def health():
    return {"status": "ok", "app": APP_TITLE}


init_db()

if __name__ == "__main__":
    app.run(debug=True)
