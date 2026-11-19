import { drawCompositionChart } from './net-worth-composition-chart';
import { drawNetWorthChart } from './net-worth-chart';
import { bookParams, getReportsApi, isoDate, loadChart, numbers, onReady } from './report-data';

/**
 * The Net Worth page's charts, from `GET …/reports/api/net-worth/` on the months
 * the page itself resolved (`#net-worth-report`'s data attributes).
 */
const trendData = (report) => ({
  labels: report.trend.map((point) => isoDate(point.date)),
  net_worth: report.trend.map((point) => Number(point.netWorth)),
  assets: report.trend.map((point) => Number(point.assets)),
  liabilities: report.trend.map((point) => Number(point.liabilities)),
});

const compositionData = (report) => ({
  labels: report.composition.dates.map(isoDate),
  groups: report.composition.bands.map((band) => ({ name: band.name, type: band.type, values: numbers(band.values) })),
  net_worth: report.trend.map((point) => Number(point.netWorth)),
});

onReady(() => {
  const page = document.getElementById('net-worth-report');
  const totals = document.getElementById('net-worth-chart');
  const composition = document.getElementById('net-worth-composition-chart');
  if (!page || (!totals && !composition)) return;

  const { startMonth, endMonth } = page.dataset;
  // One request for both charts.
  const request = getReportsApi().reportsNetWorthRetrieve({ ...bookParams(), startMonth, endMonth });
  if (totals)
    loadChart(
      totals,
      () => request,
      (report) => drawNetWorthChart(totals, trendData(report)),
    );
  if (composition) {
    loadChart(
      composition,
      () => request,
      (report) => report.composition && drawCompositionChart(composition, compositionData(report)),
    );
  }
});
