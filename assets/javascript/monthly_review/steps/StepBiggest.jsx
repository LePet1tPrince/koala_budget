import React from 'react';

import { currency } from '../format';
import InsightList from '../parts/InsightList';

const SAMPLE_SIZE = 10;

/** Step 5: the biggest line items -- top 10 single transactions. */
const StepBiggest = ({ review }) => {
  const rows = review.biggest.slice(0, SAMPLE_SIZE);
  const spend = review.current.spend || 0;
  const total = rows.reduce((sum, r) => sum + r.amount, 0);
  const share = spend ? (total / spend) * 100 : 0;

  return (
    <div>
      <p className="text-sm text-base-content/70 mb-4">
        {rows.length ? (
          <>These {rows.length} transactions represent {share.toFixed(0)}% of this month&apos;s spending.</>
        ) : (
          'No expense transactions this month.'
        )}
      </p>
      <div className="overflow-x-auto">
        <table className="table table-sm table-quiet" data-testid="biggest-transactions-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Payee</th>
              <th>Category</th>
              <th>Account</th>
              <th className="text-right">Amount</th>
              <th className="text-right">Share</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td>{r.date}</td>
                <td>
                  <a href={r.entry_url} className="link link-hover">
                    {r.payee || '—'}
                  </a>
                </td>
                <td>{r.category}</td>
                <td>{r.account}</td>
                <td className="text-right">{currency(r.amount)}</td>
                <td className="text-right">{spend ? `${((r.amount / spend) * 100).toFixed(1)}%` : '—'}</td>
              </tr>
            ))}
            {rows.length > 0 && (
              <tr className="font-medium">
                <td colSpan={4}>Total</td>
                <td className="text-right">{currency(total)}</td>
                <td className="text-right">{share.toFixed(0)}%</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="mt-4">
        <InsightList insights={review.insights} step={5} />
      </div>
    </div>
  );
};

export default StepBiggest;
