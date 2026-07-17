'use strict';
import Chart from 'chart.js/auto';

document.addEventListener('DOMContentLoaded', () => {
  const dataEl = document.getElementById('net-worth-data');
  const canvas = document.getElementById('net-worth-chart');
  if (!dataEl || !canvas) return;

  const data = JSON.parse(dataEl.textContent);
  if (!data.labels || data.labels.length === 0) return;

  // Labels arrive as ISO month-end dates; parse the parts directly so a
  // timezone offset can't shift the month.
  const labels = data.labels.map((iso) => {
    const [year, month] = iso.split('-').map(Number);
    return new Date(year, month - 1, 1).toLocaleDateString(undefined, {month: 'short', year: 'numeric'});
  });

  // Palette validated (light + dark) for CVD separation and surface contrast:
  // net worth blue, assets green, liabilities red.
  const netWorthColor = 'rgb(59, 130, 246)';
  const assetsColor = 'rgb(22, 163, 74)';
  const liabilitiesColor = 'rgb(239, 68, 68)';

  // Ink and surface from the theme so the chart works in light and dark mode.
  const getInk = () => getComputedStyle(canvas).color;
  const getSurface = () => getComputedStyle(canvas.closest('.card') || document.body).backgroundColor;
  const ink = getInk();
  const surface = getSurface();
  const grid = 'rgba(128, 128, 128, 0.15)';

  const currency = (value) =>
    `$${value.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;

  const chart = new Chart(canvas, {
    type: 'bar',
    data: {
      labels,
      datasets: [
        {
          type: 'line',
          label: 'Net Worth',
          data: data.net_worth,
          borderColor: netWorthColor,
          backgroundColor: netWorthColor,
          borderWidth: 2,
          pointRadius: 3,
          pointBorderWidth: 2,
          pointBorderColor: surface,
          pointBackgroundColor: netWorthColor,
          pointHoverRadius: 5,
          tension: 0,
          fill: false,
          order: 0,
        },
        {
          type: 'bar',
          label: 'Assets',
          data: data.assets,
          backgroundColor: assetsColor,
          borderRadius: 4,
          order: 1,
        },
        {
          type: 'bar',
          label: 'Liabilities',
          data: data.liabilities,
          backgroundColor: liabilitiesColor,
          borderRadius: 4,
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
          beginAtZero: true,
          grid: {color: grid},
          border: {display: false},
          ticks: {color: ink, callback: (value) => `$${value.toLocaleString()}`},
        },
      },
    },
  });

  // Re-resolve theme colors when the user flips light/dark mode without a reload.
  const themeObserver = new MutationObserver(() => {
    const newInk = getInk();
    const newSurface = getSurface();
    chart.options.plugins.legend.labels.color = newInk;
    chart.options.scales.x.ticks.color = newInk;
    chart.options.scales.y.ticks.color = newInk;
    chart.data.datasets.forEach((dataset) => {
      if (dataset.type === 'line') {
        dataset.pointBorderColor = newSurface;
      }
    });
    chart.update('none');
  });
  themeObserver.observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme']});
});
