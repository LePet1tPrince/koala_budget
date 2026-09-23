import React from 'react';

import { createNetWorthStackChart } from '../charts/networthStackChart';
import { currency } from '../format';
import { accountChange, netWorthWindow } from '../netWorthWindow';
import ChartCanvas from '../parts/ChartCanvas';
import InsightList from '../parts/InsightList';

/** Step 8: what it all adds up to -- net worth composition over the selected baseline's span. */
const StepNetWorth = ({ review, baseline }) => {
  const { net_worth: netWorth } = review;
  const windowed = netWorthWindow(netWorth, baseline, review.month);
  const windowStart = windowed.series.length > 1 ? windowed.series[0] : null;
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
        create={(canvas) => createNetWorthStackChart(canvas, windowed.series, windowed.stack)}
        deps={[netWorth, baseline]}
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
              <th className="text-right">{windowStart ? `Change since ${windowStart.label}` : 'Change'}</th>
            </tr>
          </thead>
          <tbody>
            {netWorth.by_account.map((row, i) => {
              const change = accountChange(row, baseline);
              return (
                <tr key={i}>
                  <td className="capitalize">{row.type}</td>
                  <td>{row.name}</td>
                  <td className="text-right">{currency(row.balance)}</td>
                  {change === null ? (
                    <td className="text-right text-base-content/70">—</td>
                  ) : (
                    <td className={`text-right ${change >= 0 ? 'text-success' : 'text-error'}`}>{currency(change)}</td>
                  )}
                </tr>
              );
            })}
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
