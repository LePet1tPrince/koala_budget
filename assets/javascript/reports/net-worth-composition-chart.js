'use strict';
/**
 * Net worth composition: a diverging stacked area. Every account group is a band
 * signed by what it does to net worth -- assets stack up from zero, debts stack
 * down from it -- and the net-worth line runs through the middle. The bands'
 * top edge is total assets, the bottom edge total debt, and at every month the
 * bands sum exactly to the line.
 *
 * A group can cross zero (an overdrawn account, a card in credit). Chart.js
 * stacks each value only onto earlier values of the same sign, but an area's
 * `fill: '-1'` fills to the previous dataset's line whatever its sign, so a
 * mixed-sign series would paint across the wrong bands. Each group is therefore
 * split into a positive part (in the 'up' stack) and a negative part (in the
 * 'down' stack); the part on the unexpected side is hatched, and the legend and
 * tooltip still treat the group as one series.
 *
 * Hue order is per side and was run through the dataviz palette validator in
 * both modes (adjacent bands, including the pair meeting at zero):
 *   light: #e34948 #4a3aa7 #e87ba4 | #2a78d6 #eb6834 #1baf7a #eda100 #008300
 *   dark:  #e66767 #9085e9 #d55181 | #3987e5 #d95926 #199e70 #c98500 #008300
 * (listed bottom → top). The server folds each side to fit: 5 asset bands, 3 debt bands.
 */
import Chart from 'chart.js/auto';
import { GRID, currency, getInk, getSurface, isDarkTheme, monthLabel } from './chart-theme';

// Nearest zero first.
const ASSET_HUES = {
  light: ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#008300'],
  dark: ['#3987e5', '#d95926', '#199e70', '#c98500', '#008300'],
};
const DEBT_HUES = {
  light: ['#e87ba4', '#4a3aa7', '#e34948'],
  dark: ['#d55181', '#9085e9', '#e66767'],
};

const signedCurrency = (value) => (value < 0 ? `−${currency(-value)}` : currency(value));
const axisCurrency = (value) =>
  value < 0 ? `−$${Math.abs(value).toLocaleString()}` : `$${Number(value).toLocaleString()}`;

function hatch(color) {
  const tile = document.createElement('canvas');
  tile.width = 8;
  tile.height = 8;
  const ctx = tile.getContext('2d');
  ctx.globalAlpha = 0.25;
  ctx.fillStyle = color;
  ctx.fillRect(0, 0, 8, 8);
  ctx.globalAlpha = 1;
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(-2, 2);
  ctx.lineTo(2, -2);
  ctx.moveTo(0, 8);
  ctx.lineTo(8, 0);
  ctx.moveTo(6, 10);
  ctx.lineTo(10, 6);
  ctx.stroke();
  return ctx.createPattern(tile, 'repeat');
}

function groupColor(group) {
  const mode = isDarkTheme() ? 'dark' : 'light';
  const hues = group.type === 'asset' ? ASSET_HUES[mode] : DEBT_HUES[mode];
  return hues[Math.min(group.slot, hues.length - 1)];
}

/**
 * One dataset per (group, sign) that has any value. Up-stack datasets come first
 * and down-stack ones after, each ordered nearest-zero first, so `fill: '-1'`
 * always points at the band directly beneath (or above) within the same stack.
 */
function buildDatasets(groups) {
  const up = [];
  const down = [];
  groups.forEach((group, groupIndex) => {
    const positive = group.values.map((v) => Math.max(v, 0));
    const negative = group.values.map((v) => Math.min(v, 0));
    const natural = group.type === 'asset' ? 'up' : 'down';
    if (positive.some((v) => v > 0)) {
      up.push({ groupIndex, data: positive, crossed: natural !== 'up' });
    }
    if (negative.some((v) => v < 0)) {
      down.push({ groupIndex, data: negative, crossed: natural !== 'down' });
    }
  });
  // Bands on their natural side sit next to zero; crossed ones stack beyond them.
  const bySide = (a, b) => Number(a.crossed) - Number(b.crossed);
  up.sort(bySide);
  down.sort(bySide);

  const primary = new Set();
  const toDataset = (part, stack, index) => {
    const group = groups[part.groupIndex];
    const isPrimary = !primary.has(part.groupIndex);
    primary.add(part.groupIndex);
    return {
      type: 'line',
      label: group.name,
      data: part.data,
      stack,
      fill: index === 0 ? 'origin' : '-1',
      groupIndex: part.groupIndex,
      crossed: part.crossed,
      primary: isPrimary,
      borderWidth: 1.5,
      pointRadius: 0,
      pointHoverRadius: 0,
      tension: 0,
      order: 1,
    };
  };
  return [...up.map((p, i) => toDataset(p, 'up', i)), ...down.map((p, i) => toDataset(p, 'down', i))];
}

