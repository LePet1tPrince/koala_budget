import { drawDollarMap } from './dollar-map-chart';
import { bookParams, getReportsApi, loadChart, onReady } from './report-data';

/** The Budget & Goals waterfall, from `GET …/reports/api/budget-and-goals/?month=` (the canvas's `data-month`). */
onReady(() => {
  const canvas = document.getElementById('dollar-map-chart');
  if (!canvas) return;
  loadChart(
    canvas,
    () => getReportsApi().reportsBudgetGoalsRetrieve({ ...bookParams(), month: canvas.dataset.month }),
    (report) =>
      drawDollarMap(
        canvas,
        report.waterfall.map((step) => ({
          key: step.key,
          label: step.label,
          value: Number(step.value),
          start: Number(step.start),
          end: Number(step.end),
          total: step.total,
        })),
      ),
  );
});
