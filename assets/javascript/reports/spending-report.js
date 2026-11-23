import { SpendingReportFromJSON } from 'api-client';

import { drawCashFlowChart } from './cash-flow-chart';
import { drawSankey } from './income-statement-sankey';

import { numbers, onReady, pageData } from './report-data';

/**
 * The Income & Spending page's charts, from the `GET …/reports/api/spending/` body the
 * page embeds for its own range and columns (`#spending-report-data`).
 */
const cashFlowData = (report) => ({
  labels: report.periods.map((period) => period.label),
  income: numbers(report.income.perPeriod),
  expenses: numbers(report.expenses.perPeriod),
  goal_spending: report.goalSpending.goals.length ? numbers(report.goalSpending.perPeriod) : null,
  net: numbers(report.netAfterGoalSpendingPerPeriod),
});

const flowAccounts = (section) =>
  section.groups.flatMap((group) =>
    group.accounts.map((account) => ({ name: account.name, amount: Number(account.amount), group: group.name })),
  );

const flowGroups = (section) => section.groups.map((group) => ({ name: group.name, amount: Number(group.total) }));

const sankeyData = (report) => ({
  income: flowAccounts(report.income),
  expenses: flowAccounts(report.expenses),
  income_groups: flowGroups(report.income),
  expense_groups: flowGroups(report.expenses),
  net_profit: Number(report.net),
  goal_spending: Number(report.goalSpending.total),
});

onReady(() => {
  const cashFlow = document.getElementById('cash-flow-chart');
  const flow = document.getElementById('sankey-chart');
  const report = pageData('spending-report-data', SpendingReportFromJSON);
  if (!report) return;
  if (cashFlow) drawCashFlowChart(cashFlow, cashFlowData(report));
  if (flow) drawSankey(flow, sankeyData(report));
});
