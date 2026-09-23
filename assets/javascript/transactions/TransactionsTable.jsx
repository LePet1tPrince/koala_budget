/* globals gettext */

import React, { useEffect, useRef, useState } from 'react';

import { formatCurrency } from '../utilities/currency';
import { formatDate } from '../bank_feed/utils';
import DateRangePicker from '../common/DateRangePicker';
import Icon from '../common/Icon';
import ColumnMenu from './ColumnMenu';
import { FALLBACK_BADGE, SOURCE_STYLES, STATUS_STYLES, TRANSACTION_COLUMNS } from './columns';

/**
 * Badge component for displaying status/source labels.
 */
const Badge = ({ children, className }) => (
  <span className={`badge badge-sm ${className}`}>
    {children}
  </span>
);

/** Sort indicator on a column header: an arrow that flips for descending. */
const SortArrow = ({ active, direction }) => (
  <Icon
    name="arrow-up"
    className={`w-3 h-3 shrink-0 transition-transform ${active ? 'opacity-70' : 'opacity-0 group-hover:opacity-30'} ${
      active && direction === 'desc' ? 'rotate-180' : ''
    }`}
  />
);

/**
 * One column header: the label toggles sorting, the chevron opens the menu.
 *
 * Clicking the label cycles asc -> desc -> unsorted, so the default
 * newest-first ordering is always one more click away rather than something
 * you have to hunt for in the menu.
 */
const ColumnHeader = ({ column, sort, onSortChange, filterValues, onFilterChange, fetchFacets }) => {
  const isSorted = sort && sort.key === column.key;

  const cycleSort = () => {
    if (!isSorted) onSortChange({ key: column.key, dir: 'asc' });
    else if (sort.dir === 'asc') onSortChange({ key: column.key, dir: 'desc' });
    else onSortChange(null);
  };

  return (
    <th className={column.align === 'right' ? 'text-right' : undefined}>
      <div className={`group flex items-center gap-1 ${column.align === 'right' ? 'justify-end' : ''}`}>
        <button
          type="button"
          className="inline-flex items-center gap-1 rounded hover:text-base-content"
          onClick={cycleSort}
          data-testid={`column-sort-${column.key}`}
          aria-label={gettext('Sort by {column}').replace('{column}', column.label)}
        >
          <span className={isSorted ? 'text-primary' : undefined}>{column.label}</span>
          <SortArrow active={isSorted} direction={isSorted ? sort.dir : null} />
        </button>
        {filterValues.length > 0 && (
          <span className="badge badge-xs badge-primary tabular-nums" data-testid={`column-filter-count-${column.key}`}>
            {filterValues.length}
          </span>
        )}
        <ColumnMenu
          column={column}
          selected={filterValues}
          sort={sort}
          onSortChange={onSortChange}
          onApply={(values) => onFilterChange(column.key, values)}
          fetchFacets={fetchFacets}
        />
      </div>
    </th>
  );
};

/**
 * The "Payee: Amazon, Costco ×" chips summarising what's currently filtered.
 *
 * Each entry carries its own label, set when it was ticked — a branch token
 * like `g:12` or `2025-03` has no readable form the client could derive.
 */
const ActiveFilters = ({ columnFilters, onFilterChange, onClearAll }) => {
  const active = TRANSACTION_COLUMNS.filter((column) => (columnFilters[column.key] || []).length > 0);
  if (active.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="active-column-filters">
      {active.map((column) => {
        const values = columnFilters[column.key];
        const shown = values
          .slice(0, 3)
          .map((entry) => entry.label || gettext('(none)'))
          .join(', ');
        const extra = values.length - 3;
        return (
          <button
            key={column.key}
            type="button"
            className="badge badge-soft badge-primary gap-1"
            onClick={() => onFilterChange(column.key, [])}
            data-testid={`active-filter-${column.key}`}
            title={gettext('Clear this filter')}
          >
            <span className="font-medium">{column.label}:</span>
            <span className="max-w-[16rem] truncate">
              {shown}
              {extra > 0 && gettext(' +{n} more').replace('{n}', extra)}
            </span>
            <Icon name="times" className="w-3 h-3 shrink-0" />
          </button>
        );
      })}
      <button type="button" className="btn btn-ghost btn-xs" onClick={onClearAll} data-testid="clear-column-filters">
        {gettext('Clear all')}
      </button>
    </div>
  );
};

/**
 * TransactionsTable - displays a flat list of journal entries as transaction rows.
 *
 * Search, date filtering, per-column value filters and sorting are all applied
 * server-side (against the full ledger, not just the rows currently loaded);
 * this component only renders whatever `transactions` it's given and asks for
 * more rows via `onLoadMore` once the sentinel at the bottom of the list
 * scrolls into view.
 *
 * Props:
 *   transactions  – array of transaction row objects for the current filters
 *   search        – current search input value
 *   onSearchChange – (value) => void
 *   startDate/endDate – current date range filter
 *   onDateApply   – (start, end) => void
 *   columnFilters – { [columnKey]: [{value, label}] } of selected values per column
 *   onColumnFilterChange – (columnKey, entries) => void
 *   onClearColumnFilters – () => void
 *   sort          – { key, dir } or null for the default newest-first order
 *   onSortChange  – (sort | null) => void
 *   fetchFacets   – (columnKey, query) => Promise<{values, hierarchical, truncated}>
 *   onLoadMore    – () => void, fetches the next page of the current filters
 *   hasMore       – whether another page is available
 *   loadingMore   – whether a "load more" request is in flight
 *   refetching    – whether the current filters are being (re)applied
 *   error         – error message to show alongside stale results, if any
 *   onEditRow     – (row) => void, opens the edit modal for that transaction
 */
