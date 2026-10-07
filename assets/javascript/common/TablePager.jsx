import React from 'react';

/* globals gettext */

/**
 * Pager for a client-side paginated table (the bank feed, the reconcile
 * workspace). `page` is zero-based; the owner clamps it.
 */
export const TablePager = ({ page, pageCount, pageSize, pageSizeOptions, total, onPageChange, onPageSizeChange }) => {
  const from = total === 0 ? 0 : page * pageSize + 1;
  const to = Math.min((page + 1) * pageSize, total);
  return (
    <div className="flex flex-wrap items-center justify-end gap-3 border-t border-base-300 px-2 py-2 text-sm">
      <label className="flex items-center gap-2">
        <span className="text-base-content/70">{gettext('Rows per page')}</span>
        <select
          className="select select-bordered select-xs w-[4.5rem]"
          value={pageSize}
          onChange={(e) => onPageSizeChange(Number(e.target.value))}
          data-testid="rows-per-page"
        >
          {pageSizeOptions.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      </label>

      <span className="tabular-nums text-base-content/70" data-testid="pager-range">
        {from}–{to} {gettext('of')} {total}
      </span>

      <div className="join">
        <button
          type="button"
          className="btn btn-ghost btn-xs join-item"
          disabled={page === 0}
          onClick={() => onPageChange(0)}
          aria-label={gettext('First page')}
        >
          «
        </button>
        <button
          type="button"
          className="btn btn-ghost btn-xs join-item"
          disabled={page === 0}
          onClick={() => onPageChange(page - 1)}
          aria-label={gettext('Previous page')}
        >
          ‹
        </button>
        <button
          type="button"
          className="btn btn-ghost btn-xs join-item"
          disabled={page >= pageCount - 1}
          onClick={() => onPageChange(page + 1)}
          aria-label={gettext('Next page')}
        >
          ›
        </button>
        <button
          type="button"
          className="btn btn-ghost btn-xs join-item"
          disabled={page >= pageCount - 1}
          onClick={() => onPageChange(pageCount - 1)}
          aria-label={gettext('Last page')}
        >
          »
        </button>
      </div>
    </div>
  );
};

/** Sort indicator on a column header. */
export const SortArrow = ({ active, direction }) => (
  <span
    className={`inline-block transition-transform ${active ? 'opacity-70' : 'opacity-0 group-hover:opacity-30'} ${
      active && direction === 'desc' ? 'rotate-180' : ''
    }`}
    aria-hidden="true"
  >
    ↑
  </span>
);
