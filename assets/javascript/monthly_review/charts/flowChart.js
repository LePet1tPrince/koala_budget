'use strict';
import Chart from 'chart.js/auto';

import { GRID, MONEY, compactCurrency, getInk } from '../../reports/chart-theme';

/** Income / Spend / Saved: this month vs the selected baseline's average. */
export function createFlowChart(canvas, baseline, current) {
  const labels = ['Income', 'Spend', 'Saved'];
  const datasets = [
    {
      label: 'This month',
      data: [current.income, current.spend, current.saved],
      backgroundColor: [MONEY.in, MONEY.out, MONEY.net],
    },
  ];
  if (baseline) {
    datasets.push({
      label: `${baseline.short} average`,
      data: [baseline.avgs.income, baseline.avgs.spend, baseline.avgs.saved],
      backgroundColor: 'rgba(128, 128, 128, 0.35)',
    });
  }

  const ink = getInk(canvas);
  return new Chart(canvas, {
    type: 'bar',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: ink } },
        tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${compactCurrency(ctx.parsed.y)}` } },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: ink } },
        y: { grid: { color: GRID }, ticks: { color: ink, callback: compactCurrency }, beginAtZero: true },
      },
    },
  });
}
