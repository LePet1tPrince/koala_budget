import React from 'react';

import { createStreamsChart } from '../charts/streamsChart';
import { currency } from '../format';
import ChartCanvas from '../parts/ChartCanvas';
import InsightList from '../parts/InsightList';

const CHART_SERIES_LIMIT = 8;

/** Step 3: where the money came from -- streams vs baseline average. */
const StepIncome = ({ review, baseline }) => {
  const rows = baseline ? baseline.streams : [];
  const total = rows.reduce((sum, r) => sum + r.amount, 0);

  return (
    <div>
      <p className="text-sm text-base-content/70 mb-4">
        {rows.length} income source{rows.length === 1 ? '' : 's'} this month, totaling {currency(total)}.
      </p>
      {rows.length > 0 && (
        <ChartCanvas
          create={(canvas) => createStreamsChart(canvas, rows.slice(0, CHART_SERIES_LIMIT))}
          deps={[rows]}
          height={Math.max(200, Math.min(rows.length, CHART_SERIES_LIMIT) * 36)}
          testId="income-streams-chart"
        />
      )}
      <div className="overflow-x-auto mt-4">
        <table className="table table-sm table-quiet" data-testid="income-streams-table">
          <thead>
            <tr>
              <th>Source</th>
              <th className="text-right">This month</th>
              <th className="text-right">Average</th>
              <th className="text-right">vs average</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.payee}>
                <td>
                  {r.payee}
                  {r.new && <span className="badge badge-info badge-sm ml-2">new</span>}
                </td>
                <td className="text-right">{currency(r.amount)}</td>
                <td className="text-right">{currency(r.avg)}</td>
                <td className={`text-right ${r.vs_avg >= 0 ? 'text-success' : 'text-error'}`}>
                  {currency(r.vs_avg)}
                </td>
              </tr>
            ))}
            {!rows.length && (
              <tr>
                <td colSpan={4} className="text-base-content/60">
                  No baseline history yet -- comparisons will appear once there is a prior month.
                </td>
              </tr>
            )}
            {rows.length > 0 && (
              <tr className="font-medium">
                <td>Total</td>
                <td className="text-right">{currency(total)}</td>
                <td />
                <td />
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="mt-4">
        <InsightList insights={review.insights} step={3} />
      </div>
    </div>
  );
};

export default StepIncome;
