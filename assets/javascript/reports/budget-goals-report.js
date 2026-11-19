import { BudgetGoalsReportFromJSON } from 'api-client';

import { drawDollarMap } from './dollar-map-chart';
import { onReady, pageData } from './report-data';

/** The Budget & Goals waterfall, from the `GET …/reports/api/budget-and-goals/` body the page embeds. */
onReady(() => {
  const canvas = document.getElementById('dollar-map-chart');
  const report = pageData('budget-goals-report-data', BudgetGoalsReportFromJSON);
  if (!canvas || !report) return;
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
  );
});
