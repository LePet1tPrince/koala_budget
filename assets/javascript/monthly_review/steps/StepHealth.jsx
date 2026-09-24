import React from 'react';

import Icon from '../../common/Icon';
import { currency } from '../format';

const TYPE_ORDER = ['asset', 'liability'];

/**
 * Accounts grouped by institution (A–Z, "No institution" last). Within a group,
 * assets sort before liabilities; the sort is stable, so each keeps board order.
 */
const groupAccounts = (accounts) => {
  const byInstitution = new Map();
  accounts.forEach((row) => {
    const key = row.institution || '';
    if (!byInstitution.has(key)) byInstitution.set(key, []);
    byInstitution.get(key).push(row);
  });
  return [...byInstitution.entries()]
    .sort(([a], [b]) => (!a ? 1 : !b ? -1 : a.localeCompare(b)))
    .map(([institution, rows]) => ({
      institution,
      rows: rows.sort((a, b) => TYPE_ORDER.indexOf(a.account_type) - TYPE_ORDER.indexOf(b.account_type)),
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
            {groupAccounts(accounts).map(({ institution, rows }) => (
              <React.Fragment key={institution || '__none__'}>
                <tr className="bg-base-200/60" data-testid="health-institution-row">
                  <td colSpan={4} className="font-semibold">
                    {institution || 'No institution'}
                  </td>
                </tr>
                {rows.map((row) => (
                  <tr key={row.account.id} className={rowClass(row.flags)} title={flagTitles(row.flags)}>
                    <td className="pl-6">{row.account.name}</td>
                    <td className="text-right">{row.transaction_count}</td>
                    <td className="text-right">{row.unreconciled_count}</td>
                    <td className="text-right">{currency(row.balance_change)}</td>
                  </tr>
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
