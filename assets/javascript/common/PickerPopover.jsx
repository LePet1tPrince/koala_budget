import React, { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import {
  addMonths,
  eachDayOfInterval,
  endOfMonth,
  endOfWeek,
  format,
  isSameDay,
  isSameMonth,
  isValid,
  isWithinInterval,
  parseISO,
  startOfMonth,
  startOfWeek,
  subMonths,
} from 'date-fns';

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
          className={`absolute z-50 mt-2 max-w-[calc(100vw-1rem)] overflow-x-auto rounded-2xl border border-base-300 bg-base-100 p-5 shadow-xl ${
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

/** Small caps heading used above each column of the panel. */
export const PanelHeading = ({ children }) => (
  <p className="mb-2 px-1 text-[0.68rem] font-semibold uppercase tracking-[0.08em] text-base-content/60">
    {children}
  </p>
);

/**
 * The presets column shared by the range pickers.
 *
 * Hand-rolled rather than daisyUI's `menu`, whose `menu-sm` padding is too tight
 * to read as a row and whose `active` state is a full-contrast slab.
 */
export const PresetList = ({ presets, active, onSelect, title = 'Presets' }) => (
  <div className="w-full border-b border-base-300 pb-3 sm:w-auto sm:min-w-[10.5rem] sm:border-b-0 sm:border-r sm:pb-0 sm:pr-5">
    <PanelHeading>{title}</PanelHeading>
    <ul className="flex flex-wrap gap-1.5 sm:flex-col sm:gap-0.5">
      {presets.map((p) => (
        <li key={p.value}>
          <button
            type="button"
            className={`rounded-lg px-3 py-2 text-sm transition-colors sm:w-full sm:text-left ${
              active === p.value
                ? 'bg-primary/10 font-medium text-primary'
                : 'border border-base-300 hover:bg-base-200 sm:border-0'
            }`}
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
  <div className="mt-2 flex justify-end gap-2 border-t border-base-300 pt-4">
    <button type="button" className="btn btn-ghost btn-sm rounded-lg" onClick={onCancel}>
      Cancel
    </button>
    <button type="button" className="btn btn-primary btn-sm rounded-lg px-5" onClick={onApply}>
      {applyLabel}
    </button>
  </div>
);

/** Chevron for the year stepper — an inline SVG keeps the icon set to one. */
const Chevron = ({ dir }) => (
  <svg className="h-4 w-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d={dir === 'left' ? 'M12.5 4.5 7 10l5.5 5.5' : 'M7.5 4.5 13 10l-5.5 5.5'}
    />
  </svg>
);

/**
 * A year header with prev/next arrows over a 12-month grid. Used wherever a month
 * is selected: `<input type="month">` is not supported in Firefox, so a grid is
 * the portable option — and it is one click rather than MUI's year→month drill-down.
 */
export const MonthGrid = ({ year, onYearChange, selectedYear, selectedMonth, onSelect }) => {
  const now = new Date();
  return (
    <div className="w-[17rem]">
      <div className="mb-2 flex items-center justify-between">
        <button
          type="button"
          className="grid h-8 w-8 place-items-center rounded-full text-base-content/70 transition-colors hover:bg-base-200 hover:text-base-content"
          onClick={() => onYearChange(year - 1)}
          aria-label="Previous year"
        >
          <Chevron dir="left" />
        </button>
        <span className="text-sm font-semibold tabular-nums">{year}</span>
        <button
          type="button"
          className="grid h-8 w-8 place-items-center rounded-full text-base-content/70 transition-colors hover:bg-base-200 hover:text-base-content"
          onClick={() => onYearChange(year + 1)}
          aria-label="Next year"
        >
          <Chevron dir="right" />
        </button>
      </div>
      <div className="grid grid-cols-4 gap-1.5">
        {MONTH_LABELS.map((label, idx) => {
          const isSelected = idx === selectedMonth && year === selectedYear;
          // Ring the current month so "now" is findable without being selected.
          const isCurrent = idx === now.getMonth() && year === now.getFullYear();
          return (
            <button
              key={label}
              type="button"
              className={`rounded-lg px-2 py-2.5 text-sm transition-colors ${
                isSelected
                  ? 'bg-primary font-semibold text-primary-content'
                  : `hover:bg-base-200 ${isCurrent ? 'ring-1 ring-inset ring-primary/40' : ''}`
              }`}
              onClick={() => onSelect(year, idx)}
            >
              {label}
            </button>
          );
        })}
      </div>
    </div>
  );
};

export const MONTH_LABELS = [
  'Jan', 'Feb', 'Mar', 'Apr',
  'May', 'Jun', 'Jul', 'Aug',
  'Sep', 'Oct', 'Nov', 'Dec',
];

const DAY_LABELS = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'];

/** 'yyyy-MM-dd' <-> Date, the format the pickers pass around. */
const toISO = (date) => format(date, 'yyyy-MM-dd');
const fromISO = (value) => {
  if (!value) return null;
  const d = parseISO(value);
  return isValid(d) ? d : null;
};

/**
 * A month of days, drawn by us.
 *
 * The first cut of this phase used `<input type="date">` and let the browser
 * supply the calendar. That is not themeable: Chrome's popup brings its own
 * squared corners, its own cramped cells and its own blue, none of which CSS can
 * reach, and it cannot show a range at all. So the grid is ours, matching
 * `MonthGrid` — cells are real hit targets, the selected range is tinted across
 * the span, and today is ringed rather than filled.
 *
 * @param {string} value      Selected day, 'yyyy-MM-dd'.
 * @param {string} rangeStart Range to tint across; omit for a single-date grid.
 * @param {string} rangeEnd
 */
export const DayGrid = ({ month, onMonthChange, value, rangeStart, rangeEnd, onSelect, testId }) => {
  const selected = fromISO(value);
  const start = fromISO(rangeStart);
  const end = fromISO(rangeEnd);
  const today = new Date();

  const days = eachDayOfInterval({
    start: startOfWeek(startOfMonth(month)),
    end: endOfWeek(endOfMonth(month)),
  });

  return (
    <div className="w-[17.5rem]" data-testid={testId}>
      <div className="mb-2 flex items-center justify-between">
        <button
          type="button"
          className="grid h-8 w-8 place-items-center rounded-full text-base-content/70 transition-colors hover:bg-base-200 hover:text-base-content"
          onClick={() => onMonthChange(subMonths(month, 1))}
          aria-label="Previous month"
        >
          <Chevron dir="left" />
        </button>
        <span className="text-sm font-semibold">{format(month, 'MMMM yyyy')}</span>
        <button
          type="button"
          className="grid h-8 w-8 place-items-center rounded-full text-base-content/70 transition-colors hover:bg-base-200 hover:text-base-content"
          onClick={() => onMonthChange(addMonths(month, 1))}
          aria-label="Next month"
        >
          <Chevron dir="right" />
        </button>
      </div>

      <div className="grid grid-cols-7 gap-y-1">
        {DAY_LABELS.map((d) => (
          <div key={d} className="pb-1 text-center text-[0.68rem] font-semibold text-base-content/50">
            {d}
          </div>
        ))}

        {days.map((day) => {
          const outside = !isSameMonth(day, month);
          const isSelected =
            (selected && isSameDay(day, selected)) ||
            (start && isSameDay(day, start)) ||
            (end && isSameDay(day, end));
          const inRange =
            start && end && !isSelected && isWithinInterval(day, { start, end });
          const isToday = isSameDay(day, today);

          // The span tint is a full-width block so adjacent days join up. Only the
          // ends of each week round off, so a run reads as one band rather than a
          // row of butted squares; the selected days sit on top with their own shape.
          const weekday = day.getDay();
          let cls = 'relative mx-auto grid h-9 w-9 place-items-center text-sm transition-colors ';
          if (isSelected) {
            cls += 'rounded-lg bg-primary font-semibold text-primary-content';
          } else if (inRange) {
            cls += `bg-primary/10 text-base-content ${
              weekday === 0 ? 'rounded-l-lg' : ''
            } ${weekday === 6 ? 'rounded-r-lg' : ''}`;
          } else {
            cls += `rounded-lg hover:bg-base-200 ${outside ? 'text-base-content/30' : ''} ${
              isToday ? 'ring-1 ring-inset ring-primary/40' : ''
            }`;
          }

          return (
            <button
              key={toISO(day)}
              type="button"
              className={cls}
              aria-current={isToday ? 'date' : undefined}
              onClick={() => onSelect(toISO(day))}
            >
              {day.getDate()}
            </button>
          );
        })}
      </div>
    </div>
  );
};

/**
 * The Start/End switch shared by the range pickers: a segmented control that also
 * shows each side's current value, so the panel needs no separate readout.
 */
export const RangeTabs = ({ editing, onEditingChange, startLabel, endLabel }) => (
  <div role="tablist" className="grid grid-cols-2 gap-1 rounded-xl bg-base-200 p-1">
    {[['start', 'Start', startLabel], ['end', 'End', endLabel]].map(([side, label, display]) => (
      <button
        key={side}
        type="button"
        role="tab"
        aria-selected={editing === side}
        className={`rounded-lg px-3 py-1.5 text-center transition-colors ${
          editing === side ? 'bg-base-100 shadow-sm' : 'hover:bg-base-100/60'
        }`}
        onClick={() => onEditingChange(side)}
      >
        <span className="block text-[0.65rem] uppercase tracking-[0.08em] text-base-content/60">
          {label}
        </span>
        <span className="block text-sm font-semibold tabular-nums">{display || '—'}</span>
      </button>
    ))}
  </div>
);

/** Calendar glyph for the trigger buttons, so no icon font or MUI icon is needed. */
export const CalendarIcon = () => (
  <svg className="h-4 w-4 shrink-0" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
    <path d="M5.75 2a.75.75 0 0 1 .75.75V4h7V2.75a.75.75 0 0 1 1.5 0V4h.25A2.75 2.75 0 0 1 18 6.75v8.5A2.75 2.75 0 0 1 15.25 18H4.75A2.75 2.75 0 0 1 2 15.25v-8.5A2.75 2.75 0 0 1 4.75 4H5V2.75A.75.75 0 0 1 5.75 2ZM3.5 8v7.25c0 .69.56 1.25 1.25 1.25h10.5c.69 0 1.25-.56 1.25-1.25V8h-13Z" />
  </svg>
);

export default PickerPopover;
