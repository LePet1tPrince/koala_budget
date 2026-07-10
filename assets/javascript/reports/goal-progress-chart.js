'use strict';
import Chart from 'chart.js/auto';
import {GRID, currency, compactCurrency, getInk, getSurface, monthLabel, observeTheme, seriesColors} from './chart-theme';

document.addEventListener('DOMContentLoaded', () => {
  const dataEl = document.getElementById('goal-progress-data');
  const canvas = document.getElementById('goal-progress-chart');
  if (!dataEl || !canvas) return;

  const data = JSON.parse(dataEl.textContent);
  if (!data.labels || data.labels.length === 0 || !data.goals.length) return;

  const labels = data.labels.map(monthLabel);
  const colors = seriesColors(data.goals.length);
  const ink = getInk(canvas);
  const surface = getSurface(canvas);

  const datasets = [];
  data.goals.forEach((goal, i) => {
    datasets.push({
      label: goal.name,
      data: goal.actual,
      borderColor: colors[i],
      backgroundColor: colors[i],
      pointBackgroundColor: colors[i],
      borderWidth: 2,
      pointRadius: 2,
      pointBorderWidth: 2,
      pointBorderColor: surface,
      pointHoverRadius: 5,
      tension: 0.3,
      spanGaps: false,
      goalIndex: i,
    });
    if (goal.projection.some((v) => v !== null)) {
      datasets.push({
        label: `${goal.name} (projected)`,
        data: goal.projection,
        borderColor: colors[i],
        backgroundColor: colors[i],
        borderWidth: 2,
        borderDash: [5, 4],
        pointRadius: 0,
        pointHoverRadius: 4,
        pointBackgroundColor: colors[i],
        tension: 0,
        spanGaps: true,
        goalIndex: i,
        isProjection: true,
      });
    }
  });

  const chart = new Chart(canvas, {
    type: 'line',
    data: {labels, datasets},
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {mode: 'nearest', intersect: false},
      plugins: {
        legend: {
          labels: {
            color: ink,
            usePointStyle: true,
            pointStyle: 'circle',
            boxHeight: 8,
            // One legend entry per goal — projections share the goal's hue
            filter: (item, chartData) => !chartData.datasets[item.datasetIndex].isProjection,
          },
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
    const newSurface = getSurface(canvas);
    const newColors = seriesColors(data.goals.length);
    c.options.plugins.legend.labels.color = newInk;
    c.options.scales.x.ticks.color = newInk;
    c.options.scales.y.ticks.color = newInk;
    c.data.datasets.forEach((dataset) => {
      const color = newColors[dataset.goalIndex];
      dataset.borderColor = color;
      dataset.backgroundColor = color;
      dataset.pointBackgroundColor = color;
      if (!dataset.isProjection) dataset.pointBorderColor = newSurface;
    });
  });
});
