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

init();

// Changing month replaces the table without reloading the page (month-swap.js),
// so every form and figure this module holds a reference to is thrown away and
// rebuilt. Bind again over the new markup: the previous listeners went out with
// the elements they were attached to, and all the state below is per-call.
document.addEventListener('budget:swapped', init);

function init() {
  const SAVE_URL = document.querySelector('[data-budget-save-url]')?.dataset.budgetSaveUrl;
  const forms = Array.from(document.querySelectorAll('form[data-budget-autosave]'));
  if (!SAVE_URL || !forms.length) return;

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
  wireCover();

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
    refreshCoverButtons();
  }

  // -------------------------------------------------------------------------
  // Cover an overspent row: from Unassigned, or from a goal
  // -------------------------------------------------------------------------

  function parseMoney(text) {
    const n = parseFloat(String(text).replace(/[^0-9.-]/g, ''));
    return Number.isFinite(n) ? n : 0;
  }

  function fmtMoney(n) {
    const abs = Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return `${n < 0 ? '-' : ''}$${abs}`;
  }

  // The button only makes sense while the row is overspent, which a save can change.
  function refreshCoverButtons() {
    document.querySelectorAll('[data-cover]').forEach((btn) => {
      const cell = cells.get(`row:${btn.dataset.categoryId}:available`);
      if (cell) btn.hidden = parseMoney(cell.textContent) >= 0;
    });
  }

  function wireCover() {
    const dialog = document.querySelector('[data-cover-dialog]');
    const url = document.querySelector('[data-cover-url]')?.dataset.coverUrl;
    if (!dialog || !url) return;
    const goalsEl = document.getElementById('cover-goals');
    const goals = goalsEl ? JSON.parse(goalsEl.textContent) : [];
    const form = dialog.querySelector('[data-cover-form]');
    const select = form.querySelector('select[name="goal_id"]');
    const goalRadio = form.querySelector('input[name="source"][value="goal"]');
    const unassignedRadio = form.querySelector('input[name="source"][value="unassigned"]');
    const amountInput = form.querySelector('input[name="amount"]');
    const unassignedEl = dialog.querySelector('[data-cover-unassigned]');
    const unassignedLabelEl = dialog.querySelector('[data-unassigned-label-text]');
    const hint = dialog.querySelector('[data-cover-hint]');
    const error = dialog.querySelector('[data-cover-error]');
    const intro = dialog.querySelector('[data-cover-intro]');
    let current = null;

    // The page's own figures, so the dialog can't disagree with the card beside it.
    const unassignedNow = () => parseMoney(cells.get('networth:available')?.textContent ?? '0');
    const source = () => (goalRadio?.checked ? 'goal' : 'unassigned');
    const selectedGoal = () => goals.find((g) => String(g.id) === select?.value);

    const fillGoals = () => {
      if (!select) return;
      select.replaceChildren(
        ...goals.map((goal) => {
          const option = document.createElement('option');
          option.value = goal.id;
          option.textContent = `${goal.name} · ${fmtMoney(parseFloat(goal.left))} left`;
          return option;
        })
      );
      const richest = goals.reduce((a, b) => (parseFloat(b.left) > parseFloat(a.left) ? b : a), goals[0]);
      if (richest) select.value = String(richest.id);
    };

    // Non-blocking: both are allowed, the user should just know what they mean.
    const refreshHint = () => {
      const amount = parseMoney(amountInput.value);
      let message = '';
      if (source() === 'unassigned') {
        const after = unassignedNow() - amount;
        if (amount > 0 && after < 0) message = `This leaves you over-assigned by ${fmtMoney(-after)}.`;
      } else {
        const goal = selectedGoal();
        const after = goal ? parseFloat(goal.left) - amount : 0;
        if (goal && amount > 0 && after < 0) {
          message = `${goal.name} will go to ${fmtMoney(after)} — that's fine, it's carried.`;
        }
      }
      hint.textContent = message;
      hint.hidden = !message;
      dialog.querySelectorAll('[data-cover-explain]').forEach((el) => {
        el.hidden = el.dataset.coverExplain !== source();
      });
    };

    form.addEventListener('change', refreshHint);
    amountInput.addEventListener('input', refreshHint);
    // Picking a goal means taking the money from a goal.
    select?.addEventListener('focus', () => {
      if (goalRadio) goalRadio.checked = true;
      refreshHint();
    });

    document.querySelectorAll('[data-cover]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const cell = cells.get(`row:${btn.dataset.categoryId}:available`);
        const shortfall = cell ? -parseMoney(cell.textContent) : 0;
        current = btn;
        fillGoals();
        amountInput.value = shortfall > 0 ? shortfall.toFixed(2) : '';
        intro.textContent = `${btn.dataset.categoryName} is ${fmtMoney(-shortfall)}.`;
        const unassigned = unassignedNow();
        unassignedEl.textContent = fmtMoney(unassigned);
        unassignedEl.classList.toggle('text-error', unassigned < 0);
        const label = cells.get('networth:label')?.textContent.trim();
        if (label) unassignedLabelEl.textContent = label;
        // Unassigned first, the way a budget is meant to absorb a surprise; a goal
        // when Unassigned can't cover it and one of them can.
        const coveringGoal = goals.find((g) => parseFloat(g.left) >= shortfall);
        if (unassigned < shortfall && coveringGoal && goalRadio) {
          goalRadio.checked = true;
          select.value = String(coveringGoal.id);
        } else {
          unassignedRadio.checked = true;
        }
        error.hidden = true;
        refreshHint();
        dialog.showModal();
        amountInput.select();
      });
    });
    dialog.querySelector('[data-cover-cancel]').addEventListener('click', () => dialog.close());

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (!current) return;
      const from = source();
      const body = {
        category_id: Number(current.dataset.categoryId),
        month: current.dataset.month,
        amount: amountInput.value,
        source: from,
      };
      if (from === 'goal') body.goal_id = Number(select.value);
      let response;
      let payload = {};
      try {
        response = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': Cookies.get('csrftoken') || '' },
          body: JSON.stringify(body),
        });
        payload = await response.json().catch(() => ({}));
      } catch {
        response = null;
      }
      if (!response || !response.ok) {
        error.textContent = payload.error || 'Could not cover that.';
        error.hidden = false;
        return;
      }
      const goal = from === 'goal' ? selectedGoal() : null;
      if (goal) goal.left = payload.goal_left;
      // The row's budget changed: show it, and keep the autosave baseline in step.
      const row = rows.find((r) => String(r.categoryId) === current.dataset.categoryId);
      if (row) {
        row.saved = payload.amount;
        row.input.value = payload.amount;
      }
      painted = ++ticket;
      paint(payload.cells);
      dialog.close();
      announce(`${current.dataset.categoryName} covered from ${goal ? goal.name : 'unassigned money'}.`);
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
