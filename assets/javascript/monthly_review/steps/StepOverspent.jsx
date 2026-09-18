import React from 'react';

import { currency } from '../format';
import InsightList from '../parts/InsightList';

const Card = ({ row, tone }) => (
  <div
    className={`rounded-box border p-4 ${tone === 'bad' ? 'border-error/40 bg-error/5' : 'border-warning/40 bg-warning/5'}`}
  >
    <div className="font-medium">{row.category.name}</div>
    <div className="text-xs text-base-content/60">{row.group.name}</div>
    <div className="text-sm mt-2">
      Spent {currency(row.spent)} against {currency(row.assigned)} assigned
    </div>
    <div className={`text-sm font-semibold mt-1 ${tone === 'bad' ? 'text-error' : 'text-warning'}`}>
      {tone === 'bad' ? 'Over by' : 'Covered, over by'} {currency(row.over)}
    </div>
    <div className="text-xs text-base-content/60 mt-1">Ending available: {currency(row.available)}</div>
  </div>
);

/** Step 4: what blew through the budget -- overspent (red) then over-assigned (amber). */
const StepOverspent = ({ review }) => {
  const { overspent, over_assigned: overAssigned } = review.budget;

  if (!overspent.length && !overAssigned.length) {
    return (
      <div className="alert alert-success" data-testid="budget-all-clear">
        Every category stayed inside its budget.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {overspent.length > 0 && (
        <div>
          <h2 className="font-semibold mb-2">Overspent</h2>
          <div className="grid md:grid-cols-2 gap-3" data-testid="overspent-cards">
            {overspent.map((row, i) => (
              <Card key={i} row={row} tone="bad" />
            ))}
          </div>
        </div>
      )}
      {overAssigned.length > 0 && (
        <div>
          <h2 className="font-semibold mb-2">Over the assignment</h2>
          <div className="grid md:grid-cols-2 gap-3" data-testid="over-assigned-cards">
            {overAssigned.map((row, i) => (
              <Card key={i} row={row} tone="warn" />
            ))}
          </div>
        </div>
      )}
      <InsightList insights={review.insights} step={4} />
    </div>
  );
};

export default StepOverspent;
