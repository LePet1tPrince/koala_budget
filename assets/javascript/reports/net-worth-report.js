import { NetWorthReportFromJSON } from 'api-client';

import { drawCompositionChart } from './net-worth-composition-chart';
import { drawNetWorthChart } from './net-worth-chart';

import { isoDate, numbers, onReady, pageData } from './report-data';

/**
 * The Net Worth page's charts, from the `GET …/reports/api/net-worth/` body the page
 * embeds for its own months (`#net-worth-report-data`).
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
  const totals = document.getElementById('net-worth-chart');
  const composition = document.getElementById('net-worth-composition-chart');
  const report = pageData('net-worth-report-data', NetWorthReportFromJSON);
  if (!report) return;
  if (totals) drawNetWorthChart(totals, trendData(report));
  if (composition && report.composition) drawCompositionChart(composition, compositionData(report));
});
