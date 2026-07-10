'use strict';
import Chart from 'chart.js/auto';
import {GRID, MONEY, currency, compactCurrency, getInk, getSurface, observeTheme} from './chart-theme';

document.addEventListener('DOMContentLoaded', () => {
  const dataEl = document.getElementById('cash-flow-data');
  const canvas = document.getElementById('cash-flow-chart');
  if (!dataEl || !canvas) return;

  const data = JSON.parse(dataEl.textContent);
  if (!data.labels || data.labels.length === 0) return;

  const ink = getInk(canvas);
  const surface = getSurface(canvas);

  const chart = new Chart(canvas, {
    data: {
      labels: data.labels,
      datasets: [
        {
          type: 'line',
          label: 'Net',
          data: data.net,
          borderColor: MONEY.net,
          backgroundColor: MONEY.net,
          pointBackgroundColor: MONEY.net,
          borderWidth: 2,
          pointRadius: 3,
          pointBorderWidth: 2,
          pointBorderColor: surface,
          pointHoverRadius: 5,
          tension: 0.3,
          order: 0,
        },
        {
          type: 'bar',
          label: 'Money In',
          data: data.income,
          backgroundColor: MONEY.in,
          borderRadius: {topLeft: 4, topRight: 4},
          maxBarThickness: 24,
          order: 1,
        },
        {
          type: 'bar',
          label: 'Money Out',
          data: data.expenses,
          backgroundColor: MONEY.out,
          borderRadius: {topLeft: 4, topRight: 4},
          maxBarThickness: 24,
          order: 1,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {mode: 'index', intersect: false},
      plugins: {
        legend: {
          labels: {color: ink, usePointStyle: true, pointStyle: 'circle', boxHeight: 8},
        },
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.dataset.label}: ${currency(ctx.parsed.y)}`,
          },
        },
      },
      scales: {
        x: {
          grid: {display: false},
          ticks: {color: ink, maxRotation: 0, autoSkip: true},
        },
        y: {
          grid: {color: GRID},
          border: {display: false},
          ticks: {color: ink, callback: compactCurrency},
        },
      },
    },
  });

  observeTheme(chart, (c) => {
    const newInk = getInk(canvas);
    const newSurface = getSurface(canvas);
    c.options.plugins.legend.labels.color = newInk;
    c.options.scales.x.ticks.color = newInk;
    c.options.scales.y.ticks.color = newInk;
    c.data.datasets[0].pointBorderColor = newSurface;
  });
});
