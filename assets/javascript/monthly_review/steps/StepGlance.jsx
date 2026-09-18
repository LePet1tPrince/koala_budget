import React from 'react';

import InsightList from '../parts/InsightList';
import StatCard from '../parts/StatCard';

/** Step 2: the month at a glance -- four cards, vs-baseline deltas. */
const StepGlance = ({ review, baseline }) => {
  const { current } = review;
  return (
    <div>
      {baseline && (
        <p className="text-sm text-base-content/70 mb-4">
          Every baseline is the period before {review.month_label}, never including it.
        </p>
      )}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
        <StatCard
          label="Money in"
          value={current.income}
          delta={baseline ? current.income - baseline.avgs.income : null}
          testId="stat-income"
        />
        <StatCard
          label="Money out"
          value={current.spend}
          delta={baseline ? current.spend - baseline.avgs.spend : null}
          goodIsUp={false}
          testId="stat-spend"
        />
        <StatCard
          label="Saved"
          value={current.saved}
          delta={baseline ? current.saved - baseline.avgs.saved : null}
          testId="stat-saved"
        />
        <StatCard
          label="Left over"
          value={current.net}
          delta={baseline ? current.net - baseline.avgs.net : null}
          testId="stat-net"
        />
      </div>
      <InsightList insights={review.insights} step={2} />
    </div>
  );
};

export default StepGlance;
