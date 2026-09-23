'use strict';
import Chart from 'chart.js/auto';

import { GRID, compactCurrency, currency, getInk, getSurface, seriesColors } from '../../reports/chart-theme';

// Liability bands are negative; show the sign ahead of the dollar sign.
const signed = (format) => (value) => (value < 0 ? `-${format(-value)}` : format(value));
const money = signed(currency);
const compactMoney = signed(compactCurrency);

/**
 * Bands to draw. The server sends every account on a bank feed (bank accounts
 * and credit cards) as one `cash` band, then the remaining asset and liability
 * groups, each value signed as its contribution to net worth. If the cash band
 * dips below zero anywhere in the shown months, everything collapses into one
 * "Net worth" band rather than drawing money-in-the-bank as a negative area.
 */
export function netWorthBands(stack) {
  const cash = stack.find((s) => s.type === 'cash');
  if (!cash || !cash.values.some((v) => v < 0)) return stack;
  const values = cash.values.map((_, i) => stack.reduce((sum, s) => sum + s.values[i], 0));
  return [{ bucket: 'Net worth', type: 'cash', values }];
}

/**
 * Stacked area of net worth over the selected baseline span. The cash band and
 * other asset groups stack above zero; liability groups (a mortgage, a loan --
 * anything not on a bank feed) stack below it on their own stack, so the bands
 * at any month sum to net worth, which the tooltip footer states.
 */
export function createNetWorthStackChart(canvas, series, stack) {
  if (!series || !series.length) return null;
  const bands = netWorthBands(stack);
  const labels = series.map((s) => s.label);
  const colors = seriesColors(Math.max(bands.length, 1));
  const ink = getInk(canvas);
  const surface = getSurface(canvas);

  // No observeTheme(): ChartCanvas rebuilds this chart on every baseline change,
  // and that helper's MutationObserver is never disconnected.
  return new Chart(canvas, {
    type: 'line',
    data: {
      labels,
      datasets: bands.map((s, i) => {
        const color = colors[i % colors.length];
        const isLiability = s.type === 'liability';
        // Liabilities stack separately, so a $0 liability month sits on zero
        // rather than on top of the asset pile. Each band fills down to the band
        // beneath it; the first band of each stack fills to zero.
        const firstOfStack = i === 0 || (bands[i - 1].type === 'liability') !== isLiability;
        return {
          label: s.bucket,
          data: s.values,
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
            // One band is already net worth; a total under it would say it twice.
            footer: (items) =>
              items.length > 1 ? `Net worth: ${money(items.reduce((sum, item) => sum + item.parsed.y, 0))}` : '',
          },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: ink, maxRotation: 0, autoSkip: true, maxTicksLimit: 12 } },
        y: {
          stacked: true,
          beginAtZero: true, // an area's height is read from zero
          grid: { color: GRID },
          border: { display: false },
          ticks: { color: ink, callback: compactMoney },
        },
      },
    },
  });
}
