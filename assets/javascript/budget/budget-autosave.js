// Budget page: save an amount in place, without navigating.
//
// Each row used to submit its own <form>, so every blur triggered a POST, a
// redirect and a full page load — which reset the scroll position to the top
// and dropped focus. Typing down a column was unusable. Here the amount is
// saved through the budget API (`budgetAmountSave`), which answers with the
// month's figures recomputed; budget-api.js paints them into the
// `data-budget-cell` spans the templates carry.
//
// The same module runs the two other writes that move this month's figures —
// covering an overspent row and the sidebar's Auto-Assign — so every write
// shares one ordering: a stale response never overwrites fresher totals.
//
// The <noscript> Save buttons (and the Auto-Assign forms' own action) remain
// the fallback when JS is disabled.
import { computeFormula, formatMoney, parseAmount } from '../common/amount';
import { apiMonth, budget, errorMessage, fetchMonth, paintFigures, rowsById } from './budget-api';

/* globals gettext */

const t = (text) => (typeof gettext === 'function' ? gettext(text) : text);

// A write made elsewhere on the page that moves this month's figures without
// going through a budget save — the Actual popover moving a transaction to
// another category changes actuals, so Available, the meters, the totals and
// Unassigned all move. Registered once; it repaints whichever table `init`
// last bound.
let refreshFigures = null;
document.addEventListener('budget:actuals-changed', () => refreshFigures?.());

// Changed month in place (month-swap.js): the same rows, another month.
let monthChanged = null;
document.addEventListener('budget:month-changed', (event) => monthChanged?.(event.detail));

// Auto-Assign: the sidebar's inline script confirms (and adds the selection to
// the form), then submits it; that submission is ours to send over the API.
let autofill = null;
document.addEventListener('submit', (event) => {
  const form = event.target.closest?.('form[data-autofill-form]');
  if (!form || event.defaultPrevented || !autofill) return;
  event.preventDefault();
  autofill(form);
});

init();

// A redraw replaces the table (month-swap.js `redraw`, after hiding a
// category), so every form and figure this module holds a reference to is
// thrown away and rebuilt. Bind again over the new markup: the previous
// listeners went out with the elements they were attached to, and all the state
// below is per-call.
document.addEventListener('budget:swapped', init);

