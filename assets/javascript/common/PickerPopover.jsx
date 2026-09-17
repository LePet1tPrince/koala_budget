import React, { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';

/** Keep this much clear of the viewport edge when clamping the panel. */
const GUTTER = 8;

/**
 * The shell every date/month picker in the app is built from (restyle plan Phase 5).
 *
 * All of them are the same shape: a trigger button showing the current selection,
 * with an optional clear affordance, opening a panel that holds presets and fields
 * plus Cancel/Apply. That was previously five separate MUI `Popover` + `Button`
 * assemblies; it is now this one component and daisyUI classes.
 *
 * Open state is controlled rather than delegated to daisyUI's `dropdown` (which
 * closes on blur): a blur-driven close fires before a click inside the panel
 * lands, so "Apply" would dismiss the panel without ever running its handler.
 *
 * @param {string}   label        Text on the trigger button.
 * @param {node}     icon         Optional leading icon.
 * @param {function} onClear      When set, a ✕ appears on the trigger. Clearing
 *                                does not open the panel.
 * @param {string}   align        Panel edge to align to the trigger: 'left' | 'right'.
 * @param {string}   testId       data-testid for the trigger button.
 * @param {function} children     Render prop; receives `{ close }`.
 */
const PickerPopover = ({
  label,
  icon = null,
  onClear = null,
  align = 'left',
  testId,
  buttonClassName = 'btn btn-outline btn-sm font-normal',
  panelClassName = '',
  children,
}) => {
  const [open, setOpen] = useState(false);
  const [offset, setOffset] = useState(0);
  const rootRef = useRef(null);
  const panelRef = useRef(null);
  const panelId = useId();

  const close = useCallback(() => setOpen(false), []);

  // These triggers sit at the right end of a page header, so a panel anchored to
  // the trigger runs off the viewport — the month grid was being cut in half at
  // desktop width, and flipping it to `right-0` only moved the overflow to the
  // left edge on a phone. So measure on open and clamp into the viewport, which
  // handles both edges and needs no positioning library.
  useLayoutEffect(() => {
    if (!open) {
      setOffset(0);
      return;
    }
    const panel = panelRef.current;
    if (!panel) return;
    const rect = panel.getBoundingClientRect();
    const overflowRight = rect.right - (window.innerWidth - GUTTER);
    let dx = overflowRight > 0 ? -overflowRight : 0;
    if (rect.left + dx < GUTTER) dx = GUTTER - rect.left;
    setOffset(dx);
  }, [open]);

  // Close on an outside press or Escape. `pointerdown` rather than `click` so a
  // press that starts outside dismisses immediately, matching native menus.
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

  const handleClear = (e) => {
    e.stopPropagation();
    close();
    onClear();
  };

  return (
    <div className="relative inline-block" ref={rootRef}>
      <button
        type="button"
        className={buttonClassName}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        onClick={() => setOpen((v) => !v)}
        data-testid={testId}
      >
        {icon}
        <span className="truncate">{label}</span>
        {onClear && (
          // A <button> may not nest inside a <button>, so this is a span with a role.
          <span
            role="button"
            tabIndex={0}
            aria-label="Clear"
            className="ml-1 -mr-1 inline-flex items-center rounded-full p-0.5 hover:bg-base-300"
            onClick={handleClear}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') handleClear(e);
            }}
          >
            <svg className="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
              <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
            </svg>
          </span>
        )}
      </button>

      {open && (
        <div
          id={panelId}
          ref={panelRef}
          role="dialog"
          className={`absolute z-50 mt-1 max-w-[calc(100vw-1rem)] overflow-x-auto rounded-box border border-base-300 bg-base-100 p-4 shadow-lg ${
            align === 'right' ? 'right-0' : 'left-0'
          } ${panelClassName}`}
          style={offset ? { transform: `translateX(${offset}px)` } : undefined}
        >
          {children({ close })}
        </div>
      )}
    </div>
  );
};

/**
 * The presets column shared by the range pickers.
 */
