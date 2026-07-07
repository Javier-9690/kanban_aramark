# -*- coding: utf-8 -*-
import csv
import io
import os
import sqlite3
from datetime import datetime, date

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
                area TEXT,
                due_date TEXT,
                position INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


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
        where.append("(title LIKE ? OR description LIKE ? OR assignee LIKE ? OR area LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like, like])
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


def create_task_from_form(form):
    title = (form.get("title") or "").strip()
    if not title:
        raise ValueError("El título de la tarea es obligatorio.")
    status = normalize_status(form.get("status") or "pendiente")
    record = {
        "title": title,
        "description": (form.get("description") or "").strip(),
        "status": status,
        "priority": normalize_priority(form.get("priority") or "Media"),
        "assignee": (form.get("assignee") or "").strip(),
        "area": (form.get("area") or "").strip(),
        "due_date": (form.get("due_date") or "").strip(),
        "position": next_position(status),
        "created_at": now_text(),
        "updated_at": now_text(),
    }
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO tasks (title, description, status, priority, assignee, area, due_date, position, created_at, updated_at)
            VALUES (:title, :description, :status, :priority, :assignee, :area, :due_date, :position, :created_at, :updated_at)
            """,
            record,
        )
        conn.commit()


def update_task_from_form(task_id, form):
    title = (form.get("title") or "").strip()
    if not title:
        raise ValueError("El título de la tarea es obligatorio.")
    status = normalize_status(form.get("status") or "pendiente")
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE tasks
            SET title = ?, description = ?, status = ?, priority = ?, assignee = ?, area = ?, due_date = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                title,
                (form.get("description") or "").strip(),
                status,
                normalize_priority(form.get("priority") or "Media"),
                (form.get("assignee") or "").strip(),
                (form.get("area") or "").strip(),
                (form.get("due_date") or "").strip(),
                now_text(),
                task_id,
            ),
        )
        conn.commit()


@app.after_request
def force_utf8_headers(response):
    if response.mimetype in {"text/html", "text/css", "text/csv", "application/json", "text/javascript", "application/javascript"}:
        response.headers["Content-Type"] = f"{response.mimetype}; charset=utf-8"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.context_processor
def inject_globals():
    return {"STATUSES": STATUSES, "PRIORITIES": PRIORITIES, "AREAS": AREAS, "STATUS_LABELS": STATUS_LABELS}


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


@app.route("/editar/<int:task_id>", methods=["POST"])
def editar(task_id):
    try:
        update_task_from_form(task_id, request.form)
        flash("Tarea actualizada correctamente.", "success")
    except Exception as exc:
        flash(f"Error al actualizar tarea: {exc}", "error")
    return redirect(url_for("index"))


@app.route("/eliminar/<int:task_id>", methods=["POST"])
def eliminar(task_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
    flash("Tarea eliminada.", "success")
    return redirect(url_for("index"))


@app.route("/mover/<int:task_id>", methods=["POST"])
def mover(task_id):
    payload = request.get_json(silent=True) or request.form
    status = normalize_status(payload.get("status"))
    with get_conn() as conn:
        conn.execute(
            "UPDATE tasks SET status = ?, position = ?, updated_at = ? WHERE id = ?",
            (status, next_position(status), now_text(), task_id),
        )
        conn.commit()
    return jsonify({"ok": True, "status": status, "status_label": STATUS_LABELS[status]})


@app.route("/exportar/csv")
def exportar_csv():
    tasks = load_tasks()
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["id", "title", "description", "status", "priority", "assignee", "area", "due_date", "created_at", "updated_at"])
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