const TransactionsTable = ({
  transactions,
  search,
  onSearchChange,
  startDate,
  endDate,
  onDateApply,
  columnFilters,
  onColumnFilterChange,
  onClearColumnFilters,
  sort,
  onSortChange,
  fetchFacets,
  onLoadMore,
  hasMore,
  loadingMore,
  refetching,
  error,
  onEditRow,
}) => {
  const sentinelRef = useRef(null);

  // Which splits are showing their legs. Local and deliberately not persisted:
  // it is a glance at one row, not a view setting worth surviving a reload.
  const [expandedIds, setExpandedIds] = useState(() => new Set());

  const toggleExpanded = (id) =>
    setExpandedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

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

      <ActiveFilters
        columnFilters={columnFilters}
        onFilterChange={onColumnFilterChange}
        onClearAll={onClearColumnFilters}
      />

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
              {TRANSACTION_COLUMNS.map((column) => (
                <ColumnHeader
                  key={column.key}
                  column={column}
                  sort={sort}
                  onSortChange={onSortChange}
                  filterValues={columnFilters[column.key] || []}
                  onFilterChange={onColumnFilterChange}
                  fetchFacets={fetchFacets}
                />
              ))}
              {/* The edit column. No label: the pencil in each row says what it
                  is, and a header here would look like a sortable field. */}
              <th className="w-10" aria-label={gettext('Edit')} />
            </tr>
          </thead>
          <tbody>
            {transactions.map((tx) => {
              const source = SOURCE_STYLES[tx.source] || { label: tx.source, className: FALLBACK_BADGE };
              const statusStyle = STATUS_STYLES[tx.status] || { label: tx.status, className: FALLBACK_BADGE };
              const expanded = expandedIds.has(tx.id);

              return (
                <React.Fragment key={tx.id}>
                  <tr
                    data-testid="transaction-row"
                    className="cursor-pointer hover:bg-base-200"
                    onClick={() => onEditRow?.(tx)}
                    // The pencil button below is the control a keyboard or screen
                    // reader reaches; the row click is a convenience on top of it,
                    // which is why the <tr> gets no tabIndex or role of its own.
                  >
                    <td className="whitespace-nowrap">
                      {formatDate(tx.date)}
                    </td>
                    <td className="whitespace-nowrap">
                      {tx.payee_name || <span className="text-base-content/40 italic">{gettext('—')}</span>}
                    </td>
                    <td className="max-w-xs truncate">
                      {/* A split has no per-leg memo, so the marker beside the
                          description is what identifies one in the ledger. */}
                      {tx.is_split && (
                        <button
                          type="button"
                          className="badge badge-ghost badge-sm mr-1"
                          onClick={(e) => {
                            // Expanding a split is a look, not an edit — without
                            // this the row handler would open the modal over it.
                            e.stopPropagation();
                            toggleExpanded(tx.id);
                          }}
                          aria-expanded={expanded}
                          title={gettext('Show the categories this transaction is split across')}
                          data-testid={`split-toggle-${tx.id}`}
                        >
                          <Icon
                            name="chevron-right"
                            className={`h-3 w-3 transition-transform ${expanded ? 'rotate-90' : ''}`}
                          />
                          {gettext('Split')}
                        </button>
                      )}
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
                    <td className="w-10">
                      <button
                        type="button"
                        className="btn btn-ghost btn-xs"
                        onClick={(e) => {
                          e.stopPropagation();
                          onEditRow?.(tx);
                        }}
                        aria-label={gettext('Edit transaction')}
                        data-testid={`edit-row-${tx.id}`}
                      >
                        <Icon name="edit" className="h-4 w-4" />
                      </button>
                    </td>
                  </tr>
                  {expanded
                    && (tx.legs || []).map((leg, index) => (
                      <tr key={`${tx.id}-leg-${index}`} data-testid={`split-leg-${tx.id}`}>
                        <td />
                        <td />
                        <td className="pl-8 text-base-content/70">{leg.account}</td>
                        <td className="money whitespace-nowrap text-base-content/70">
                          {Number(leg.debit) > 0 ? formatCurrency(leg.debit) : ''}
                        </td>
                        <td className="money whitespace-nowrap text-base-content/70">
                          {Number(leg.credit) > 0 ? formatCurrency(leg.credit) : ''}
                        </td>
                        <td />
                        <td />
                        <td />
                        <td />
                      </tr>
                    ))}
                </React.Fragment>
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
