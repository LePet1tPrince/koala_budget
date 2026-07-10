'use strict';
import Chart from 'chart.js/auto';
import {GRID, currency, compactCurrency, getInk, getSurface, monthLabel, observeTheme, seriesColors} from './chart-theme';

document.addEventListener('DOMContentLoaded', () => {
  const dataEl = document.getElementById('composition-data');
  if (!dataEl) return;
  const data = JSON.parse(dataEl.textContent);
  if (!data.labels || data.labels.length === 0) return;

  const labels = data.labels.map(monthLabel);

  const buildChart = (canvasId, groups) => {
    const canvas = document.getElementById(canvasId);
    if (!canvas || !groups.length) return;

    const colors = seriesColors(groups.length);
    const ink = getInk(canvas);
    const surface = getSurface(canvas);

    const chart = new Chart(canvas, {
      type: 'line',
      data: {
        labels,
        datasets: groups.map((group, i) => ({
          label: group.name,
          data: group.values,
          borderColor: colors[i],
          backgroundColor: `${colors[i]}4d`, // ~30% alpha wash between stack bands
          pointBackgroundColor: colors[i],
          fill: true,
          borderWidth: 2,
          pointRadius: 2,
          pointBorderWidth: 2,
          pointBorderColor: surface,
          pointHoverRadius: 5,
          tension: 0.3,
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
            grid: {display: false},
            ticks: {color: ink, maxRotation: 0, autoSkip: true, maxTicksLimit: 12},
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
        dataset.borderColor = newColors[i];
        dataset.backgroundColor = `${newColors[i]}4d`;
        dataset.pointBackgroundColor = newColors[i];
        dataset.pointBorderColor = newSurface;
      });
    });
  };

  buildChart('assets-composition-chart', data.asset_groups);
  buildChart('liabilities-composition-chart', data.liability_groups);
});