function init() {
  refreshFigures = null;
  monthChanged = null;
  autofill = null;
  const forms = Array.from(document.querySelectorAll('form[data-budget-autosave]'));
  if (!forms.length) return;
  const { api, params } = budget();

  // A stale response must never overwrite fresher totals: each request takes a
  // ticket, and only the newest one that has come back gets to paint.
  let ticket = 0;
  let painted = 0;
  // The newest figures painted, for the cover dialog (Unassigned, the goals).
  let latest = null;

  // One shared live region: the per-row dot is decorative, so save state has to
  // reach a screen reader some other way.
  const live = document.querySelector('[data-budget-live]');

  const rows = forms
    .map((form) => {
      const input = form.querySelector('input[name="budget_amount"]');
      return input ? makeRow(form, input) : null;
    })
    .filter(Boolean);

  rows.forEach((row, index) => wire(row, index));
  const cover = wireCover();
  refreshFigures = refetchFigures;
  autofill = runAutofill;
  monthChanged = ({ figures }) => {
    // Responses still in flight belong to the month just left.
    painted = ++ticket;
    latest = figures;
    rows.forEach((row) => {
      row.month = row.form.dataset.month;
      row.saved = row.input.value;
      row.queued = null;
      row.input.classList.remove('input-error');
      setStatus(row, '');
    });
    cover?.close();
  };

  const currentMonth = () => forms[0].dataset.month;

  function paint(figures, mine) {
    if (mine <= painted) return;
    painted = mine;
    latest = figures;
    paintFigures(figures);
  }

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

    // With JS on, the row never navigates: saving happens over the API.
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
        focusRow(index, event.shiftKey ? -1 : 1);
      } else if (event.key === 'ArrowDown') {
        event.preventDefault();
        commit(row);
        focusRow(index, 1);
      } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        commit(row);
        focusRow(index, -1);
      } else if (event.key === 'Escape') {
        event.preventDefault();
        input.value = row.saved;
        setStatus(row, '');
        input.select();
      }
    });
  }

  // The next row in `step`'s direction that is on screen: a collapsed hidden
  // category's field, or one on another tab, is still in the list but cannot
  // take focus — and moving down a column must never land on a tab out of view.
  function focusRow(index, step) {
    for (let i = index + step; i >= 0 && i < rows.length; i += step) {
      const target = rows[i];
      if (target.input.closest('[hidden]')) continue;
      target.input.focus();
      target.input.select();
      return;
    }
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
    // A formula ("120+35") is saved as its result, and shown as it.
    // `common/amount-fields.js` normally swaps it first; this covers Up/Down,
    // which commit without a `change` event.
    const typed = row.input.value.trim();
    const value = computeFormula(typed) ?? typed;
    if (value !== typed) row.input.value = value;
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
    const month = row.month;

    let result;
    try {
      result = await api.budgetAmountSave({
        ...params,
        budgetAmountRequest: { categoryId: Number(row.categoryId), month: apiMonth(month), amount: value },
      });
    } catch (error) {
      row.inFlight = false;
      const fallback = error?.response
        ? t('Could not save that amount.')
        : t('Could not reach the server. Your change was not saved.');
      fail(row, await errorMessage(error, fallback));
      return;
    }

    row.inFlight = false;
    // Saved, but the page has moved to another month since: nothing on screen is that month's.
    if (row.month !== month) return;

    row.saved = result.amount;
    // Normalize the display to 2dp — but never yank the text out from under
    // someone who has focused the field again and is typing.
    if (document.activeElement !== row.input) {
      row.input.value = result.amount;
    }
    row.input.classList.remove('input-error');
    setStatus(row, 'saved');
    announce(`${row.categoryName} saved as ${result.amount}.`);
    paint(result.figures, mine);

    if (row.queued !== null) {
      const next = row.queued;
      row.queued = null;
      if (!sameAmount(next, row.saved)) save(row, next);
    }
  }

  // Re-read every figure for the month and paint it. Shares the tickets, so
  // whichever of a save and a refresh was *sent* last is what stays on screen.
  async function refetchFigures() {
    const mine = ++ticket;
    try {
      paint(await fetchMonth(currentMonth()), mine);
    } catch {
      // The next save or month change catches up.
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

  /** Every amount field to the budgets in `figures` (after a write that set many). */
  function syncInputs(figures) {
    const byId = rowsById(figures);
    rows.forEach((row) => {
      const data = byId.get(String(row.categoryId));
      if (!data || row.inFlight || document.activeElement === row.input) return;
      row.saved = data.budgeted;
      row.input.value = Number(data.budgeted) ? data.budgeted : '';
    });
  }

  // -------------------------------------------------------------------------
  // Auto-Assign
  // -------------------------------------------------------------------------

  const AUTOFILL_DONE = {
    assigned_last_month: "Budgets set to last month's assigned amounts.",
    spent_last_month: "Budgets set to last month's spending.",
    assign_zero: 'Budgets set to zero.',
    reset_available_zero: 'Budgets adjusted so all available amounts are zero.',
  };

  async function runAutofill(form) {
    const action = form.elements.action.value;
    // The inline script marks an explicit selection with `filtered`; without it the
    // action reaches the whole tab, as the plain form post does.
    const filtered = Boolean(form.elements.filtered?.value);
    const categoryIds = filtered
      ? Array.from(form.querySelectorAll('input[name="category_ids"]')).map((input) => Number(input.value))
      : null;
    const buttons = form.querySelectorAll('button');
    buttons.forEach((button) => {
      button.disabled = true;
    });
    const mine = ++ticket;
    try {
      const result = await api.budgetAutofill({
        ...params,
        autofillRequest: {
          action,
          month: apiMonth(form.elements.month.value),
          section: form.elements.section?.value || undefined,
          categoryIds,
        },
      });
      if (mine > painted) syncInputs(result.figures);
      paint(result.figures, mine);
      announce(t(AUTOFILL_DONE[action] || 'Budgets updated.'));
    } catch (error) {
      const message = await errorMessage(error, t('Could not apply Auto-Assign.'));
      announce(message);
      toast(message);
    } finally {
      buttons.forEach((button) => {
        button.disabled = false;
      });
    }
  }

  // -------------------------------------------------------------------------
  // Cover an overspent row: from Unassigned, or from a goal
  // -------------------------------------------------------------------------

  function parseMoney(text) {
    const n = parseFloat(String(text).replace(/[^0-9.-]/g, ''));
    return Number.isFinite(n) ? n : 0;
  }

  function wireCover() {
    const dialog = document.querySelector('[data-cover-dialog]');
    if (!dialog) return null;
    const form = dialog.querySelector('[data-cover-form]');
    const select = form.querySelector('select[name="goal_id"]');
    const goalOption = form.querySelector('[data-cover-goal-option]');
    const goalRadio = form.querySelector('input[name="source"][value="goal"]');
    const unassignedRadio = form.querySelector('input[name="source"][value="unassigned"]');
    const amountInput = form.querySelector('input[name="amount"]');
    const submit = form.querySelector('button[type="submit"]');
    const unassignedEl = dialog.querySelector('[data-cover-unassigned]');
    const unassignedLabelEl = dialog.querySelector('[data-unassigned-label-text]');
    const hint = dialog.querySelector('[data-cover-hint]');
    const error = dialog.querySelector('[data-cover-error]');
    const intro = dialog.querySelector('[data-cover-intro]');
    let current = null;
    let currentShortfall = 0;
    let goals = [];

    // The page's own figures, so the dialog can't disagree with the table beside it.
    const unassignedNow = () => Number(latest?.unassigned.amount ?? 0);
    const unassignedLabel = () => latest?.unassigned.label || 'Unassigned';
    const source = () => (goalRadio?.checked && !goalOption?.hidden ? 'goal' : 'unassigned');
    const selectedGoal = () => goals.find((g) => String(g.id) === select?.value);

    const fillGoals = () => {
      goals = (latest?.coverGoals ?? []).map((goal) => ({ ...goal }));
      if (goalOption) goalOption.hidden = !goals.length;
      if (!select) return;
      select.replaceChildren(
        ...goals.map((goal) => {
          const option = document.createElement('option');
          option.value = goal.id;
          option.textContent = `${goal.name} · ${formatMoney(goal.left)} left`;
          return option;
        }),
      );
      const richest = goals.reduce((a, b) => (Number(b.left) > Number(a.left) ? b : a), goals[0]);
      if (richest) select.value = String(richest.id);
    };

    // What covering does to Unassigned. The overspending already came out of it (an
    // overspent envelope claims nothing), so filling the hole is free: only budget
    // past the shortfall is a new claim, and money a goal gives up (while it has any
    // left) is released. See apps/budget/unassigned.py.
    const unassignedChange = (amount) => {
      const newClaim = Math.max(0, amount - currentShortfall);
      if (source() === 'unassigned') return -newClaim;
      const goal = selectedGoal();
      const released = goal ? Math.min(amount, Math.max(0, Number(goal.left))) : 0;
      return released - newClaim;
    };

    // Non-blocking: both are allowed, the user should just know what they mean.
    const refreshHint = () => {
      const amount = parseAmount(amountInput.value) ?? 0;
      const messages = [];
      let warn = false;
      if (amount > 0 && latest) {
        const before = unassignedNow();
        const after = before + unassignedChange(amount);
        if (Math.abs(after - before) >= 0.005) {
          messages.push(`${unassignedLabel()}: ${formatMoney(before)} → ${formatMoney(after)}.`);
        }
        if (after < 0) {
          messages.push(`This leaves you over-assigned by ${formatMoney(-after)}.`);
          warn = true;
        }
        const goal = source() === 'goal' ? selectedGoal() : null;
        const goalAfter = goal ? Number(goal.left) - amount : 0;
        if (goal && goalAfter < 0) {
          messages.push(`${goal.name} will go to ${formatMoney(goalAfter)}.`);
          warn = true;
        }
      }
      const message = messages.join(' ');
      hint.textContent = message;
      hint.hidden = !message;
      hint.classList.toggle('text-warning', warn);
      hint.classList.toggle('text-base-content/70', !warn);
      dialog.querySelectorAll('[data-cover-explain]').forEach((el) => {
        el.hidden = el.dataset.coverExplain !== source();
      });
    };

    // Unassigned and the goals as of now: from the last figures painted, else
    // (nothing written yet on this page) loaded while the dialog says so.
    const showSources = () => {
      fillGoals();
      const unassigned = unassignedNow();
      unassignedEl.textContent = latest ? formatMoney(unassigned) : t('Loading…');
      unassignedEl.classList.toggle('text-error', Boolean(latest) && unassigned < 0);
      unassignedLabelEl.textContent = unassignedLabel();
      submit.disabled = !latest;
      refreshHint();
    };

    form.addEventListener('change', refreshHint);
    amountInput.addEventListener('input', refreshHint);
    // Picking a goal means taking the money from a goal.
    select?.addEventListener('focus', () => {
      if (goalRadio) goalRadio.checked = true;
      refreshHint();
    });

    document.querySelectorAll('[data-cover]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const row = latest ? rowsById(latest).get(btn.dataset.categoryId) : null;
        const cell = document.querySelector(`[data-budget-cell="row:${btn.dataset.categoryId}:available"]`);
        const available = row ? Number(row.available) : parseMoney(cell?.textContent ?? '0');
        const shortfall = Math.max(0, -available);
        current = btn;
        currentShortfall = shortfall;
        amountInput.value = shortfall > 0 ? shortfall.toFixed(2) : '';
        intro.textContent = `${btn.dataset.categoryName} is ${formatMoney(-shortfall)}.`;
        // Unassigned first: the overspending has already come out of it, so covering
        // from it costs nothing more.
        unassignedRadio.checked = true;
        error.hidden = true;
        showSources();
        dialog.showModal();
        amountInput.select();
        if (!latest) {
          const mine = ++ticket;
          try {
            paint(await fetchMonth(currentMonth()), mine);
          } catch {
            error.textContent = t('Could not load your goals and unassigned money.');
            error.hidden = false;
          }
          if (dialog.open && current === btn) showSources();
        }
      });
    });
    dialog.querySelector('[data-cover-cancel]').addEventListener('click', () => dialog.close());

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (!current) return;
      const from = source();
      const target = current;
      const mine = ++ticket;
      let result;
      try {
        result = await api.budgetCover({
          ...params,
          coverRequest: {
            categoryId: Number(target.dataset.categoryId),
            month: apiMonth(target.dataset.month),
            amount: computeFormula(amountInput.value) ?? amountInput.value,
            source: from,
            ...(from === 'goal' ? { goalId: Number(select.value) } : {}),
          },
        });
      } catch (failure) {
        error.textContent = await errorMessage(failure, t('Could not cover that.'));
        error.hidden = false;
        return;
      }
      const goal = from === 'goal' ? selectedGoal() : null;
      // The row's budget changed: show it, and keep the autosave baseline in step.
      const row = rows.find((r) => String(r.categoryId) === target.dataset.categoryId);
      if (row) {
        row.saved = result.amount;
        row.input.value = result.amount;
      }
      paint(result.figures, mine);
      dialog.close();
      announce(`${target.dataset.categoryName} covered from ${goal ? goal.name : 'unassigned money'}.`);
    });

    return { close: () => dialog.open && dialog.close() };
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
