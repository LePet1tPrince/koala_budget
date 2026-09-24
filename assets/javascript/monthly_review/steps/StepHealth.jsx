import React from 'react';

import Icon from '../../common/Icon';
import { currency } from '../format';

const TYPE_ORDER = ['asset', 'liability'];
const TYPE_HEADING = { asset: 'Assets', liability: 'Liabilities' };

/**
 * Institution → account type → accounts. Institutions A–Z with "No institution"
 * last; assets before liabilities; accounts keep the server's (board) order.
 */
const groupAccounts = (accounts) => {
  const byInstitution = new Map();
  accounts.forEach((row) => {
    const key = row.institution || '';
    if (!byInstitution.has(key)) byInstitution.set(key, new Map());
    const byType = byInstitution.get(key);
    if (!byType.has(row.account_type)) byType.set(row.account_type, []);
    byType.get(row.account_type).push(row);
  });
  return [...byInstitution.entries()]
    .sort(([a], [b]) => (!a ? 1 : !b ? -1 : a.localeCompare(b)))
    .map(([institution, byType]) => ({
      institution,
      types: [...byType.entries()]
        .sort(([a], [b]) => TYPE_ORDER.indexOf(a) - TYPE_ORDER.indexOf(b))
        .map(([type, rows]) => ({ type, rows })),
    }));
};

/** Row background: red when the account had nothing to check, yellow for any other flag. */
const rowClass = (flags) => {
  const kinds = flags.map((f) => f.kind);
  if (kinds.includes('no_transactions')) return 'bg-error/10';
  if (kinds.length) return 'bg-warning/10';
  return '';
};

const flagTitles = (flags) => flags.map((f) => f.kind.replace(/_/g, ' ')).join(', ');

/** Step 1: the trust gate. Never blocks -- one row per asset/liability account, flagged rows highlighted. */
const StepHealth = ({ review }) => {
  const { accounts, all_clear: allClear } = review.health;

  return (
    <div>
      <p className="text-base-content/70 mb-4">
        Before looking at numbers, let&apos;s make sure this month&apos;s data is trustworthy.
      </p>

      {allClear ? (
        <div
          className="rounded-box border border-success/40 bg-success/5 text-success p-3 mb-4 flex items-center gap-2 text-sm"
          data-testid="health-all-clear"
        >
          <Icon name="check-circle" className="w-4 h-4 shrink-0" />
          Everything&apos;s accounted for.
        </div>
      ) : (
        <p className="text-sm text-base-content/70 mb-4">
          <span className="inline-flex items-center gap-1.5 mr-4">
            <span className="w-3 h-3 rounded-sm bg-warning/40 inline-block" /> needs a check
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="w-3 h-3 rounded-sm bg-error/40 inline-block" /> no activity this month
          </span>
        </p>
      )}

      <div className="overflow-x-auto app-surface">
        <table className="table table-sm table-quiet" data-testid="step-health-table">
          <thead>
            <tr>
              <th>Account</th>
              <th className="text-right">Transactions</th>
              <th className="text-right">Unreconciled</th>
              <th className="text-right">Balance change</th>
            </tr>
          </thead>
          <tbody>
            {groupAccounts(accounts).map(({ institution, types }) => (
              <React.Fragment key={institution || '__none__'}>
                <tr className="bg-base-200/60" data-testid="health-institution-row">
                  <td colSpan={4} className="font-semibold">
                    {institution || 'No institution'}
                  </td>
                </tr>
                {types.map(({ type, rows }) => (
                  <React.Fragment key={type}>
                    <tr>
                      <td colSpan={4} className="pl-6 text-xs uppercase tracking-wide text-base-content/70">
                        {TYPE_HEADING[type] || type}
                      </td>
                    </tr>
                    {rows.map((row) => (
                      <tr key={row.account.id} className={rowClass(row.flags)} title={flagTitles(row.flags)}>
                        <td className="pl-10">{row.account.name}</td>
                        <td className="text-right">{row.transaction_count}</td>
                        <td className="text-right">{row.unreconciled_count}</td>
                        <td className="text-right">{currency(row.balance_change)}</td>
                      </tr>
                    ))}
                  </React.Fragment>
                ))}
              </React.Fragment>
            ))}
            {!accounts.length && (
              <tr>
                <td colSpan={4} className="text-center text-base-content/70 py-6">
                  No feed accounts yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default StepHealth;
