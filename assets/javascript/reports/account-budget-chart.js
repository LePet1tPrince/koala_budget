'use strict';
import Chart from 'chart.js/auto';
import {GRID, MONEY, currency, getInk, getSurface, observeTheme} from './chart-theme';

document.addEventListener('DOMContentLoaded', () => {
  const dataEl = document.getElementById('account-budget-data');
  const canvas = document.getElementById('account-budget-chart');
  if (!dataEl || !canvas) return;

  const data = JSON.parse(dataEl.textContent);
  if (!data.labels || data.labels.length === 0) return;

  // Green for income, red for expenses; the Available rollover line is blue.
  // Budgeted and Actual fully overlap (grouped: false) so each month reads as
  // a progress bar: the Budgeted outline is the container, the solid Actual
  // fill shows how much of it is used. The outline is a darker step of the
  // same hue so it stays visible where an over-budget fill overflows it.
  const income = data.account_type === 'income';
  const seriesColor = income ? MONEY.in : MONEY.out;
  const outlineColor = income ? 'rgb(15, 118, 66)' : 'rgb(185, 28, 28)';

  const ink = getInk(canvas);
  const surface = getSurface(canvas);
  const barLayout = {grouped: false, barPercentage: 0.6, categoryPercentage: 0.8};

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
          // Outline only — drawn over the Actual fill so the budget container
          // stays visible whether the fill is inside it or overflows it.
          type: 'bar',
          label: 'Budgeted',
          data: data.budgeted,
          backgroundColor: 'transparent',
          borderColor: outlineColor,
          borderWidth: 2,
          borderSkipped: false,
          borderRadius: 4,
          ...barLayout,
        },
        {
          type: 'bar',
          label: 'Actual',
          data: data.actual,
          backgroundColor: seriesColor,
          borderWidth: 0,
          borderRadius: 4,
          ...barLayout,
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
