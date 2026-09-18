import React from 'react';

import DrillTable from '../parts/DrillTable';
import InsightList from '../parts/InsightList';

/** Step 6: the whole breakdown -- every category that moved, click to unfold. */
const StepBreakdown = ({ review, baseline }) => (
  <div>
    <DrillTable
      groups={review.budget.groups}
      catTxns={review.cat_txns}
      catAvg={baseline ? baseline.cat_avg : null}
      baselineLabel={baseline ? baseline.short : ''}
    />
    <div className="mt-4">
      <InsightList insights={review.insights} step={6} />
    </div>
  </div>
);

export default StepBreakdown;
