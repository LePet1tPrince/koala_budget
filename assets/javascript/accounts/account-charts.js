'use strict';

import { readBook } from '../common/book';
import { drawBalanceChart } from '../reports/account-balance-chart';
import { drawBudgetChart } from '../reports/account-budget-chart';
import { apiErrorMessage, getAccountsApi } from './accountsApi';

/**
 * The account page's charts (`reports/components/account_activity_section.html`),
 * loaded from the charts API for the range the page shows. Each canvas waits
 * behind a skeleton until the request answers.
 */

// The generated client turns ISO dates into `Date`s (UTC midnight); the charts work in ISO days.
const isoDay = (value) => (value instanceof Date ? value.toISOString().slice(0, 10) : value);

const balanceData = (chart) => ({
  start_date: isoDay(chart.startDate),
  end_date: isoDay(chart.endDate),
  starting_balance: chart.startingBalance,
  ending_balance: chart.endingBalance,
  points: chart.points.map((point) => ({ date: isoDay(point.date), balance: point.balance })),
});

function settle(canvasId, message) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  canvas.removeAttribute('aria-busy');
  const skeleton = document.querySelector(`[data-chart-loading="${canvasId}"]`);
  if (!skeleton) return;
  if (message) {
    skeleton.classList.remove('skeleton');
    skeleton.className += ' flex items-center justify-center text-sm text-base-content/70';
    skeleton.removeAttribute('aria-hidden');
    skeleton.textContent = message;
  } else {
    skeleton.remove();
  }
}

async function loadCharts() {
  const section = document.getElementById('account-activity');
  const balanceCanvas = document.getElementById('account-balance-chart');
  const budgetCanvas = document.getElementById('account-budget-chart');
  if (!section || (!balanceCanvas && !budgetCanvas)) return;

  const book = readBook();
  const { accountId, startDate, endDate } = section.dataset;
  try {
    const charts = await getAccountsApi().accountsAccountsCharts({
      ...book.params,
      id: Number(accountId),
      startDate,
      endDate,
    });
    settle('account-balance-chart');
    settle('account-budget-chart');
    if (balanceCanvas && charts.balance) drawBalanceChart(balanceCanvas, balanceData(charts.balance));
    if (budgetCanvas && charts.budget) drawBudgetChart(budgetCanvas, charts.budget);
  } catch (error) {
    const message = await apiErrorMessage(error);
    settle('account-balance-chart', message);
    settle('account-budget-chart', message);
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', loadCharts);
} else {
  loadCharts();
}
