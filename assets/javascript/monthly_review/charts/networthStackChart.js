'use strict';
import Chart from 'chart.js/auto';

import { GRID, compactCurrency, currency, getInk, getSurface, seriesColors } from '../../reports/chart-theme';

// Liability bands are negative here; show the sign ahead of the dollar sign.
const signed = (format) => (value) => (value < 0 ? `-${format(-value)}` : format(value));
const money = signed(currency);
const compactMoney = signed(compactCurrency);

/**
 * Stacked area of net worth by account group over the selected baseline span.
 * Asset groups stack above zero and liability groups below it (their balances
 * are negated), so the bands at any month sum to net worth -- which the
 * tooltip footer states. Relies on the server listing asset bands before
 * liability bands.
 */
export function createNetWorthStackChart(canvas, series, stack) {
  if (!series || !series.length) return null;
  const labels = series.map((s) => s.label);
  const colors = seriesColors(Math.max(stack.length, 1));
  const ink = getInk(canvas);
  const surface = getSurface(canvas);

  // No observeTheme(): ChartCanvas rebuilds this chart on every baseline change,
  // and that helper's MutationObserver is never disconnected.
  return new Chart(canvas, {
    type: 'line',
    data: {
      labels,
      datasets: stack.map((s, i) => {
        const color = colors[i % colors.length];
        const isLiability = s.type === 'liability';
        // Assets and liabilities stack separately, so a $0 liability month sits
        // on zero rather than on top of the asset pile. Each band fills down to
        // the band beneath it; the first band of each stack fills to zero.
        const firstOfStack = i === 0 || stack[i - 1].type !== s.type;
        return {
          label: s.bucket,
          data: isLiability ? s.values.map((v) => -v) : s.values,
          stack: isLiability ? 'liabilities' : 'assets',
          fill: firstOfStack ? 'origin' : '-1',
          borderColor: color,
          backgroundColor: `${color}4d`, // ~30% alpha wash between stack bands
          pointBackgroundColor: color,
          pointBorderColor: surface,
          borderWidth: 2,
          pointRadius: 2,
          pointBorderWidth: 2,
          pointHoverRadius: 5,
          tension: 0,
        };
      }),
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { labels: { color: ink, usePointStyle: true, pointStyle: 'circle', boxHeight: 8 } },
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.dataset.label}: ${money(ctx.parsed.y)}`,
            footer: (items) => `Net worth: ${money(items.reduce((sum, item) => sum + item.parsed.y, 0))}`,
          },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: ink, maxRotation: 0, autoSkip: true, maxTicksLimit: 12 } },
        y: {
          stacked: true,
          grid: { color: GRID },
          border: { display: false },
          ticks: { color: ink, callback: compactMoney },
        },
      },
    },
  });
}
