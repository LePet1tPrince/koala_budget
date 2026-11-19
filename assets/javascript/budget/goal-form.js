'use strict';

import { apiCall } from '../api';
import { formatMoney, parseAmount } from '../common/amount';
import { budget } from './budget-api';

/**
 * The goal form (templates/budget/goal_form.html).
 *
 * - Plan: a target date or a monthly amount; the sentence under them works out
 *   the other one, from what the goal already has (its `allocated`, loaded from
 *   the goal API while editing). With no target the goal is open-ended: the
 *   monthly amount is the whole plan.
 * - Where the money lives: an account's start date and starting-balance choice
 *   show only while it is ticked, the outflow choice only while any account is,
 *   and a preview (the goal API's link preview, sent the form's own choices)
 *   says what saving would add to the goal and do to Unassigned.
 *
 * The form itself posts to the page (the same with or without JS).
 */

const form = document.getElementById('goal-form');
const goalId = Number(form?.dataset.goalId) || null;
const state = { allocated: 0, loading: Boolean(goalId), hadLinks: false };

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

const monthLabel = (year, month) => `${MONTHS[month]} ${year}`;

function planSummary() {
  const target = parseAmount(form.elements.target_amount?.value);
  const monthly = parseAmount(form.elements.monthly_contribution?.value);
  const dateValue = form.elements.target_date?.value || '';
  const toFund = Math.max((target || 0) - state.allocated, 0);
  const now = new Date();

  if (!target) {
    // Open-ended: no target, so the monthly contribution is the whole plan.
    if (monthly && monthly > 0) {
      return `Open-ended: ${formatMoney(monthly)}/month with no finish line. Each month is on track once it's in.`;
    }
    if (dateValue) return 'A target date needs a target amount.';
    return 'Set a target amount, a monthly contribution, or both.';
  }
  if (toFund <= 0) return '';

  if (monthly && monthly > 0) {
    const months = Math.ceil(toFund / monthly);
    const finish = new Date(now.getFullYear(), now.getMonth() + months - 1, 1);
    let sentence = `${formatMoney(monthly)}/month reaches ${formatMoney(target)} by ${monthLabel(
      finish.getFullYear(),
      finish.getMonth(),
    )}.`;
    if (dateValue) {
      const [y, m] = dateValue.split('-').map(Number);
      const late = finish.getFullYear() * 12 + finish.getMonth() > y * 12 + (m - 1);
      if (late) sentence += ` That's after your target date of ${monthLabel(y, m - 1)}.`;
    }
    return sentence;
  }

  if (dateValue) {
    const [y, m] = dateValue.split('-').map(Number);
    const monthsLeft = Math.max(y * 12 + (m - 1) - (now.getFullYear() * 12 + now.getMonth()) + 1, 1);
    return `About ${formatMoney(toFund / monthsLeft)}/month reaches ${formatMoney(target)} by ${monthLabel(y, m - 1)}.`;
  }
  return '';
}

function renderPlan() {
  const out = form.querySelector('[data-plan-summary]');
  if (!out) return;
  // Editing: the sentence counts what the goal already has, so it waits for it.
  out.toggleAttribute('aria-busy', state.loading);
  out.textContent = state.loading ? '' : planSummary();
}

async function loadGoal() {
  try {
    const { api, params } = budget();
    const goal = await apiCall(api.budgetGoalsRetrieve({ ...params, id: goalId }));
    state.allocated = Number(goal.allocated) || 0;
  } catch {
    state.allocated = 0;
  } finally {
    state.loading = false;
    renderPlan();
  }
}

function syncLinkRows() {
  let any = false;
  form.querySelectorAll('[data-link-row]').forEach((row) => {
    const toggle = row.querySelector('[data-link-toggle]');
    const details = row.querySelector('[data-link-details]');
    const on = Boolean(toggle?.checked && !toggle.disabled);
    any = any || on;
    if (details) details.classList.toggle('hidden', !on);
  });
  const outflow = form.querySelector('[data-outflow-section]');
  if (outflow) outflow.classList.toggle('hidden', !any);
  return any;
}

let previewTicket = 0;
let previewTimer = null;

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;

/** The preview request from the form's own fields (the names the form posts). */
function previewRequest() {
  const data = new FormData(form);
  const links = data.getAll('link_account').map((raw) => {
    const id = Number(raw);
    const start = String(data.get(`link_start_${id}`) || '').trim();
    const startDate = ISO_DAY.test(start) ? new Date(`${start}T00:00:00Z`) : null;
    if (start && (!startDate || Number.isNaN(startDate.getTime()))) {
      throw new Error('Enter a valid start date.');
    }
    return { accountId: id, startDate, includeStartingBalance: Boolean(data.get(`link_include_${id}`)) };
  });
  return { goalId, outflow: data.get('outflow') || undefined, links };
}

function showPreview(kind, html) {
  const box = form.querySelector('[data-link-preview]');
  if (!box) return;
  box.classList.remove('hidden', 'alert-error', 'alert-warning', 'alert-info');
  if (!kind) {
    box.classList.add('hidden');
    box.textContent = '';
    return;
  }
  box.classList.add(kind);
  box.innerHTML = html;
}

async function refreshPreview() {
  const ticket = ++previewTicket;
  let request;
  try {
    request = previewRequest();
  } catch (error) {
    showPreview('alert-error', escapeHtml(error.message));
    return;
  }
  if (!request.links.length && !state.hadLinks) {
    showPreview(null);
    return;
  }
  try {
    const { api, params } = budget();
    const data = await apiCall(api.budgetGoalsLinkPreview({ ...params, goalLinkPreviewRequest: request }));
    if (ticket !== previewTicket) return; // a newer preview is on its way
    const adds = Number(data.adds);
    const before = Number(data.unassignedBefore);
    const after = Number(data.unassignedAfter);
    if (Math.abs(adds) < 0.005 && Math.abs(after - before) < 0.005) {
      showPreview(null);
      return;
    }
    const verb = adds >= 0 ? 'Adds' : 'Takes';
    const negative = after < 0;
    showPreview(
      negative ? 'alert-warning' : 'alert-info',
      `<span>${verb} <strong class="money">${formatMoney(Math.abs(adds))}</strong> ${
        adds >= 0 ? 'to' : 'from'
      } this goal. Unassigned goes from <strong class="money">${escapeHtml(
        formatMoney(before),
      )}</strong> to <strong class="money">${escapeHtml(formatMoney(after))}</strong>${
        negative ? ' (over-assigned)' : ''
      }.</span>`,
    );
  } catch (error) {
    if (ticket !== previewTicket) return;
    // A refusal (400) is what saving would say; anything else just hides the preview.
    if (error.status === 400)
      showPreview('alert-error', escapeHtml(error.message || 'That combination can’t be saved.'));
    else showPreview(null);
  }
}

function schedulePreview() {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(refreshPreview, 300);
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = String(text ?? '');
  return div.innerHTML;
}

if (form) {
  state.hadLinks = Boolean(form.querySelector('[data-link-toggle]:checked'));
  syncLinkRows();
  renderPlan();
  if (goalId) loadGoal();
  schedulePreview();

  const onChange = (event) => {
    const name = event.target?.name || '';
    if (['target_amount', 'monthly_contribution', 'target_date'].includes(name)) renderPlan();
    if (name === 'link_account') syncLinkRows();
    if (name === 'outflow' || name.startsWith('link_')) schedulePreview();
  };
  form.addEventListener('change', onChange);
  form.addEventListener('input', (event) => {
    const name = event.target?.name || '';
    if (['target_amount', 'monthly_contribution'].includes(name)) renderPlan();
  });
}
