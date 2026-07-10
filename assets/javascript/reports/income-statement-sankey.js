'use strict';
import Chart from 'chart.js/auto';
import {SankeyController, Flow} from 'chartjs-chart-sankey';

Chart.register(SankeyController, Flow);

document.addEventListener('DOMContentLoaded', () => {
  const dataEl = document.getElementById('sankey-data');
  if (!dataEl) return;

  const data = JSON.parse(dataEl.textContent);
  const income = data.income || [];
  const expenses = data.expenses || [];
  const incomeGroups = data.income_groups || [];
  const expenseGroups = data.expense_groups || [];
  const netProfit = data.net_profit || 0;

  const flows = [];

  // Five layers: income accounts -> their account group -> "Income" -> their
  // account group -> expense accounts. An account or group with a negative net
  // for the period (e.g. refunds/chargebacks exceeding income/spending) flows
  // the other way instead of being dropped, so everything is represented and
  // the diagram stays flow-conservative with the Total Income/Expenses figures
  // above it.
  income.forEach(item => {
    if (item.amount > 0) {
      flows.push({from: item.name, to: item.group, flow: item.amount});
    } else if (item.amount < 0) {
      flows.push({from: item.group, to: item.name, flow: Math.abs(item.amount)});
    }
  });

  incomeGroups.forEach(group => {
    if (group.amount > 0) {
      flows.push({from: group.name, to: 'Income', flow: group.amount});
    } else if (group.amount < 0) {
      flows.push({from: 'Income', to: group.name, flow: Math.abs(group.amount)});
    }
  });

  expenseGroups.forEach(group => {
    if (group.amount > 0) {
      flows.push({from: 'Income', to: group.name, flow: group.amount});
    } else if (group.amount < 0) {
      flows.push({from: group.name, to: 'Income', flow: Math.abs(group.amount)});
    }
  });

  expenses.forEach(item => {
    if (item.amount > 0) {
      flows.push({from: item.group, to: item.name, flow: item.amount});
    } else if (item.amount < 0) {
      flows.push({from: item.name, to: item.group, flow: Math.abs(item.amount)});
    }
  });

  // Handle net profit / deficit
  if (netProfit > 0) {
    flows.push({from: 'Income', to: 'Savings', flow: netProfit});
  } else if (netProfit < 0) {
    flows.push({from: 'Deficit', to: 'Income', flow: Math.abs(netProfit)});
  }

  if (flows.length === 0) return;

  // Build color map. Groups get a darker shade of their side's color so the
  // account -> group -> hub -> group -> account hierarchy reads at a glance.
  const colorMap = {};
  const incomeColor = 'rgba(34, 197, 94, 0.6)';        // green
  const incomeGroupColor = 'rgba(21, 128, 61, 0.7)';   // dark green
  const expenseColor = 'rgba(239, 68, 68, 0.6)';       // red
  const expenseGroupColor = 'rgba(185, 28, 28, 0.7)';  // dark red
  const savingsColor = 'rgba(59, 130, 246, 0.6)';      // blue
  const deficitColor = 'rgba(251, 146, 60, 0.6)';      // orange
  const hubColor = 'rgba(107, 114, 128, 0.6)';         // gray

  colorMap['Income'] = hubColor;
  colorMap['Savings'] = savingsColor;
  colorMap['Deficit'] = deficitColor;
  income.forEach(item => { colorMap[item.name] = incomeColor; });
  incomeGroups.forEach(group => { colorMap[group.name] = incomeGroupColor; });
  expenseGroups.forEach(group => { colorMap[group.name] = expenseGroupColor; });
  expenses.forEach(item => { colorMap[item.name] = expenseColor; });

  const getColor = (key) => colorMap[key] || hubColor;

  const canvas = document.getElementById('sankey-chart');
  if (!canvas) return;

  const createChart = () => new Chart(canvas, {
    type: 'sankey',
    data: {
      datasets: [{
        label: 'Income Statement',
        data: flows,
        colorFrom: (c) => getColor(c.dataset.data[c.dataIndex].from),
        colorTo: (c) => getColor(c.dataset.data[c.dataIndex].to),
        colorMode: 'gradient',
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {display: false},
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const item = ctx.dataset.data[ctx.dataIndex];
              return `${item.from} → ${item.to}: $${item.flow.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
            }
          }
        }
      }
    }
  });

  // The canvas starts inside a hidden tab (display:none), where Chart.js would
  // size itself to 0x0 — defer creation until the canvas is first shown.
  const observer = new IntersectionObserver((entries) => {
    if (entries.some((entry) => entry.isIntersecting)) {
      observer.disconnect();
      createChart();
    }
  });
  observer.observe(canvas);
});
