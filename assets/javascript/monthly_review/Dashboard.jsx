import React from 'react';

import BaselineBar from './BaselineBar';
import { createFlowChart } from './charts/flowChart';
import { createNetWorthStackChart } from './charts/networthStackChart';
import { currency } from './format';
import ChartCanvas from './parts/ChartCanvas';
import DrillTable from './parts/DrillTable';
import InsightList from './parts/InsightList';

/**
 * The permanent month dashboard (§4.10): the same payload as the walkthrough,
 * everything at once, no step gating. Always reachable at the review's own
 * URL for any month.
 */
const Dashboard = ({ review, baselines, baselineOrder, baseline, currentBaseline, onBaselineChange, onWalkthrough, urls }) => {
  const { current, budget, biggest, net_worth: netWorth, health } = review;

  return (
    <div className="max-w-6xl mx-auto py-6 space-y-6" data-testid="monthly-review-dashboard">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">{review.month_label}</h1>
          {review.is_current_month && (
            <div className="badge badge-warning badge-sm mt-1">This month isn&apos;t over yet</div>
          )}
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <BaselineBar baselines={baselines} order={baselineOrder} value={baseline} onChange={onBaselineChange} />
          <button
            type="button"
            className="btn btn-outline btn-sm"
            onClick={onWalkthrough}
            data-testid="walk-me-through-btn"
          >
            &#9654; Walk me through {review.month_label}
          </button>
          <a href={urls.export} className="btn btn-outline btn-sm">
            Export CSV
          </a>
        </div>
      </div>

      <div
        className={`app-card ${health.all_clear ? 'border-success/40' : 'border-warning/40'}`}
        data-testid="health-strip"
      >
        {health.all_clear ? "Everything's accounted for." : `${health.flags.length} thing(s) need attention this month.`}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatBlock
          label="Money in"
          value={current.income}
          delta={currentBaseline && current.income - currentBaseline.avgs.income}
          testId="dash-income"
        />
        <StatBlock
          label="Money out"
          value={current.spend}
          delta={currentBaseline && current.spend - currentBaseline.avgs.spend}
          goodIsUp={false}
          testId="dash-spend"
        />
        <StatBlock
          label="Saved"
          value={current.saved}
          delta={currentBaseline && current.saved - currentBaseline.avgs.saved}
          testId="dash-saved"
        />
        <StatBlock
          label="Left over"
          value={current.net}
          delta={currentBaseline && current.net - currentBaseline.avgs.net}
          testId="dash-net"
        />
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <div className="app-card">
          <h2 className="font-semibold mb-2">Income &amp; spending flow</h2>
          <ChartCanvas
            create={(canvas) => createFlowChart(canvas, currentBaseline, current)}
            deps={[currentBaseline, current]}
            height={260}
            testId="flow-chart"
          />
        </div>
        <div className="app-card">
          <h2 className="font-semibold mb-2">Net worth composition</h2>
          <ChartCanvas
            create={(canvas) => createNetWorthStackChart(canvas, netWorth.series, netWorth.stack)}
            deps={[netWorth]}
            height={260}
            testId="dash-net-worth-chart"
          />
        </div>
      </div>

      <div className="app-card">
        <h2 className="font-semibold mb-4">Budget</h2>
        <DrillTable
          groups={budget.groups}
          catTxns={review.cat_txns}
          catAvg={currentBaseline ? currentBaseline.cat_avg : null}
          baselineLabel={currentBaseline ? currentBaseline.short : ''}
        />
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <div className="app-card">
          <h2 className="font-semibold mb-2">Largest transactions</h2>
          <div className="overflow-x-auto">
            <table className="table table-sm table-quiet">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Payee</th>
                  <th className="text-right">Amount</th>
                </tr>
              </thead>
              <tbody>
                {biggest.slice(0, 10).map((r, i) => (
                  <tr key={i}>
                    <td>{r.date}</td>
                    <td>{r.payee || '—'}</td>
                    <td className="text-right">{currency(r.amount)}</td>
                  </tr>
                ))}
                {!biggest.length && (
                  <tr>
                    <td colSpan={3} className="text-base-content/60">
                      No expense transactions this month.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
        <div className="app-card">
          <h2 className="font-semibold mb-2">Net worth by account</h2>
          <div className="overflow-x-auto">
            <table className="table table-sm table-quiet">
              <thead>
                <tr>
                  <th>Account</th>
                  <th className="text-right">Balance</th>
                  <th className="text-right">Change</th>
                </tr>
              </thead>
              <tbody>
                {netWorth.by_account.map((r, i) => (
                  <tr key={i}>
                    <td>{r.name}</td>
                    <td className="text-right">{currency(r.balance)}</td>
                    <td className={`text-right ${r.change >= 0 ? 'text-success' : 'text-error'}`}>
                      {currency(r.change)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="app-card">
        <h2 className="font-semibold mb-4">Insights</h2>
        <div className="space-y-3">
          {[1, 2, 3, 4, 5, 6, 7, 8].map((step) => (
            <InsightList key={step} insights={review.insights} step={step} testId={`dash-insights-${step}`} />
          ))}
        </div>
      </div>

      {review.notes.length > 0 && (
        <div className="text-xs text-base-content/60 space-y-1" data-testid="review-notes">
          <div className="font-medium">How these numbers are built</div>
          {review.notes.map((note, i) => (
            <p key={i}>{note}</p>
          ))}
        </div>
      )}
    </div>
  );
};

const StatBlock = ({ label, value, delta, testId, goodIsUp = true }) => (
  <div className="app-card" data-testid={testId}>
    <div className="text-sm text-base-content/70">{label}</div>
    <div className="text-2xl font-semibold mt-1">{currency(value)}</div>
    {delta !== undefined && delta !== null && (
      <div className={`text-xs font-medium mt-1 ${(delta >= 0) === goodIsUp ? 'text-success' : 'text-error'}`}>
        {delta >= 0 ? '▲' : '▼'} {currency(Math.abs(delta))}
      </div>
    )}
  </div>
);

export default Dashboard;
