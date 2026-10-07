import React, { useCallback, useEffect, useId, useRef } from 'react';

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
