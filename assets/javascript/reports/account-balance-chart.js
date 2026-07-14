'use strict';
import Chart from 'chart.js/auto';
import {GRID, MONEY, currency, getInk, getSurface, observeTheme} from './chart-theme';

document.addEventListener('DOMContentLoaded', () => {
  const dataEl = document.getElementById('account-balance-data');
  const canvas = document.getElementById('account-balance-chart');
  if (!dataEl || !canvas) return;

  const data = JSON.parse(dataEl.textContent);

  // Parse ISO dates as UTC parts so a timezone offset can't shift the day.
  const parseDay = (iso) => {
    const [year, month, day] = iso.split('-').map(Number);
    return Date.UTC(year, month - 1, day);
  };
  const MS_PER_DAY = 24 * 60 * 60 * 1000;
  const startMs = parseDay(data.start_date);
  const dayOffset = (iso) => (parseDay(iso) - startMs) / MS_PER_DAY;
  const dayLabel = (offset) =>
    new Date(startMs + offset * MS_PER_DAY).toLocaleDateString(undefined, {
      timeZone: 'UTC',
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });

  // A balance is a step function: it holds until the next transaction. Anchor
  // the line at the period's start (starting balance) and end (ending balance).
  const points = data.points.map((point) => ({x: dayOffset(point.date), y: point.balance}));
  if (points.length === 0 || points[0].x > 0) {
    points.unshift({x: 0, y: data.starting_balance});
  }
  const endOffset = dayOffset(data.end_date);
  if (points[points.length - 1].x < endOffset) {
    points.push({x: endOffset, y: data.ending_balance});
  }

  const ink = getInk(canvas);
  const surface = getSurface(canvas);

  const chart = new Chart(canvas, {
    type: 'line',
    data: {
      datasets: [
        {
          label: 'Balance',
          data: points,
          borderColor: MONEY.net,
          backgroundColor: MONEY.netFill,
          pointBackgroundColor: MONEY.net,
          borderWidth: 2,
          pointRadius: points.length > 60 ? 0 : 3,
          pointBorderWidth: 2,
          pointBorderColor: surface,
          pointHoverRadius: 5,
          stepped: 'after',
          fill: true,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {mode: 'nearest', axis: 'x', intersect: false},
      plugins: {
        // Single series — the panel title names it, no legend box needed.
        legend: {display: false},
        tooltip: {
          callbacks: {
            title: (items) => dayLabel(items[0].parsed.x),
            label: (ctx) => `Balance: ${currency(ctx.parsed.y)}`,
          },
        },
      },
      scales: {
        x: {
          type: 'linear',
          min: 0,
          max: endOffset,
          grid: {display: false},
          ticks: {
            color: ink,
            maxRotation: 0,
            autoSkip: true,
            maxTicksLimit: 8,
            callback: (value) => dayLabel(value),
          },
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
    themedChart.options.scales.x.ticks.color = newInk;
    themedChart.options.scales.y.ticks.color = newInk;
    themedChart.data.datasets[0].pointBorderColor = newSurface;
  });
});
