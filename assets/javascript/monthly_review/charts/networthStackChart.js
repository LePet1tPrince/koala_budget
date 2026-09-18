'use strict';
import Chart from 'chart.js/auto';

import { GRID, compactCurrency, getInk, seriesColors } from '../../reports/chart-theme';

/**
 * Stacked composition of net worth by account group over the baseline span.
 * Bars rather than an area chart -- a 2-point area is unreadable, and bars
 * degrade gracefully at any point count.
 */
export function createNetWorthStackChart(canvas, series, stack) {
  if (!series || !series.length) return null;
  const labels = series.map((s) => s.label);
  const colors = seriesColors(Math.max(stack.length, 1));
  const ink = getInk(canvas);

  return new Chart(canvas, {
    type: 'bar',
    data: {
      labels,
      datasets: stack.map((s, i) => ({
        label: s.bucket,
        data: s.values,
        backgroundColor: colors[i % colors.length],
        stack: 'composition',
      })),
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: ink, boxHeight: 8 } },
        tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${compactCurrency(ctx.parsed.y)}` } },
      },
      scales: {
        x: { stacked: true, grid: { display: false }, ticks: { color: ink, maxRotation: 0, autoSkip: true } },
        y: { stacked: true, grid: { color: GRID }, ticks: { color: ink, callback: compactCurrency } },
      },
    },
  });
}
