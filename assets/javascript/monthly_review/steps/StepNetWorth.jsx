import React from 'react';

import { createNetWorthStackChart } from '../charts/networthStackChart';
import { currency } from '../format';
import ChartCanvas from '../parts/ChartCanvas';
import InsightList from '../parts/InsightList';

/** Step 8: what it all adds up to -- net worth composition over the baseline span. */
const StepNetWorth = ({ review }) => {
  const { net_worth: netWorth } = review;
  const windowStart = netWorth.series[0];
  const windowChange = windowStart ? netWorth.now.net - windowStart.net : null;

  return (
    <div>
      <p className="text-sm text-base-content/70 mb-4">
        Net worth is {currency(netWorth.now.net)}
        {windowStart && windowChange !== null && (
          <>
            , {windowChange >= 0 ? 'up' : 'down'} {currency(Math.abs(windowChange))} since {windowStart.label}
          </>
        )}
        .
      </p>
      <ChartCanvas
        create={(canvas) => createNetWorthStackChart(canvas, netWorth.series, netWorth.stack)}
        deps={[netWorth]}
        height={320}
        testId="net-worth-composition-chart"
      />
      <div className="overflow-x-auto mt-4">
        <table className="table table-sm table-quiet" data-testid="net-worth-by-account-table">
          <thead>
            <tr>
              <th>Type</th>
              <th>Account</th>
              <th className="text-right">Balance</th>
              <th className="text-right">Change</th>
            </tr>
          </thead>
          <tbody>
            {netWorth.by_account.map((row, i) => (
              <tr key={i}>
                <td className="capitalize">{row.type}</td>
                <td>{row.name}</td>
                <td className="text-right">{currency(row.balance)}</td>
                <td className={`text-right ${row.change >= 0 ? 'text-success' : 'text-error'}`}>
                  {currency(row.change)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-4">
        <InsightList insights={review.insights} step={8} />
      </div>
    </div>
  );
};

export default StepNetWorth;
