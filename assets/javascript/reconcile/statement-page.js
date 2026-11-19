/* globals gettext */
import { readBook } from '../common/book';
import { getReconcileApi } from './api';

/**
 * The statement page's Undo button (`templates/reconciliation/statement.html`):
 * `POST reconcile/api/reconciliations/{id}/undo/`, then the page reloads showing
 * the statement as undone.
 */
const api = getReconcileApi(readBook());
const errorBox = document.querySelector('[data-statement-undo-error]');

document.addEventListener('click', async (event) => {
  const button = event.target.closest('[data-statement-undo]');
  if (!button) return;
  if (!window.confirm(button.dataset.confirm)) return;
  button.disabled = true;
  try {
    await api.undo(Number(button.dataset.statementUndo));
    window.location.reload();
  } catch (err) {
    button.disabled = false;
    if (errorBox) {
      errorBox.textContent = err.message || gettext('Could not undo this reconciliation.');
      errorBox.classList.remove('hidden');
    }
  }
});
