import { drawCashFlowChart } from './cash-flow-chart';
import { drawSankey } from './income-statement-sankey';
import { apiDate, bookParams, getReportsApi, loadChart, numbers, onReady } from './report-data';

/**
 * The Income & Spending page's charts, from `GET …/reports/api/spending/` on the
 * range and columns the page itself resolved (`#spending-report`'s data attributes).
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
  const page = document.getElementById('spending-report');
  const cashFlow = document.getElementById('cash-flow-chart');
  const flow = document.getElementById('sankey-chart');
  if (!page || (!cashFlow && !flow)) return;

  const { startDate, endDate, columns } = page.dataset;
  // One request for both charts.
  const request = getReportsApi().reportsSpendingRetrieve({
    ...bookParams(),
    startDate: apiDate(startDate),
    endDate: apiDate(endDate),
    columns: columns || undefined,
  });
  if (cashFlow)
    loadChart(
      cashFlow,
      () => request,
      (report) => drawCashFlowChart(cashFlow, cashFlowData(report)),
    );
  if (flow)
    loadChart(
      flow,
      () => request,
      (report) => drawSankey(flow, sankeyData(report)),
    );
});
