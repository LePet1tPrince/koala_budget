import React, { useCallback, useEffect, useId, useRef, useState } from 'react';

/* globals gettext */

/**
 * Small daisyUI primitives the bank feed table is built from (restyle plan
 * Phase 5b), kept out of `LineTable.jsx` so that file stays about the table.
 */

/**
 * A controlled dropdown.
 *
 * Controlled rather than daisyUI's `dropdown`, which closes on blur: the quick
 * filters menu has to stay open while several checkboxes are toggled, and a
 * blur-driven close would dismiss it on the first click.
 */
export const Dropdown = ({ trigger, children, align = 'left', panelClassName = '', open, onOpenChange }) => {
  const rootRef = useRef(null);
  const panelId = useId();
  const close = useCallback(() => onOpenChange(false), [onOpenChange]);

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (e) => {
      if (rootRef.current && !rootRef.current.contains(e.target)) close();
    };
    const onKeyDown = (e) => {
      if (e.key === 'Escape') close();
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open, close]);

  return (
    <div className="relative inline-flex" ref={rootRef}>
      {trigger({ open, toggle: () => onOpenChange(!open), panelId })}
      {open && (
        <div
          id={panelId}
          role="menu"
          className={`absolute top-full z-50 mt-1 min-w-[15rem] rounded-xl border border-base-300 bg-base-100 p-1.5 shadow-lg ${
            align === 'right' ? 'right-0' : 'left-0'
          } ${panelClassName}`}
        >
          {children({ close })}
        </div>
      )}
    </div>
  );
};

/** A row in a `Dropdown`, optionally with a leading checkbox and a trailing count. */
export const MenuRow = ({ onClick, checked, label, count, countClass = '', disabled = false, testId, icon }) => (
  <button
    type="button"
    role="menuitem"
    disabled={disabled}
    onClick={onClick}
    data-testid={testId}
    className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition-colors hover:bg-base-200 disabled:cursor-not-allowed disabled:opacity-50"
  >
    {checked !== undefined && (
      <input
        type="checkbox"
        className="checkbox checkbox-xs rounded-sm pointer-events-none"
        checked={checked}
        readOnly
        tabIndex={-1}
      />
    )}
    {icon}
    <span className="flex-1">{label}</span>
    {count !== undefined && <span className={`badge badge-sm ${countClass}`}>{count}</span>}
  </button>
);

/** Transient message strip, replacing MUI's Snackbar + Alert. */
export const Toast = ({ open, message, severity = 'info', onClose, autoHideMs = 4000 }) => {
  useEffect(() => {
    if (!open) return undefined;
    const t = setTimeout(onClose, autoHideMs);
    return () => clearTimeout(t);
  }, [open, onClose, autoHideMs]);

  if (!open) return null;
  const cls = { success: 'alert-success', error: 'alert-error', warning: 'alert-warning', info: 'alert-info' }[severity];
  return (
    <div className="toast toast-end z-50" data-testid="feed-toast">
      <div className={`alert ${cls}`}>
        <span>{message}</span>
        <button type="button" className="btn btn-ghost btn-xs" onClick={onClose} aria-label={gettext('Dismiss')}>
          ✕
        </button>
      </div>
    </div>
  );
};

/**
 * Pager for the table.
 *
 * `@material-table/core` supplied this; the page size options and default of 10
 * are carried over unchanged so the table paginates exactly as it did.
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

/** Open/closed padlock for the Reconciled column. */
export const ReconciledLock = ({ reconciled }) => {
  const title = reconciled ? gettext('Reconciled') : gettext('Not yet reconciled');
  // Class names must be full literals, otherwise Tailwind's compiler
  // can't see them and strips them from the build.
  const colorClasses = reconciled ? 'bg-success/15 text-success' : 'bg-base-200 text-base-content/40';
  return (
    <span
      title={title}
      aria-label={title}
      className={`inline-flex h-6 w-6 items-center justify-center rounded-full ${colorClasses}`}
    >
      <svg className="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
        {reconciled ? (
          <path d="M10 2a4 4 0 0 0-4 4v2H5.5A1.5 1.5 0 0 0 4 9.5v7A1.5 1.5 0 0 0 5.5 18h9a1.5 1.5 0 0 0 1.5-1.5v-7A1.5 1.5 0 0 0 14.5 8H14V6a4 4 0 0 0-4-4Zm2.5 6h-5V6a2.5 2.5 0 0 1 5 0v2Z" />
        ) : (
          <path d="M10 2a4 4 0 0 0-4 4 .75.75 0 0 0 1.5 0 2.5 2.5 0 0 1 5 0v2H5.5A1.5 1.5 0 0 0 4 9.5v7A1.5 1.5 0 0 0 5.5 18h9a1.5 1.5 0 0 0 1.5-1.5v-7A1.5 1.5 0 0 0 14.5 8H14V6a4 4 0 0 0-4-4Z" />
        )}
      </svg>
    </span>
  );
};
