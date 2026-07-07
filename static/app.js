document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-open-modal]').forEach(btn => {
    btn.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopPropagation();
      const modal = document.getElementById(btn.dataset.openModal);
      if (modal) modal.classList.add('open');
    });
  });
  document.querySelectorAll('[data-close-modal]').forEach(btn => {
    btn.addEventListener('click', () => btn.closest('.modal')?.classList.remove('open'));
  });
  document.querySelectorAll('.modal').forEach(modal => {
    modal.addEventListener('click', event => {
      if (event.target === modal) modal.classList.remove('open');
    });
  });

  document.querySelectorAll('.task-actions button, .task-actions a, input, select, textarea').forEach(el => {
    el.addEventListener('mousedown', event => event.stopPropagation());
    el.addEventListener('dragstart', event => event.preventDefault());
  });

  let dragged = null;
  document.querySelectorAll('.task-card').forEach(card => {
    card.addEventListener('dragstart', (event) => {
      dragged = event.currentTarget;
      dragged.classList.add('dragging');
      event.dataTransfer.effectAllowed = 'move';
      event.dataTransfer.setData('text/plain', dragged.dataset.taskId || '');
    });
    card.addEventListener('dragend', () => {
      card.classList.remove('dragging');
      dragged = null;
    });
  });

  document.querySelectorAll('.drop-zone').forEach(zone => {
    zone.addEventListener('dragover', event => {
      event.preventDefault();
      event.dataTransfer.dropEffect = 'move';
      zone.classList.add('drag-over');
    });
    zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
    zone.addEventListener('drop', async event => {
      event.preventDefault();
      zone.classList.remove('drag-over');

      const card = dragged || document.querySelector('.task-card.dragging');
      const taskId = event.dataTransfer.getData('text/plain') || card?.dataset.taskId;
      const status = zone.dataset.status;

      if (!taskId || !status) {
        alert('No se pudo identificar la tarea o el estado. Recarga el tablero e inténtalo nuevamente.');
        window.location.reload();
        return;
      }

      const previousParent = card?.parentElement || null;
      const moveUrl = window.KANBAN_MOVE_URL || '/api/mover';

      try {
        if (card) card.classList.add('saving');
        const response = await fetch(moveUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
          body: JSON.stringify({ task_id: taskId, status })
        });
        let result = {};
        try { result = await response.json(); } catch (_) {}
        if (!response.ok || result.ok === false) {
          throw new Error(result.error || `No se pudo mover la tarea. Código ${response.status}.`);
        }
        window.location.reload();
      } catch (error) {
        if (card && previousParent) previousParent.appendChild(card);
        alert(error.message || 'No se pudo mover la tarea.');
        window.location.reload();
      }
    });
  });
});
