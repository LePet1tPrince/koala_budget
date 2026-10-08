'use strict';
/**
 * Dollar Map waterfall: net worth stepping down to Unassigned, one floating bar
 * per term of the sum (apps/budget/unassigned.py::waterfall). The two totals
 * stand on zero; every step floats from where the previous one ended.
 */
import Chart from 'chart.js/auto';
import {GRID, MONEY, compactCurrency, currency, getInk, isDarkTheme, observeTheme} from './chart-theme';

// Fixed colours per term, matching the allocation bar above the chart: goals
// ochre (the theme accent), envelopes blue, net worth neutral.
const PALETTE = {
  light: {net_worth: '#8b938c', envelopes: '#2a78d6', goals: '#c98500'},
  dark: {net_worth: '#7c867e', envelopes: '#3987e5', goals: '#c98500'},
};

function colorFor(bar) {
  const p = isDarkTheme() ? PALETTE.dark : PALETTE.light;
  switch (bar.key) {
    case 'net_worth':
      return p.net_worth;
    case 'income_due':
      return 'rgba(22, 163, 74, 0.45)';
    case 'envelopes':
      return p.envelopes;
    case 'goals':
      return p.goals;
    case 'goals_held':
      // Planned for a linked goal and not yet moved: the goals colour, lighter.
      return `${p.goals}99`;
    case 'unassigned':
      return bar.value < 0 ? MONEY.out : MONEY.in;
    default:
      return p.net_worth;
  }
}

// Chart.js draws an array label as stacked lines; the step names are long.
function wrap(label, width = 14) {
  const lines = [];
  label.split(' ').forEach((word) => {
    const last = lines[lines.length - 1];
    if (last && `${last} ${word}`.length <= width) lines[lines.length - 1] = `${last} ${word}`;
    else lines.push(word);
  });
  return lines;
}

document.addEventListener('DOMContentLoaded', () => {
  const dataEl = document.getElementById('dollar-map-data');
  const canvas = document.getElementById('dollar-map-chart');
  if (!dataEl || !canvas) return;

  const bars = JSON.parse(dataEl.textContent);
  if (!bars.length) return;
  const ink = getInk(canvas);

  const chart = new Chart(canvas, {
    type: 'bar',
    data: {
      labels: bars.map((b) => wrap(b.label)),
      datasets: [
        {
          label: 'Amount',
          data: bars.map((b) => [b.start, b.end]),
          backgroundColor: bars.map(colorFor),
          borderColor: bars.map((b) => (b.key === 'income_due' ? MONEY.in : 'transparent')),
          borderWidth: bars.map((b) => (b.key === 'income_due' ? 1.5 : 0)),
          borderDash: [4, 3],
          borderRadius: 3,
          borderSkipped: false,
          maxBarThickness: 72,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {display: false},
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const bar = bars[ctx.dataIndex];
              const sign = !bar.total && bar.value > 0 ? '+' : '';
              return `${sign}${currency(bar.value)}`;
            },
          },
        },
      },
      scales: {
        x: {
          grid: {display: false},
          ticks: {color: ink, maxRotation: 0, autoSkip: false, font: {size: 11}},
        },
        y: {
          beginAtZero: true,
          grid: {color: GRID},
          border: {display: false},
          ticks: {color: ink, callback: compactCurrency},
        },
      },
    },
  });

  observeTheme(chart, (c) => {
    const newInk = getInk(canvas);
    c.options.scales.x.ticks.color = newInk;
    c.options.scales.y.ticks.color = newInk;
    c.data.datasets[0].backgroundColor = bars.map(colorFor);
  });
});
