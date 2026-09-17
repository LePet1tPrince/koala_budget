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
 */
const BudgetMonthPicker = ({ initialMonth }) => {
  const currentMonth = parseMonth(initialMonth);
  const [pickerYear, setPickerYear] = useState(currentMonth.getFullYear());

  const navigateToMonth = (date) => {
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
        buttonClassName="btn btn-ghost btn-sm text-lg font-bold"
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
