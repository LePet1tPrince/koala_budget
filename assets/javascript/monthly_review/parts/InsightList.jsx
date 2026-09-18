import React from 'react';

import FlagCard from './FlagCard';

/** The insights the server generated for one step, already interpolated copy. */
const InsightList = ({ insights, step, testId }) => {
  const rows = (insights || []).filter((i) => i.step === step);
  if (!rows.length) return null;
  return (
    <div className="space-y-3" data-testid={testId || `insights-step-${step}`}>
      {rows.map((insight, idx) => (
        <FlagCard key={`${insight.kind}-${idx}`} insight={insight} />
      ))}
    </div>
  );
};

export default InsightList;
