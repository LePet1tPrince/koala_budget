/* globals gettext */

import React, { useEffect, useRef } from 'react';

import { formatCurrency } from '../utilities/currency';
import { formatDate } from '../bank_feed/utils';
import DateRangePicker from '../common/DateRangePicker';

/**
 * Badge component for displaying status/source labels.
 */
const Badge = ({ children, className }) => (
  <span className={`badge badge-sm ${className}`}>
    {children}
  </span>
);

/**
 * Map source values to human-readable labels and badge colours.
 */
const SOURCE_STYLES = {
  manual: { label: 'Manual', className: 'badge-ghost' },
  import: { label: 'Import', className: 'badge-soft badge-info' },
  bank_match: { label: 'Bank', className: 'badge-soft badge-accent' },
  recurring: { label: 'Recurring', className: 'badge-soft badge-secondary' },
};

const STATUS_STYLES = {
  draft: { label: 'Draft', className: 'badge-soft badge-warning' },
  posted: { label: 'Posted', className: 'badge-soft badge-success' },
  void: { label: 'Void', className: 'badge-soft badge-error' },
};

const FALLBACK_BADGE = 'badge-ghost';

/**
 * TransactionsTable - displays a flat list of journal entries as transaction rows.
 *
 * Search and date filtering are applied server-side (against the full ledger,
 * not just the rows currently loaded); this component only renders whatever
 * `transactions` it's given and asks for more rows via `onLoadMore` once the
 * sentinel at the bottom of the list scrolls into view.
 *
 * Props:
 *   transactions  – array of transaction row objects for the current filters
 *   search        – current search input value
 *   onSearchChange – (value) => void
 *   startDate/endDate – current date range filter
 *   onDateApply   – (start, end) => void
 *   onLoadMore    – () => void, fetches the next page of the current filters
 *   hasMore       – whether another page is available
 *   loadingMore   – whether a "load more" request is in flight
 *   refetching    – whether the current filters are being (re)applied
 *   error         – error message to show alongside stale results, if any
 */
const TransactionsTable = ({
  transactions,
  search,
  onSearchChange,
  startDate,
  endDate,
  onDateApply,
  onLoadMore,
  hasMore,
  loadingMore,
  refetching,
  error,
}) => {
  const sentinelRef = useRef(null);

  useEffect(() => {
    const node = sentinelRef.current;
    if (!node || !hasMore) return undefined;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) {
          onLoadMore();
        }
      },
      { rootMargin: '200px' }
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [hasMore, onLoadMore, transactions.length]);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4">
        <input
          type="text"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder={gettext('Search by payee, description, account, or amount...')}
          className="input input-bordered flex-1"
          data-testid="transaction-search"
        />
        <DateRangePicker
          startDate={startDate}
          endDate={endDate}
          onApply={onDateApply}
        />
      </div>

      {refetching && (
        <div className="text-sm text-base-content/70" data-testid="transactions-refetching">
          {gettext('Searching…')}
        </div>
      )}

      {error && (
        <div className="text-sm text-error" data-testid="transactions-error">
          {gettext('Error loading transactions:')} {error}
        </div>
      )}

      <div className="app-surface overflow-x-auto">
        <table className="table table-sm table-quiet w-full" data-testid="transactions-table">
          <thead>
            <tr>
              <th>{gettext('Date')}</th>
              <th>{gettext('Payee')}</th>
              <th>{gettext('Description')}</th>
              <th>{gettext('Debit Account')}</th>
              <th>{gettext('Credit Account')}</th>
              <th className="text-right">{gettext('Amount')}</th>
              <th>{gettext('Source')}</th>
              <th>{gettext('Status')}</th>
            </tr>
          </thead>
          <tbody>
            {transactions.map((tx) => {
              const source = SOURCE_STYLES[tx.source] || { label: tx.source, className: FALLBACK_BADGE };
              const statusStyle = STATUS_STYLES[tx.status] || { label: tx.status, className: FALLBACK_BADGE };

              return (
                <tr key={tx.id} data-testid="transaction-row">
                  <td className="whitespace-nowrap">
                    {formatDate(tx.date)}
                  </td>
                  <td className="whitespace-nowrap">
                    {tx.payee_name || <span className="text-base-content/40 italic">{gettext('—')}</span>}
                  </td>
                  <td className="max-w-xs truncate">
                    {tx.description}
                  </td>
                  <td className="whitespace-nowrap">
                    {tx.debit_account || '—'}
                  </td>
                  <td className="whitespace-nowrap">
                    {tx.credit_account || '—'}
                  </td>
                  <td className="money whitespace-nowrap text-right">
                    {formatCurrency(tx.amount)}
                  </td>
                  <td className="whitespace-nowrap">
                    <Badge className={source.className}>{source.label}</Badge>
                  </td>
                  <td className="whitespace-nowrap">
                    <Badge className={statusStyle.className}>{statusStyle.label}</Badge>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {transactions.length === 0 && !refetching && (
        <div className="text-center py-12 text-base-content/70" data-testid="transactions-empty-state">
          {gettext('No transactions found.')}
        </div>
      )}

      <div ref={sentinelRef} />

      {loadingMore && (
        <div className="text-center py-4 text-base-content/70" data-testid="transactions-loading-more">
          {gettext('Loading more transactions…')}
        </div>
      )}
    </div>
  );
};

export default TransactionsTable;
