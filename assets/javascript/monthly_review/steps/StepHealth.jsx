import React from 'react';

import InsightList from '../parts/InsightList';

/** Step 1: the trust gate. Never blocks -- it only warns before showing figures. */
const StepHealth = ({ review }) => (
  <div>
    <p className="text-base-content/70 mb-4">
      Before looking at numbers, let&apos;s make sure this month&apos;s data is trustworthy.
    </p>
    <InsightList insights={review.insights} step={1} testId="step-health-insights" />
  </div>
);

export default StepHealth;
