// Goals page: quick-assign buttons, count-up animations and celebrations.
// Server-rendered cards carry data attributes; this module wires them up and
// moves money through the goal API (apps/budget/api/goals.py) via `api-client`.
import { apiCall } from '../api';
import { formatMoney, parseAmount } from '../common/amount';
import { fireConfetti } from '../common/confetti';
import { apiMonth, budget } from './budget-api';

const root = document.querySelector('[data-goals-root]');
// Unassigned for the page's month and the goals' saved total: loaded from the
// goals API on start (the quick-assign buttons wait for it), then kept from each answer.
let available = null;
let unassignedLabel = 'Unassigned';
let totalSaved = 0;

const fmt = (amount) => formatMoney(amount);

// ---------------------------------------------------------------------------
// Number animation
// ---------------------------------------------------------------------------

function animateNumber(el, from, to, { duration = 900 } = {}) {
  if (!el) return;
  const format = el.dataset.format || 'currency';
  const render = (value) => {
    el.textContent = format === 'pct' ? `${Math.round(value)}%` : fmt(value);
  };
  const start = performance.now();
  const tick = (now) => {
    const t = Math.min((now - start) / duration, 1);
    const eased = 1 - Math.pow(1 - t, 3);
    render(from + (to - from) * eased);
    if (t < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

// ---------------------------------------------------------------------------
// Toasts
// ---------------------------------------------------------------------------

function toast(message, kind = 'success') {
  let container = document.getElementById('goals-toast');
  if (!container) {
    container = document.createElement('div');
    container.id = 'goals-toast';
    container.className = 'toast toast-end toast-bottom';
    container.style.zIndex = '10000';
    document.body.appendChild(container);
  }
  const alert = document.createElement('div');
  alert.className = `alert alert-${kind} shadow-lg`;
  alert.setAttribute('data-testid', 'goals-toast-alert');
  alert.textContent = message;
  container.appendChild(alert);
  setTimeout(() => alert.remove(), 5000);
}

// ---------------------------------------------------------------------------
// Celebrations
// ---------------------------------------------------------------------------

function celebrate(card, data) {
  const rect = card.getBoundingClientRect();
  fireConfetti({ origin: { x: rect.left + rect.width / 2, y: rect.top + rect.height / 3 }, count: 110 });
  if (data.completed) setTimeout(() => fireConfetti({ origin: 'sky', count: 200 }), 300);
}

function successMessage(data) {
  const { goal } = data;
  if (data.completed) {
    return `🎉 ${goal.name} is fully funded! You did it!`;
  }
  if (!goal.hasTarget) {
    return `+${fmt(data.amount)} — ${goal.name} is at ${Math.round(goal.pct)}% of this month's contribution.`;
  }
  return `+${fmt(data.amount)} — ${goal.name} is now ${Math.round(goal.pct)}% funded (was ${Math.round(data.before.pct)}%).`;
}

// ---------------------------------------------------------------------------
// Card + page updates
// ---------------------------------------------------------------------------

function refreshAssignButtons() {
  if (available === null) return; // still loading: the server-rendered state stands
  document.querySelectorAll('[data-goal-card]').forEach((card) => {
    const remaining = parseFloat(card.dataset.remaining || '0');
    // Withdrawals are capped at what the goal has left (allocated − spent).
    const left = parseFloat(card.dataset.left ?? card.dataset.saved ?? '0');
    const btn = card.querySelector('[data-assign-all]');
    if (btn) {
      // An open-ended goal (no target) never runs out of room: once this month's
      // contribution is in, the button adds whatever is available.
      const openEnded = 'openEnded' in card.dataset;
      const funded = card.classList.contains('is-funded') || (remaining <= 0 && !openEnded);
      const finish = !funded && available >= remaining && remaining > 0;
      const amount = finish ? remaining : available;
      const label = finish ? btn.dataset.labelFinish : btn.dataset.labelAll;
      const labelEl = btn.querySelector('[data-assign-label]') || btn;
      labelEl.textContent = `${label} (${fmt(Math.max(amount, 0))})`;
      btn.disabled = funded || available <= 0;
    }
    const withdrawAll = card.querySelector('[data-withdraw-all]');
    if (withdrawAll) {
      const labelEl = withdrawAll.querySelector('[data-withdraw-all-label]') || withdrawAll;
      labelEl.textContent = `${withdrawAll.dataset.labelAll} (${fmt(Math.max(left, 0))})`;
      withdrawAll.disabled = left <= 0;
    }
    const withdrawBtn = card.querySelector('[data-withdraw-btn]');
    if (withdrawBtn) withdrawBtn.disabled = left <= 0;
  });
  document.querySelectorAll('[data-available-display]').forEach((el) => {
    el.textContent = fmt(available);
    el.classList.toggle('text-success', available > 0);
    el.classList.toggle('text-error', available < 0);
  });
  // The figure's own name flips to "Over-assigned" below zero (the API names it).
  document.querySelectorAll('[data-unassigned-label]').forEach((el) => {
    el.textContent = unassignedLabel;
  });
  document.querySelectorAll('[data-saved-display]').forEach((el) => {
    el.textContent = fmt(totalSaved);
  });
}

// The close dialog is rendered once per card with every case in the markup; after an
// in-place assign/withdraw/cover, show the case that now applies and its figures.
function refreshCloseDialog(card, allocated, spent, left) {
  const root = card.querySelector('[data-close-root]');
  if (!root) return;
  const kind = left > 0 ? 'pos' : left < 0 ? 'neg' : 'zero';
  root.querySelectorAll('[data-close-case]').forEach((el) => {
    el.hidden = !el.dataset.closeCase.split(' ').includes(kind);
  });
  const values = { allocated, spent, left, cover: Math.max(-left, 0) };
  root.querySelectorAll('[data-close-num]').forEach((el) => {
    el.textContent = fmt(values[el.dataset.closeNum]);
  });
  root.querySelectorAll('[data-close-num="left"]').forEach((el) => el.classList.toggle('text-error', left < 0));
  const cover = root.querySelector('[data-close-cover]');
  if (cover) cover.disabled = left >= 0;
}

// `data` is the API's answer to an assign or withdraw: the goal's card after
// (`goal`) and its allocated total and bar before (`before`).
function updateCard(card, data) {
  const { goal } = data;
  const oldSaved = Number(data.before.allocated);
  const newSaved = Number(goal.allocated);
  const remaining = Number(goal.remaining);
  const left = Number(goal.left);
  const thisMonth = Number(goal.thisMonth);
  card.dataset.remaining = String(remaining);
  card.dataset.saved = String(newSaved);
  card.dataset.left = String(left);

  // Works in both directions: positive delta = assignment, negative = withdrawal
  const delta = newSaved - oldSaved;

  const allocatedEl = card.querySelector('[data-num="allocated"]');
  if (allocatedEl) animateNumber(allocatedEl, oldSaved, newSaved);

  refreshCloseDialog(card, newSaved, Number(goal.spent), left);
  const leftEl = card.querySelector('[data-num="left"]');
  if (leftEl) {
    animateNumber(leftEl, left - delta, left);
    leftEl.classList.toggle('text-error', left < 0);
  }
  card.querySelectorAll('[data-carried]').forEach((el) => {
    el.hidden = left >= 0;
  });

  animateNumber(card.querySelector('[data-num="saved"]'), oldSaved, newSaved);
  animateNumber(card.querySelector('[data-num="pct"]'), data.before.pct, goal.pct);
  const remainingEl = card.querySelector('[data-num="remaining"]');
  if (remainingEl) {
    animateNumber(remainingEl, Math.max(remaining + delta, 0), remaining);
  }
  const thisMonthEl = card.querySelector('[data-num="this-month"]');
  if (thisMonthEl) {
    animateNumber(thisMonthEl, thisMonth - delta, thisMonth);
  }

  const fill = card.querySelector('[data-fill]');
  if (fill) fill.style.height = `${goal.pct}%`;

  const funded = data.completed || goal.funded;
  card.classList.toggle('is-funded', !!funded);
  const fundedBadge = card.querySelector('[data-funded-badge]');
  if (fundedBadge) fundedBadge.hidden = !funded;
  const savingPill = card.querySelector('[data-saving-pill]');
  if (savingPill) savingPill.hidden = !!funded;
}

function applyUnassigned(unassigned) {
  available = Number(unassigned.amount);
  unassignedLabel = unassigned.label;
}

// ---------------------------------------------------------------------------
// Assign / withdraw flows
// ---------------------------------------------------------------------------

async function postMoney(card, withdrawing, amount, failMessage) {
  const buttons = card.querySelectorAll(
    '[data-assign-all], [data-assign-custom], [data-withdraw-btn], [data-withdraw-all]',
  );
  buttons.forEach((b) => b.classList.add('btn-disabled'));
  try {
    const { api, params } = budget();
    const goalFundsRequest = { month: apiMonth(root.dataset.month), amount: amount == null ? null : String(amount) };
    const request = { ...params, id: Number(card.dataset.goalId), goalFundsRequest };
    return await apiCall(withdrawing ? api.budgetGoalsWithdraw(request) : api.budgetGoalsAssign(request));
  } catch (e) {
    toast(e.status ? e.message || failMessage : `${failMessage} Check your connection and try again.`, 'error');
    return null;
  } finally {
    buttons.forEach((b) => b.classList.remove('btn-disabled'));
  }
}

async function assign(card, amount) {
  const data = await postMoney(card, false, amount, 'Could not assign funds.');
  if (!data) return;
  applyUnassigned(data.unassigned);
  totalSaved += Number(data.amount);
  updateCard(card, data);
  refreshAssignButtons();
  celebrate(card, data);
  toast(successMessage(data), 'success');
  const input = card.querySelector('[data-custom-input]');
  if (input) input.value = '';
  // Covered: the goal is no longer carried negative.
  if (Number(data.goal.left) >= 0) card.querySelector('[data-testid="goal-negative"]')?.remove();
  return data;
}

function withdrawMessage(data) {
  return `−${fmt(data.amount)} from ${data.goal.name} — ${fmt(data.unassigned.amount)} back in ${data.unassigned.label}.`;
}

async function withdraw(card, amount) {
  const data = await postMoney(card, true, amount, 'Could not withdraw funds.');
  if (!data) return;
  applyUnassigned(data.unassigned);
  totalSaved -= Number(data.amount);
  updateCard(card, data);
  refreshAssignButtons();
  card.classList.add('withdrawing');
  setTimeout(() => card.classList.remove('withdrawing'), 900);
  toast(withdrawMessage(data), 'info');
  const input = card.querySelector('[data-withdraw-input]');
  if (input) input.value = '';
}

// Unassigned and the saved total for the page's month. The quick-assign buttons
// show what they would add, so they wait (busy) until it is in.
async function loadFigures() {
  const quick = document.querySelectorAll('[data-assign-all]');
  root.setAttribute('aria-busy', 'true');
  quick.forEach((b) => b.classList.add('btn-disabled'));
  try {
    const { api, params } = budget();
    const page = await apiCall(api.budgetGoalsList({ ...params, month: apiMonth(root.dataset.month) }));
    applyUnassigned(page.unassigned);
    totalSaved = Number(page.summary.totalSaved);
    refreshAssignButtons();
  } catch {
    // The page as the server rendered it still works; the first assign brings the figures.
  } finally {
    root.removeAttribute('aria-busy');
    quick.forEach((b) => b.classList.remove('btn-disabled'));
  }
}

function init() {
  if (!root) return;
  loadFigures();

  document.querySelectorAll('[data-goal-card]').forEach((card) => {
    card.querySelector('[data-assign-all]')?.addEventListener('click', () => assign(card, null));

    const customBtn = card.querySelector('[data-assign-custom]');
    const customInput = card.querySelector('[data-custom-input]');
    const submitCustom = () => {
      const value = parseAmount(customInput?.value);
      if (!value || value <= 0) {
        toast('Enter an amount above zero first.', 'warning');
        return;
      }
      assign(card, value);
    };
    customBtn?.addEventListener('click', submitCustom);
    customInput?.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        submitCustom();
      }
    });

    // A goal carried negative: cover it from Unassigned now, or keep paying it
    // back month by month through the ordinary custom-amount box.
    card.querySelector('[data-cover]')?.addEventListener('click', (event) => {
      const amount = parseFloat(event.currentTarget.dataset.amount);
      if (amount > 0) assign(card, amount);
    });
    card.querySelector('[data-pay-back]')?.addEventListener('click', () => customInput?.focus());

    const withdrawRow = card.querySelector('[data-withdraw-row]');
    card.querySelector('[data-withdraw-toggle]')?.addEventListener('click', () => {
      withdrawRow.hidden = !withdrawRow.hidden;
      if (!withdrawRow.hidden) withdrawRow.querySelector('[data-withdraw-input]')?.focus();
    });
    card.querySelector('[data-withdraw-all]')?.addEventListener('click', () => withdraw(card, null));
    const withdrawBtn = card.querySelector('[data-withdraw-btn]');
    const withdrawInput = card.querySelector('[data-withdraw-input]');
    const submitWithdraw = () => {
      const value = parseAmount(withdrawInput?.value);
      if (!value || value <= 0) {
        toast('Enter an amount above zero first.', 'warning');
        return;
      }
      withdraw(card, value);
    };
    withdrawBtn?.addEventListener('click', submitWithdraw);
    withdrawInput?.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        submitWithdraw();
      }
    });
  });

  // Server renders final fill heights (works without JS); replay them from zero
  // on first paint so the thermometers visibly climb.
  document.querySelectorAll('[data-fill]').forEach((el) => {
    el.style.transition = 'none';
    el.style.height = '0%';
    void el.offsetHeight;
    el.style.transition = '';
    requestAnimationFrame(() => {
      el.style.height = `${el.dataset.pct}%`;
    });
  });
}

init();
