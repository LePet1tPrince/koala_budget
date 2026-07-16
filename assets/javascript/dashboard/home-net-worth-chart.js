'use strict';
import Chart from 'chart.js/auto';
import {MONEY, GRID, getInk, getSurface, currency, monthLabel, observeTheme} from '../reports/chart-theme';

document.addEventListener('DOMContentLoaded', () => {
  const dataEl = document.getElementById('home-net-worth-data');
  const canvas = document.getElementById('home-net-worth-chart');
  if (!dataEl || !canvas) return;

  const data = JSON.parse(dataEl.textContent);
  if (!data.labels || data.labels.length === 0) return;

  const labels = data.labels.map(monthLabel);
  const ink = getInk(canvas);
  const surface = getSurface(canvas);

  const chart = new Chart(canvas, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'Net Worth',
          data: data.net_worth,
          borderColor: MONEY.net,
          backgroundColor: MONEY.netFill,
          borderWidth: 2,
          pointRadius: 3,
          pointBorderWidth: 2,
          pointBorderColor: surface,
          pointBackgroundColor: MONEY.net,
          pointHoverRadius: 5,
          tension: 0.3,
          fill: true,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {mode: 'index', intersect: false},
      plugins: {
        legend: {display: false},
        tooltip: {
          callbacks: {
            label: (ctx) => currency(ctx.parsed.y),
          },
        },
      },
      scales: {
        x: {
          grid: {display: false},
          ticks: {color: ink, maxRotation: 0, autoSkip: true},
        },
        y: {
          beginAtZero: true,
          grid: {color: GRID},
          border: {display: false},
          ticks: {color: ink, callback: (value) => `$${value.toLocaleString()}`},
        },
      },
    },
  });

  observeTheme(chart, (c) => {
    const newInk = getInk(canvas);
    const newSurface = getSurface(canvas);
    c.options.scales.x.ticks.color = newInk;
    c.options.scales.y.ticks.color = newInk;
    c.data.datasets.forEach((dataset) => {
      dataset.pointBorderColor = newSurface;
    });
  });
});
