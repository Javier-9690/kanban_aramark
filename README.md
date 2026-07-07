# Kanban Operacional Aramark

Aplicación web Flask lista para Render.com, con estética corporativa roja y logos Aramark / Escondida BHP.

## Funciones

- Tablero Kanban con columnas: Pendiente, En proceso, En revisión, Bloqueado y Finalizado.
- Crear, editar, eliminar y mover tareas con arrastrar y soltar.
- Campos por tarea: título, descripción, estado, prioridad, responsable, área y fecha límite.
- Métricas superiores: total de tareas, finalizadas, bloqueadas, vencidas y avance.
- Filtros por búsqueda, área, prioridad y responsable.
- Exportación CSV.
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
