import React, { useRef, useState } from 'react';
import { createPortal } from 'react-dom';

import Icon from '../../common/Icon';
import { portalTarget, useAnchoredPosition } from '../../common/popoverPosition';
import { currency } from '../format';

const TYPE_ORDER = ['asset', 'liability'];
const TOOLTIP_ID = 'health-row-tooltip';

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

const isSevere = (flag) => flag.kind === 'no_transactions';

/** Row background: red when the account had nothing to check, yellow for any other flag. */
const rowClass = (flags) => {
  if (flags.some(isSevere)) return 'bg-error/10';
  if (flags.length) return 'bg-warning/10';
  return '';
};

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

/** "2026-08-12" -> "Aug 12, 2026", parsed as a local date so it can't shift a day. */
const shortDate = (iso) => {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
};

/** One plain sentence per flag, saying what tripped it. */
const flagSentence = (flag, monthLabel) => {
  switch (flag.kind) {
    case 'no_transactions':
      return `No transactions in ${monthLabel}. Did an import get missed?`;
    case 'stale_account':
      return `Last transaction was ${shortDate(flag.last_transaction_date)}, ${flag.days} days before month end. Check the feed is still syncing.`;
    case 'uncategorized':
      return `${plural(flag.count, 'transaction', 'transactions')} posted by the end of ${monthLabel} ${flag.count === 1 ? 'is' : 'are'} still uncategorized.`;
    case 'unreconciled':
      return `${plural(flag.count, 'transaction', 'transactions')} in ${monthLabel} ${flag.count === 1 ? "isn't" : "aren't"} reconciled yet.`;
    default:
      return null;
  }
};

/** The hovered (or focused) row's reasons, placed against that row. */
const FlagTooltip = ({ row, anchorRef, monthLabel }) => {
  const panelRef = useRef(null);
  const { style } = useAnchoredPosition(row?.account.id, anchorRef, panelRef);
  if (!row) return null;
  return createPortal(
    <div
      ref={panelRef}
      id={TOOLTIP_ID}
      role="tooltip"
      className="fixed z-[1200] max-w-sm rounded-xl border border-base-300 bg-base-100 p-3 text-sm shadow-lg pointer-events-none"
      style={style ? { top: style.top, left: style.left } : { top: 0, left: 0, visibility: 'hidden' }}
      data-testid="health-row-tooltip"
    >
      <ul className="space-y-1.5">
        {row.flags.map((flag) => {
          const sentence = flagSentence(flag, monthLabel);
          if (!sentence) return null;
          return (
            <li key={flag.kind} className="flex gap-2 items-start">
              <Icon
                name={isSevere(flag) ? 'circle-alert' : 'triangle-alert'}
                className={`w-4 h-4 shrink-0 mt-0.5 ${isSevere(flag) ? 'text-error' : 'text-warning'}`}
              />
              <span>{sentence}</span>
            </li>
          );
        })}
      </ul>
    </div>,
    portalTarget(anchorRef.current),
  );
};

/** Step 1: the trust gate. Never blocks -- one row per asset/liability account, flagged rows highlighted. */
const StepHealth = ({ review }) => {
  const { accounts, all_clear: allClear } = review.health;
  const [activeRow, setActiveRow] = useState(null);
  const anchorRef = useRef(null);

  const show = (row) => (event) => {
    anchorRef.current = event.currentTarget;
    setActiveRow(row);
  };
  const hide = () => setActiveRow(null);

  return (
    <div>
      <p className="text-base-content/70 mb-4">
        Before looking at numbers, let&apos;s make sure this month&apos;s data is trustworthy.
      </p>

      {allClear && (
        <div
          className="rounded-box border border-success/40 bg-success/5 text-success p-3 mb-4 flex items-center gap-2 text-sm"
          data-testid="health-all-clear"
        >
          <Icon name="check-circle" className="w-4 h-4 shrink-0" />
          Everything&apos;s accounted for.
        </div>
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
                {rows.map((row) => {
                  const flagged = row.flags.length > 0;
                  const active = activeRow?.account.id === row.account.id;
                  return (
                    <tr
                      key={row.account.id}
                      className={`${rowClass(row.flags)} ${flagged ? 'cursor-help focus:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-inset' : ''}`}
                      data-testid={`health-row-${row.account.id}`}
                      {...(flagged && {
                        tabIndex: 0,
                        onMouseEnter: show(row),
                        onMouseLeave: hide,
                        onFocus: show(row),
                        onBlur: hide,
                        'aria-describedby': active ? TOOLTIP_ID : undefined,
                      })}
                    >
                      <td className="pl-6">{row.account.name}</td>
                      <td className="text-right">{row.transaction_count}</td>
                      <td className="text-right">{row.unreconciled_count}</td>
                      <td className="text-right">{currency(row.balance_change)}</td>
                    </tr>
                  );
                })}
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

      <FlagTooltip row={activeRow} anchorRef={anchorRef} monthLabel={review.month_label} />
    </div>
  );
};

export default StepHealth;
