// Budget page: save an amount in place, without navigating.
//
// Each row used to submit its own <form>, so every blur triggered a POST, a
// redirect and a full page load — which reset the scroll position to the top
// and dropped focus. Typing down a column was unusable. Here the amount is
// POSTed as JSON and the server returns every figure for the month, which we
// write straight into the `data-budget-cell` spans the templates carry.
//
// The <noscript> Save buttons remain the fallback when JS is disabled.
import Cookies from 'js-cookie';

const SAVE_URL = document.querySelector('[data-budget-save-url]')?.dataset.budgetSaveUrl;
const forms = Array.from(document.querySelectorAll('form[data-budget-autosave]'));

if (SAVE_URL && forms.length) {
  init();
}

function init() {
  // A stale response must never overwrite fresher totals: each save takes a
  // ticket, and only the newest one that has come back gets to paint.
  let ticket = 0;
  let painted = 0;

  const cells = new Map();
  document.querySelectorAll('[data-budget-cell]').forEach((el) => {
    cells.set(el.dataset.budgetCell, el);
  });

  // One shared live region: the per-row dot is decorative, so save state has to
  // reach a screen reader some other way.
  const live = document.querySelector('[data-budget-live]');

  const checkboxes = new Map();
  document.querySelectorAll('.budget-row-checkbox').forEach((cb) => {
    checkboxes.set(`row:${cb.dataset.categoryId}:budgeted`, cb);
  });

  const rows = forms
    .map((form) => {
      const input = form.querySelector('input[name="budget_amount"]');
      return input ? makeRow(form, input) : null;
    })
    .filter(Boolean);

  rows.forEach((row, index) => wire(row, index));

  // -------------------------------------------------------------------------
  // Row state
  // -------------------------------------------------------------------------

  function makeRow(form, input) {
    return {
      form,
      input,
      status: form.querySelector('[data-budget-status]'),
      categoryId: form.dataset.categoryId,
      categoryName: form.dataset.categoryName || '',
      month: form.dataset.month,
      // What the server last confirmed. Escape reverts to it, and a commit that
      // matches it is a no-op rather than a request.
      saved: input.value,
      inFlight: false,
      // Latest value typed while a save was already running.
      queued: null,
    };
  }

  function wire(row, index) {
    const { input } = row;

    input.addEventListener('focus', () => input.select());

    // With JS on, the row never navigates: saving happens over fetch.
    row.form.addEventListener('submit', (event) => {
      event.preventDefault();
      commit(row);
    });

    // Blur, Enter and any other committing change all land here.
    input.addEventListener('change', () => commit(row));

    // Leaving a field that had nothing to save still tidies "1234" to "1234.00";
    // a field that *is* saving gets normalized by the response instead.
    input.addEventListener('blur', () => {
      if (!row.inFlight && row.queued === null) input.value = row.saved;
    });

    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        commit(row);
        focusRow(index + (event.shiftKey ? -1 : 1));
      } else if (event.key === 'ArrowDown') {
        event.preventDefault();
        commit(row);
        focusRow(index + 1);
      } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        commit(row);
        focusRow(index - 1);
      } else if (event.key === 'Escape') {
        event.preventDefault();
        input.value = row.saved;
        setStatus(row, '');
        input.select();
      }
    });
  }

  function focusRow(index) {
    const target = rows[index];
    if (!target) return;
    target.input.focus();
    target.input.select();
  }

  // -------------------------------------------------------------------------
  // Saving
  // -------------------------------------------------------------------------

  // "1234", "1,234" and "1234.00" are the same amount — retyping one as another
  // is not an edit, and must not cost a request.
  function sameAmount(a, b) {
    const clean = (v) => String(v).replace(/[$,\s]/g, '');
    const [x, y] = [clean(a), clean(b)];
    if (x === y) return true;
    const [nx, ny] = [Number(x), Number(y)];
    return x !== '' && y !== '' && Number.isFinite(nx) && Number.isFinite(ny) && nx === ny;
  }

  function commit(row) {
    const value = row.input.value.trim();
    if (sameAmount(value, row.saved)) return;

    if (row.inFlight) {
      // Keep the newest value and send it once the running save returns, so
      // fast typing can't interleave two writes to the same row.
      row.queued = value;
      return;
    }
    save(row, value);
  }

  async function save(row, value) {
    row.inFlight = true;
    setStatus(row, 'saving');
    const mine = ++ticket;

    let response;
    let payload;
    try {
      response = await fetch(SAVE_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': Cookies.get('csrftoken') || '',
        },
        body: JSON.stringify({
          category_id: Number(row.categoryId),
          month: row.month,
          amount: value,
        }),
      });
      payload = await response.json().catch(() => ({}));
    } catch {
      row.inFlight = false;
      fail(row, 'Could not reach the server. Your change was not saved.');
      return;
    }

    row.inFlight = false;

    if (!response.ok) {
      fail(row, payload.error || 'Could not save that amount.');
      return;
    }

    row.saved = payload.amount;
    // Normalize the display to 2dp — but never yank the text out from under
    // someone who has focused the field again and is typing.
    if (document.activeElement !== row.input) {
      row.input.value = payload.amount;
    }
    row.input.classList.remove('input-error');
    setStatus(row, 'saved');
    announce(`${row.categoryName} saved as ${payload.amount}.`);

    if (mine > painted) {
      painted = mine;
      paint(payload.cells);
    }

    if (row.queued !== null) {
      const next = row.queued;
      row.queued = null;
      if (!sameAmount(next, row.saved)) save(row, next);
    }
  }

  function fail(row, message) {
    row.queued = null;
    row.input.classList.add('input-error');
    setStatus(row, 'error', message);
    const text = `${row.categoryName ? `${row.categoryName}: ` : ''}${message}`;
    announce(text);
    toast(text);
  }

  // -------------------------------------------------------------------------
  // Painting the returned figures
  // -------------------------------------------------------------------------

  function paint(payload) {
    if (!payload) return;
    Object.entries(payload).forEach(([key, cell]) => {
      const checkbox = checkboxes.get(key);
      // Keeps the Auto-Assign "this will overwrite N amounts" count honest.
      if (checkbox) checkbox.dataset.budgeted = cell.value;

      const el = cells.get(key);
      if (!el || el.textContent.trim() === cell.value) return;
      el.textContent = cell.value;
      el.classList.toggle('text-error', cell.tone === 'neg');
      el.classList.toggle('text-success', cell.tone === 'pos');
      flash(el);
    });
  }

  function flash(el) {
    el.classList.remove('budget-cell-flash');
    // Restart the animation on a cell that is still mid-flash.
    void el.offsetWidth;
    el.classList.add('budget-cell-flash');
  }

  // -------------------------------------------------------------------------
  // Per-row status and error toast
  // -------------------------------------------------------------------------

  function setStatus(row, state, label) {
    if (!row.status) return;
    clearTimeout(row.statusTimer);
    row.status.className = state ? `budget-status is-${state}` : 'budget-status';
    row.status.title = label || (state === 'saved' ? 'Saved' : state === 'saving' ? 'Saving…' : '');
    if (state === 'saved') {
      row.statusTimer = setTimeout(() => {
        row.status.className = 'budget-status';
        row.status.title = '';
      }, 1600);
    }
  }

  function announce(message) {
    if (live) live.textContent = message;
  }

  function toast(message) {
    let container = document.getElementById('budget-toast');
    if (!container) {
      container = document.createElement('div');
      container.id = 'budget-toast';
      container.className = 'toast toast-end toast-bottom';
      container.style.zIndex = '10000';
      document.body.appendChild(container);
    }
    const alert = document.createElement('div');
    alert.className = 'alert alert-error shadow-lg';
    alert.setAttribute('data-testid', 'budget-save-error');
    alert.textContent = message;
    container.appendChild(alert);
    setTimeout(() => alert.remove(), 6000);
  }
}
