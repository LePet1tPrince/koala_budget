'use strict';
import Chart from 'chart.js/auto';
import {GRID, currency, compactCurrency, getInk, getSurface, observeTheme, seriesColors} from './chart-theme';

document.addEventListener('DOMContentLoaded', () => {
  const dataEl = document.getElementById('trend-chart-data');
  const canvas = document.getElementById('expense-trend-chart');
  if (!dataEl || !canvas) return;

  const data = JSON.parse(dataEl.textContent);
  if (!data.labels || data.labels.length === 0 || !data.expense_groups.length) return;

  const colors = seriesColors(data.expense_groups.length);
  const ink = getInk(canvas);
  const surface = getSurface(canvas);

  const chart = new Chart(canvas, {
    type: 'bar',
    data: {
      labels: data.labels,
      datasets: data.expense_groups.map((group, i) => ({
        label: group.name,
        data: group.values,
        backgroundColor: colors[i],
        // 2px surface-colored border = the gap between stacked segments
        borderColor: surface,
        borderWidth: 2,
        maxBarThickness: 32,
      })),
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
            footer: (items) => `Total: ${currency(items.reduce((sum, item) => sum + item.parsed.y, 0))}`,
          },
        },
      },
      scales: {
        x: {
          stacked: true,
          grid: {display: false},
          ticks: {color: ink, maxRotation: 0, autoSkip: true},
        },
        y: {
          stacked: true,
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
    const newColors = seriesColors(c.data.datasets.length);
    c.options.plugins.legend.labels.color = newInk;
    c.options.scales.x.ticks.color = newInk;
    c.options.scales.y.ticks.color = newInk;
    c.data.datasets.forEach((dataset, i) => {
      dataset.backgroundColor = newColors[i];
      dataset.borderColor = newSurface;
    });
  });
});
