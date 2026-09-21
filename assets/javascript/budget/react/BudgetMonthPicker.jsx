import React, { useState } from 'react';
import { addMonths, format, isValid, parse, subMonths } from 'date-fns';

import PickerPopover, { MonthGrid } from '../../common/PickerPopover';

/**
 * Budget Month Picker - a compact month selector with prev/next arrows
 * and a dropdown grid for jumping to any month.
 *
 * Reads the current month from the `month` URL query parameter (YYYY-MM-DD)
 * and navigates by updating it.
 *
 * @param {Object} props
 * @param {string} props.initialMonth - Current month as YYYY-MM-DD string
 * @param {string} [props.triggerClassName] - Override for the month label button's classes
 * @param {function} [props.onNavigate] - Takes over from the full page load. Given
 *   the chosen Date, it is expected to bring the page to that month itself (the
 *   budget page swaps its content in place). Without it the picker navigates,
 *   which is still what the Goals and Monthly Review pages want.
 */
const BudgetMonthPicker = ({
  initialMonth,
  triggerClassName = 'btn btn-ghost btn-sm text-lg font-bold',
  onNavigate = null,
}) => {
  const currentMonth = parseMonth(initialMonth);
  const [pickerYear, setPickerYear] = useState(currentMonth.getFullYear());

  // The budget page keeps this controlled, so the selected month can now change
  // under a mounted picker. Follow it across a year boundary — otherwise
  // reopening the panel after jumping to another year shows the old one, with
  // nothing selected in it. (Adjusting state during render rather than in an
  // effect: React re-renders before painting, so the grid never shows the
  // stale year.)
  const [seenMonth, setSeenMonth] = useState(initialMonth);
  if (seenMonth !== initialMonth) {
    setSeenMonth(initialMonth);
    setPickerYear(currentMonth.getFullYear());
  }

  const navigateToMonth = (date) => {
    if (onNavigate) {
      onNavigate(date);
      return;
    }
    const url = new URL(window.location);
    url.searchParams.set('month', format(date, 'yyyy-MM-dd'));
    window.location.href = url.toString();
  };

  return (
    <div className="flex items-center gap-1">
      <button
        type="button"
        className="btn btn-ghost btn-sm btn-circle"
        onClick={() => navigateToMonth(subMonths(currentMonth, 1))}
        aria-label="Previous month"
      >
        ‹
      </button>

      <PickerPopover
        label={format(currentMonth, 'MMMM yyyy')}
        buttonClassName={triggerClassName}
        testId="budget-month-trigger"
        panelClassName="w-max"
      >
        {({ close }) => (
          <MonthGrid
            year={pickerYear}
            onYearChange={setPickerYear}
            selectedYear={currentMonth.getFullYear()}
            selectedMonth={currentMonth.getMonth()}
            onSelect={(year, monthIdx) => {
              close();
              navigateToMonth(new Date(year, monthIdx, 1));
            }}
          />
        )}
      </PickerPopover>

      <button
        type="button"
        className="btn btn-ghost btn-sm btn-circle"
        onClick={() => navigateToMonth(addMonths(currentMonth, 1))}
        aria-label="Next month"
      >
        ›
      </button>
    </div>
  );
};

function parseMonth(str) {
  const firstOfThisMonth = () => new Date(new Date().getFullYear(), new Date().getMonth(), 1);
  if (!str) return firstOfThisMonth();
  const date = parse(str, 'yyyy-MM-dd', new Date());
  return isValid(date) ? new Date(date.getFullYear(), date.getMonth(), 1) : firstOfThisMonth();
}

export default BudgetMonthPicker;
