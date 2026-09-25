import React, { useCallback, useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
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

import { portalTarget, useAnchoredPosition } from './popoverPosition';

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
 * @param {string}   testId       data-testid for the trigger button.
 * @param {boolean}  disabled     Disables the trigger, so it cannot be opened by
 *                                click *or* by keyboard — which is why this is a
 *                                real prop rather than `pointer-events-none`.
 * @param {function} children     Render prop; receives `{ close }`.
 */
const PickerPopover = ({
  label,
  icon = null,
  onClear = null,
  onOpen = null,
  testId,
  disabled = false,
  buttonClassName = 'btn btn-outline btn-sm font-normal',
  panelClassName = '',
  children,
}) => {
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);
  const panelRef = useRef(null);
  const panelId = useId();

  const close = useCallback(() => setOpen(false), []);

  const { style: panelStyle } = useAnchoredPosition(open, rootRef, panelRef);

  // Close on an outside press or Escape. `pointerdown` rather than `click` so a
  // press that starts outside dismisses immediately, matching native menus.
  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (e) => {
      // The panel is portaled out of the trigger (see popoverPosition.js), so it
      // is not a DOM descendant of `rootRef` and has to be tested separately.
      // Testing the trigger alone reported every press *inside* the panel as an
      // outside press, closing it on `pointerdown` — so the panel unmounted
      // before the `click` on the month or day being aimed at could land, and
      // picking a value silently did nothing.
      // A Combobox inside the panel portals its list out of the panel as well.
      const inside =
        rootRef.current?.contains(e.target) ||
        panelRef.current?.contains(e.target) ||
        e.target.closest?.('[data-combobox]');
      if (!inside) close();
    };
    const onKeyDown = (e) => {
      if (e.key !== 'Escape') return;
      // `DateField` puts this panel inside a native <dialog>, which closes on
      // Escape as a default action of the keydown rather than by propagation.
      // Without preventDefault the modal would close along with the panel.
      e.preventDefault();
      close();
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
        className={`${buttonClassName} ${disabled ? 'cursor-not-allowed opacity-60' : ''}`}
        disabled={disabled}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        onClick={() => {
          setOpen((v) => {
            // `onOpen` lets a caller load the panel's contents lazily — the budget
            // page's transaction list is fetched the first time it is shown.
            if (!v) onOpen?.();
            return !v;
          });
        }}
        data-testid={testId}
      >
        {icon}
        <span className="truncate">{label}</span>
        {onClear && !disabled && (
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

      {open &&
        createPortal(
          <div
            id={panelId}
            ref={panelRef}
            role="dialog"
            className={`fixed z-[1200] max-w-[calc(100vw-1rem)] overflow-auto rounded-2xl border border-base-300 bg-base-100 p-5 shadow-xl ${panelClassName}`}
            style={
              panelStyle
                ? { top: panelStyle.top, left: panelStyle.left, maxHeight: panelStyle.maxHeight }
                : // Measured on first paint, so stay invisible until placed.
                  { top: 0, left: 0, visibility: 'hidden' }
            }
          >
            {children({ close })}
          </div>,
          portalTarget(rootRef.current)
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

/** A round hover target for the prev/next steppers. */
const StepButton = ({ onClick, label, dir }) => (
  <button
    type="button"
    className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-base-content/70 transition-colors hover:bg-base-200 hover:text-base-content"
    onClick={onClick}
    aria-label={label}
  >
    <Chevron dir={dir} />
  </button>
);

/** Downward caret marking a header label as openable. */
const Caret = () => (
  <svg className="h-3 w-3 opacity-60" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
    <path d="M5.22 7.22a.75.75 0 0 1 1.06 0L10 10.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 8.28a.75.75 0 0 1 0-1.06Z" />
  </svg>
);

/**
 * A menu that drops out of a calendar header label.
 *
 * It lives inside the picker panel, so `PickerPopover`'s outside-press handler
 * treats it as inside and leaves the panel alone. Its backdrop is part of the
 * panel too, so any press while the menu is open dismisses just the menu and
 * leaves the picker where it was.
 */
const HeaderMenu = ({ open, onClose, label, children, width = 'w-[15rem]' }) => {
  // Escape should dismiss this menu, not the whole picker. A capture-phase
  // listener runs before `PickerPopover`'s bubble-phase one, so stopping
  // propagation here keeps the panel open; preventDefault additionally stops a
  // surrounding <dialog> from closing, which it does as a keydown default action.
  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        onClose();
      }
    };
    document.addEventListener('keydown', onKeyDown, true);
    return () => document.removeEventListener('keydown', onKeyDown, true);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <>
      <div className="fixed inset-0 z-10" onPointerDown={onClose} aria-hidden="true" />
      <div
        role="listbox"
        aria-label={label}
        className={`absolute left-1/2 top-full z-20 mt-1 -translate-x-1/2 rounded-xl border border-base-300 bg-base-100 p-2 shadow-lg ${width}`}
      >
        {children}
      </div>
    </>
  );
};

/** A calendar header label that opens a menu. */
const HeaderLabel = ({ open, onToggle, children, testId }) => (
  <button
    type="button"
    className={`flex items-center gap-1 rounded-lg px-2 py-1 text-sm font-semibold transition-colors hover:bg-base-200 ${
      open ? 'bg-base-200' : ''
    }`}
    aria-haspopup="listbox"
    aria-expanded={open}
    onClick={onToggle}
    data-testid={testId}
  >
    {children}
    <Caret />
  </button>
);

/** Cell shared by the month and year menus. */
const MenuCell = ({ selected, onClick, children }) => (
  <button
    type="button"
    role="option"
    aria-selected={selected}
    className={`rounded-lg px-2 py-2 text-sm transition-colors ${
      selected ? 'bg-primary font-semibold text-primary-content' : 'hover:bg-base-200'
    }`}
    onClick={onClick}
  >
    {children}
  </button>
);

/** Twelve years at a time, paged so any year is a few clicks away. */
const YearMenu = ({ year, onSelect, onClose }) => {
  const [pageStart, setPageStart] = useState(Math.floor(year / 12) * 12);
  const years = Array.from({ length: 12 }, (_, i) => pageStart + i);
  return (
    <>
      <div className="mb-1 flex items-center justify-between">
        <StepButton dir="left" label="Earlier years" onClick={() => setPageStart((y) => y - 12)} />
        <span className="text-xs font-semibold tabular-nums">
          {years[0]} – {years[11]}
        </span>
        <StepButton dir="right" label="Later years" onClick={() => setPageStart((y) => y + 12)} />
      </div>
      <div className="grid grid-cols-3 gap-1">
        {years.map((y) => (
          <MenuCell
            key={y}
            selected={y === year}
            onClick={() => {
              onSelect(y);
              onClose();
            }}
          >
            {y}
          </MenuCell>
        ))}
      </div>
    </>
  );
};

/** The twelve months of the displayed year. */
const MonthMenu = ({ monthIndex, onSelect, onClose }) => (
  <div className="grid grid-cols-3 gap-1">
    {MONTH_LABELS.map((label, idx) => (
      <MenuCell
        key={label}
        selected={idx === monthIndex}
        onClick={() => {
          onSelect(idx);
          onClose();
        }}
      >
        {label}
      </MenuCell>
    ))}
  </div>
);

/**
 * A year header with prev/next arrows over a 12-month grid. Used wherever a month
 * is selected: `<input type="month">` is not supported in Firefox, so a grid is
 * the portable option — and it is one click rather than MUI's year→month drill-down.
 */
export const MonthGrid = ({ year, onYearChange, selectedYear, selectedMonth, onSelect }) => {
  const [yearMenu, setYearMenu] = useState(false);
  const closeYearMenu = useCallback(() => setYearMenu(false), []);
  const now = new Date();
  return (
    <div className="w-[17rem]">
      <div className="mb-2 flex items-center justify-between">
        <StepButton dir="left" label="Previous year" onClick={() => onYearChange(year - 1)} />

        {/* Same jump-to affordance as the day calendar's year label. */}
        <div className="relative">
          <HeaderLabel
            open={yearMenu}
            onToggle={() => setYearMenu((v) => !v)}
            testId="cal-year-label"
          >
            <span className="tabular-nums">{year}</span>
          </HeaderLabel>
          <HeaderMenu open={yearMenu} onClose={closeYearMenu} label="Select year">
            <YearMenu year={year} onSelect={onYearChange} onClose={closeYearMenu} />
          </HeaderMenu>
        </div>

        <StepButton dir="right" label="Next year" onClick={() => onYearChange(year + 1)} />
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
  const [menu, setMenu] = useState(null); // 'month' | 'year' | null
  const closeMenu = useCallback(() => setMenu(null), []);
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
        <StepButton dir="left" label="Previous month" onClick={() => onMonthChange(subMonths(month, 1))} />

        {/* Month and year are each their own jump target, so moving a year back
            is one click rather than twelve presses of the arrow. Each menu is
            positioned by its own label's wrapper so it drops from what was clicked. */}
        <div className="flex items-center gap-1">
          <div className="relative">
            <HeaderLabel
              open={menu === 'month'}
              onToggle={() => setMenu((m) => (m === 'month' ? null : 'month'))}
              testId="cal-month-label"
            >
              {format(month, 'MMMM')}
            </HeaderLabel>
            <HeaderMenu open={menu === 'month'} onClose={closeMenu} label="Select month">
              <MonthMenu
                monthIndex={month.getMonth()}
                onSelect={(idx) => onMonthChange(new Date(month.getFullYear(), idx, 1))}
                onClose={closeMenu}
              />
            </HeaderMenu>
          </div>

          <div className="relative">
            <HeaderLabel
              open={menu === 'year'}
              onToggle={() => setMenu((m) => (m === 'year' ? null : 'year'))}
              testId="cal-year-label"
            >
              <span className="tabular-nums">{format(month, 'yyyy')}</span>
            </HeaderLabel>
            <HeaderMenu open={menu === 'year'} onClose={closeMenu} label="Select year">
              <YearMenu
                year={month.getFullYear()}
                onSelect={(y) => onMonthChange(new Date(y, month.getMonth(), 1))}
                onClose={closeMenu}
              />
            </HeaderMenu>
          </div>
        </div>

        <StepButton dir="right" label="Next month" onClick={() => onMonthChange(addMonths(month, 1))} />
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
