'use strict';

import { AccountChartsFromJSON } from 'api-client';

import { pageData } from '../api';
import { drawBalanceChart } from '../reports/account-balance-chart';
import { drawBudgetChart } from '../reports/account-budget-chart';

/**
 * The account page's charts (`reports/components/account_activity_section.html`),
 * from the `GET …/accounts/api/accounts/{id}/charts/` body the page embeds for the
 * range it shows (`#account-charts-data`). Each canvas sits behind a skeleton until drawn.
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

function settle(canvasId) {
  document.getElementById(canvasId)?.removeAttribute('aria-busy');
  document.querySelector(`[data-chart-loading="${canvasId}"]`)?.remove();
}

function loadCharts() {
  const balanceCanvas = document.getElementById('account-balance-chart');
  const budgetCanvas = document.getElementById('account-budget-chart');
  const charts = pageData('account-charts-data', AccountChartsFromJSON);
  if (!charts || (!balanceCanvas && !budgetCanvas)) return;
  settle('account-balance-chart');
  settle('account-budget-chart');
  if (balanceCanvas && charts.balance) drawBalanceChart(balanceCanvas, balanceData(charts.balance));
  if (budgetCanvas && charts.budget) drawBudgetChart(budgetCanvas, charts.budget);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', loadCharts);
} else {
  loadCharts();
}
