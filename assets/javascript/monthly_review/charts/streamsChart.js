'use strict';
import Chart from 'chart.js/auto';

import { GRID, compactCurrency, getInk, seriesColors } from '../../reports/chart-theme';

/** Horizontal bar: this-month vs baseline-average per income stream. */
export function createStreamsChart(canvas, rows) {
  if (!rows || !rows.length) return null;
  const ink = getInk(canvas);
  const colors = seriesColors(2);

  return new Chart(canvas, {
    type: 'bar',
    data: {
      labels: rows.map((r) => r.payee),
      datasets: [
        { label: 'This month', data: rows.map((r) => r.amount), backgroundColor: colors[0] },
        { label: 'Average', data: rows.map((r) => r.avg), backgroundColor: 'rgba(128, 128, 128, 0.35)' },
      ],
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: ink } },
        tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${compactCurrency(ctx.parsed.x)}` } },
      },
      scales: {
        x: { grid: { color: GRID }, ticks: { color: ink, callback: compactCurrency } },
        y: { grid: { display: false }, ticks: { color: ink } },
      },
    },
  });
}
