'use strict';
import Chart from 'chart.js/auto';
import {GRID, MONEY, currency, getInk, getSurface, observeTheme} from './chart-theme';

document.addEventListener('DOMContentLoaded', () => {
  const dataEl = document.getElementById('account-budget-data');
  const canvas = document.getElementById('account-budget-chart');
  if (!dataEl || !canvas) return;

  const data = JSON.parse(dataEl.textContent);
  if (!data.labels || data.labels.length === 0) return;

  // Actual earns green for income, spends red for expenses; Budgeted stays a
  // recessive neutral (it's the plan); the Available rollover line is blue.
  const actualColor = data.account_type === 'income' ? MONEY.in : MONEY.out;
  const budgetColor = 'rgba(128, 128, 128, 0.45)';

  const ink = getInk(canvas);
  const surface = getSurface(canvas);

  const chart = new Chart(canvas, {
    data: {
      labels: data.labels,
      datasets: [
        {
          // Dataset 0 draws top-most, so the line rides over the bars.
          type: 'line',
          label: 'Available',
          data: data.available,
          borderColor: MONEY.net,
          backgroundColor: MONEY.net,
          pointBackgroundColor: MONEY.net,
          pointBorderColor: surface,
          pointBorderWidth: 2,
          pointRadius: 3,
          pointHoverRadius: 5,
          borderWidth: 2,
          tension: 0.3,
        },
        {
          type: 'bar',
          label: 'Budgeted',
          data: data.budgeted,
          backgroundColor: budgetColor,
          borderRadius: 4,
        },
        {
          type: 'bar',
          label: 'Actual',
          data: data.actual,
          backgroundColor: actualColor,
          borderRadius: 4,
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
          ticks: {color: ink, maxRotation: 0, autoSkip: true, maxTicksLimit: 12},
        },
        y: {
          grid: {color: GRID},
          border: {display: false},
          ticks: {
            color: ink,
            callback: (value) => `$${value.toLocaleString()}`,
          },
        },
      },
    },
  });

  observeTheme(chart, (themedChart) => {
    const newInk = getInk(canvas);
    const newSurface = getSurface(canvas);
    themedChart.options.plugins.legend.labels.color = newInk;
    themedChart.options.scales.x.ticks.color = newInk;
    themedChart.options.scales.y.ticks.color = newInk;
    themedChart.data.datasets[0].pointBorderColor = newSurface;
  });
});