// Every colour is set here, before the chart exists and again on a theme flip:
// a dataset left without one would be painted by Chart.js's own Colors plugin.
function applyColors(datasets, options, groups, canvas) {
  const ink = getInk(canvas);
  const surface = getSurface(canvas);
  datasets.forEach((dataset) => {
    if (dataset.isNetWorth) {
      dataset.borderColor = ink;
      dataset.backgroundColor = ink;
      dataset.pointBackgroundColor = ink;
      dataset.pointBorderColor = surface;
      dataset.pointHoverBackgroundColor = ink;
      dataset.pointHoverBorderColor = surface;
      return;
    }
    const color = groupColor(groups[dataset.groupIndex]);
    dataset.backgroundColor = dataset.crossed ? hatch(color) : color;
    // A surface-coloured edge is the 2px gap that keeps adjacent bands apart.
    dataset.borderColor = surface;
  });
  options.plugins.legend.labels.color = ink;
  options.scales.x.ticks.color = ink;
  options.scales.y.ticks.color = ink;
  options.scales.y.grid.color = (ctx) => (ctx.tick.value === 0 ? ink : GRID);
}

function render(canvas, data) {
  const groups = data.groups.map((group) => ({ ...group }));
  let assetSlot = 0;
  let debtSlot = 0;
  groups.forEach((group) => {
    group.slot = group.type === 'asset' ? assetSlot++ : debtSlot++;
  });

  const netWorth = {
    type: 'line',
    label: 'Net worth',
    data: data.net_worth,
    stack: 'net',
    fill: false,
    isNetWorth: true,
    borderWidth: 2,
    pointRadius: 3,
    pointBorderWidth: 2,
    pointHoverRadius: 5,
    tension: 0,
    order: 0,
  };
  const datasets = [...buildDatasets(groups), netWorth];

  const toggleGroup = (chart, groupIndex) => {
    const indices = chart.data.datasets
      .map((dataset, i) => (dataset.groupIndex === groupIndex ? i : -1))
      .filter((i) => i >= 0);
    const show = !indices.every((i) => chart.isDatasetVisible(i));
    indices.forEach((i) => chart.setDatasetVisibility(i, show));
    chart.update();
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: {
        labels: {
          usePointStyle: true,
          pointStyle: 'rectRounded',
          boxHeight: 8,
          // One entry per group (a group may be two datasets), then the line.
          generateLabels: (c) => {
            const items = groups.map((group, groupIndex) => {
              const indices = c.data.datasets
                .map((d, i) => (d.groupIndex === groupIndex ? i : -1))
                .filter((i) => i >= 0);
              const color = groupColor(group);
              return {
                text: group.name,
                fillStyle: color,
                strokeStyle: color,
                fontColor: c.options.plugins.legend.labels.color,
                hidden: indices.every((i) => !c.isDatasetVisible(i)),
                groupIndex,
              };
            });
            const lineIndex = c.data.datasets.findIndex((d) => d.isNetWorth);
            items.push({
              text: 'Net worth',
              fillStyle: c.data.datasets[lineIndex].borderColor,
              strokeStyle: c.data.datasets[lineIndex].borderColor,
              fontColor: c.options.plugins.legend.labels.color,
              pointStyle: 'line',
              lineWidth: 2,
              hidden: !c.isDatasetVisible(lineIndex),
              datasetIndex: lineIndex,
            });
            return items;
          },
        },
        onClick: (event, item, legend) => {
          const c = legend.chart;
          if (item.groupIndex !== undefined) {
            toggleGroup(c, item.groupIndex);
          } else {
            c.setDatasetVisibility(item.datasetIndex, !c.isDatasetVisible(item.datasetIndex));
            c.update();
          }
        },
      },
      tooltip: {
        // One line per group with its whole signed balance, whichever part is hovered.
        filter: (item) =>
          !item.dataset.isNetWorth &&
          item.dataset.primary &&
          groups[item.dataset.groupIndex].values[item.dataIndex] !== 0,
        itemSort: (a, b) => a.dataset.groupIndex - b.dataset.groupIndex,
        callbacks: {
          label: (item) => {
            const group = groups[item.dataset.groupIndex];
            return `${group.name}: ${signedCurrency(group.values[item.dataIndex])}`;
          },
          labelColor: (item) => {
            const color = groupColor(groups[item.dataset.groupIndex]);
            return { borderColor: color, backgroundColor: color };
          },
          footer: (items) => (items.length ? `Net worth: ${signedCurrency(data.net_worth[items[0].dataIndex])}` : ''),
        },
      },
    },
    scales: {
      x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true } },
      y: {
        stacked: true,
        border: { display: false },
        grid: {},
        ticks: { callback: axisCurrency },
      },
    },
  };
  applyColors(datasets, options, groups, canvas);
  const chart = new Chart(canvas, { data: { labels: data.labels.map(monthLabel), datasets }, options });

  new MutationObserver(() => {
    applyColors(chart.data.datasets, chart.options, groups, canvas);
    chart.update('none');
  }).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
}

document.addEventListener('DOMContentLoaded', () => {
  const dataEl = document.getElementById('net-worth-composition-data');
  const canvas = document.getElementById('net-worth-composition-chart');
  if (!dataEl || !canvas) return;
  const data = JSON.parse(dataEl.textContent);
  if (!data.groups || !data.groups.length) return;

  // The canvas may start in a hidden view, where Chart.js would size it 0×0:
  // build it the first time it is actually on screen.
  const observer = new IntersectionObserver((entries) => {
    if (entries.some((entry) => entry.isIntersecting)) {
      observer.disconnect();
      render(canvas, data);
    }
  });
  observer.observe(canvas);
});
