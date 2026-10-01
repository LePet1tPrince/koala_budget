'use strict';

import { formatMoney, parseAmount } from '../common/amount';

/**
 * The goal form (templates/budget/goal_form.html).
 *
 * - Plan: a target date or a monthly amount; the sentence under them works out
 *   the other one.
 * - Where the money lives: an account's start date and starting-balance choice
 *   show only while it is ticked, the outflow choice only while any account is,
 *   and a preview (from `goal_link_preview`, which reads the form's own fields)
 *   says what saving would add to the goal and do to Unassigned.
 *
 * Without JS every field is visible and the form posts the same thing.
 */

const form = document.getElementById('goal-form');
const props = JSON.parse(document.getElementById('goal-form-props')?.textContent || '{}');

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

const monthLabel = (year, month) => `${MONTHS[month]} ${year}`;

function planSummary() {
  const target = parseAmount(form.elements.target_amount?.value);
  const monthly = parseAmount(form.elements.monthly_contribution?.value);
  const dateValue = form.elements.target_date?.value || '';
  const toFund = Math.max((target || 0) - (props.allocated || 0), 0);
  const now = new Date();

  if (!target || toFund <= 0) return '';

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
    return `About ${formatMoney(toFund / monthsLeft)}/month reaches ${formatMoney(target)} by ${monthLabel(
      y,
      m - 1,
    )}.`;
  }
  return '';
}

function renderPlan() {
  const out = form.querySelector('[data-plan-summary]');
  if (out) out.textContent = planSummary();
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

function previewQuery() {
  const params = new URLSearchParams();
  if (props.goalId) params.set('goal', props.goalId);
  const data = new FormData(form);
  for (const [key, value] of data.entries()) {
    if (key === 'outflow' || key.startsWith('link_')) params.append(key, value);
  }
  return params;
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
  const params = previewQuery();
  const hadLinks = Boolean(props.hadLinks);
  if (!params.getAll('link_account').length && !hadLinks) {
    showPreview(null);
    return;
  }
  try {
    const response = await fetch(`${props.previewUrl}?${params.toString()}`, {
      headers: { Accept: 'application/json' },
      credentials: 'same-origin',
    });
    const data = await response.json();
    if (ticket !== previewTicket) return; // a newer preview is on its way
    if (!data.ok) {
      showPreview('alert-error', escapeHtml(data.error || 'That combination can’t be saved.'));
      return;
    }
    if (Math.abs(data.adds) < 0.005 && Math.abs(data.unassignedAfter - data.unassignedBefore) < 0.005) {
      showPreview(null);
      return;
    }
    const verb = data.adds >= 0 ? 'Adds' : 'Takes';
    const negative = data.unassignedAfter < 0;
    showPreview(
      negative ? 'alert-warning' : 'alert-info',
      `<span>${verb} <strong class="money">${formatMoney(Math.abs(data.adds))}</strong> ${
        data.adds >= 0 ? 'to' : 'from'
      } this goal. Unassigned goes from <strong class="money">${escapeHtml(
        data.unassignedBeforeDisplay,
      )}</strong> to <strong class="money">${escapeHtml(data.unassignedAfterDisplay)}</strong>${
        negative ? ' (over-assigned)' : ''
      }.</span>`,
    );
  } catch {
    if (ticket === previewTicket) showPreview(null);
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
  props.hadLinks = Boolean(form.querySelector('[data-link-toggle]:checked'));
  syncLinkRows();
  renderPlan();
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