export const PresetList = ({ presets, active, onSelect, title = 'Presets' }) => (
  <div className="min-w-[9.5rem] border-r border-base-300 pr-3">
    <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-base-content/70">{title}</p>
    <ul className="menu menu-sm w-full p-0">
      {presets.map((p) => (
        <li key={p.value}>
          <button
            type="button"
            className={active === p.value ? 'active' : ''}
            onClick={() => onSelect(p.value)}
          >
            {p.label}
          </button>
        </li>
      ))}
    </ul>
  </div>
);

/**
 * The Cancel/Apply pair shared by the range pickers.
 */
export const PickerActions = ({ onCancel, onApply, applyLabel = 'Apply' }) => (
  <div className="mt-1 flex justify-end gap-2 border-t border-base-300 pt-3">
    <button type="button" className="btn btn-ghost btn-sm" onClick={onCancel}>
      Cancel
    </button>
    <button type="button" className="btn btn-primary btn-sm" onClick={onApply}>
      {applyLabel}
    </button>
  </div>
);

/**
 * A year header with prev/next arrows over a 12-month grid. Used wherever a month
 * is selected: `<input type="month">` is not supported in Firefox, so a grid is
 * the portable option — and it is one click rather than MUI's year→month drill-down.
 */
export const MonthGrid = ({ year, onYearChange, selectedYear, selectedMonth, onSelect }) => (
  <div className="w-[15rem]">
    <div className="mb-2 flex items-center justify-between">
      <button
        type="button"
        className="btn btn-ghost btn-xs"
        onClick={() => onYearChange(year - 1)}
        aria-label="Previous year"
      >
        ‹
      </button>
      <span className="text-sm font-semibold">{year}</span>
      <button
        type="button"
        className="btn btn-ghost btn-xs"
        onClick={() => onYearChange(year + 1)}
        aria-label="Next year"
      >
        ›
      </button>
    </div>
    <div className="grid grid-cols-4 gap-1">
      {MONTH_LABELS.map((label, idx) => {
        const isSelected = idx === selectedMonth && year === selectedYear;
        return (
          <button
            key={label}
            type="button"
            className={`btn btn-xs ${isSelected ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => onSelect(year, idx)}
          >
            {label}
          </button>
        );
      })}
    </div>
  </div>
);

export const MONTH_LABELS = [
  'Jan', 'Feb', 'Mar', 'Apr',
  'May', 'Jun', 'Jul', 'Aug',
  'Sep', 'Oct', 'Nov', 'Dec',
];

/**
 * A labelled native date field. `<input type="date">` is supported everywhere and
 * brings the platform's own calendar, so it replaces MUI's `DatePicker` outright;
 * the theme's `color-scheme` makes the browser's calendar icon follow dark mode.
 */
export const DateField = ({ label, value, onChange, min, max, testId }) => (
  <label className="form-control w-full">
    <span className="mb-1 block text-xs font-medium text-base-content/70">{label}</span>
    <input
      type="date"
      className="input input-bordered input-sm w-full"
      value={value || ''}
      min={min || undefined}
      max={max || undefined}
      onChange={(e) => onChange(e.target.value)}
      data-testid={testId}
    />
  </label>
);

/** Calendar glyph for the trigger buttons, so no icon font or MUI icon is needed. */
export const CalendarIcon = () => (
  <svg className="h-4 w-4 shrink-0" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
    <path d="M5.75 2a.75.75 0 0 1 .75.75V4h7V2.75a.75.75 0 0 1 1.5 0V4h.25A2.75 2.75 0 0 1 18 6.75v8.5A2.75 2.75 0 0 1 15.25 18H4.75A2.75 2.75 0 0 1 2 15.25v-8.5A2.75 2.75 0 0 1 4.75 4H5V2.75A.75.75 0 0 1 5.75 2ZM3.5 8v7.25c0 .69.56 1.25 1.25 1.25h10.5c.69 0 1.25-.56 1.25-1.25V8h-13Z" />
  </svg>
);

export default PickerPopover;
