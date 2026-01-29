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
  const netProfit = data.net_profit || 0;

  const flows = [];

  // Income accounts -> "Income"
  income.forEach(item => {
    if (item.amount > 0) {
      flows.push({from: item.name, to: 'Income', flow: item.amount});
    }
  });

  // "Income" -> Expense accounts
  expenses.forEach(item => {
    if (item.amount > 0) {
      flows.push({from: 'Income', to: item.name, flow: item.amount});
    }
  });

  // Handle net profit / deficit
  if (netProfit > 0) {
    flows.push({from: 'Income', to: 'Savings', flow: netProfit});
  } else if (netProfit < 0) {
    flows.push({from: 'Deficit', to: 'Income', flow: Math.abs(netProfit)});
  }

  if (flows.length === 0) return;

  // Build color map
  const colorMap = {};
  const incomeColor = 'rgba(34, 197, 94, 0.6)';   // green
  const expenseColor = 'rgba(239, 68, 68, 0.6)';   // red
  const savingsColor = 'rgba(59, 130, 246, 0.6)';   // blue
  const deficitColor = 'rgba(251, 146, 60, 0.6)';   // orange
  const hubColor = 'rgba(107, 114, 128, 0.6)';      // gray

  colorMap['Income'] = hubColor;
  colorMap['Savings'] = savingsColor;
  colorMap['Deficit'] = deficitColor;
  income.forEach(item => { colorMap[item.name] = incomeColor; });
  expenses.forEach(item => { colorMap[item.name] = expenseColor; });

  const getColor = (key) => colorMap[key] || hubColor;

  const canvas = document.getElementById('sankey-chart');
  if (!canvas) return;

  new Chart(canvas, {
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
              return `${item.from} → ${item.to}: ${item.flow.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
            }
          }
        }
      }
    }
  });
});
