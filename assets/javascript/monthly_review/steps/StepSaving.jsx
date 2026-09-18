import React from 'react';

import { currency, percent } from '../format';
import InsightList from '../parts/InsightList';
import StatCard from '../parts/StatCard';

/** Step 7: what we put away -- savings-rate cards plus a per-goal table. */
const StepSaving = ({ review, baseline }) => {
  const { current } = review;
  const rows = baseline ? baseline.saving_rows : [];
  // The average column would duplicate "Last month" under a 1-month baseline.
  const showAvgColumn = Boolean(baseline && baseline.months > 1);

  return (
    <div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
        <StatCard label="Saved" value={current.saved} testId="stat-saved-2" />
        <StatCard label="Savings rate" value={current.savings_rate} format={percent} testId="stat-savings-rate" />
        <StatCard label="Left over after everything" value={current.net} testId="stat-left-over" />
      </div>
      <div className="overflow-x-auto">
        <table className="table table-sm table-quiet" data-testid="goal-savings-table">
          <thead>
            <tr>
              <th>Destination</th>
              <th className="text-right">This month</th>
              <th className="text-right">Last month</th>
              {showAvgColumn && <th className="text-right">{baseline.short} average</th>}
              <th className="text-right">vs baseline</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.goal.id}>
                <td>{r.goal.name}</td>
                <td className="text-right">{currency(r.amount)}</td>
                <td className="text-right">{currency(r.prev)}</td>
                {showAvgColumn && <td className="text-right">{currency(r.avg)}</td>}
                <td className={`text-right ${r.vs_avg >= 0 ? 'text-success' : 'text-error'}`}>
                  {currency(r.vs_avg)}
                </td>
              </tr>
            ))}
            {!rows.length && (
              <tr>
                <td colSpan={showAvgColumn ? 5 : 4} className="text-base-content/60">
                  No goal activity to compare yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="mt-4">
        <InsightList insights={review.insights} step={7} />
      </div>
    </div>
  );
};

export default StepSaving;
