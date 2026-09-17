import React, { useEffect, useState } from 'react';
import { format, parseISO, startOfMonth } from 'date-fns';

import PickerPopover, { CalendarIcon, DayGrid } from './PickerPopover';

/* globals gettext */

/**
 * A single-date form field (restyle plan Phase 7).
 *
 * Replaces MUI's `DatePicker` + `LocalizationProvider` + `AdapterDateFns`, which
 * were the last use of `@mui/x-date-pickers`. The calendar itself is the same
 * `DayGrid` the range pickers use, so every date surface in the app is now one
 * component rather than two that look different.
 *
 * `value` and `onChange` speak ISO `yyyy-MM-dd` — the format the API takes and the
 * one the old `type="date"` inputs produced, so callers are unchanged.
 */
const DateField = ({ label, value, onChange, testId, allowClear = false, className = '' }) => {
  const parsed = value ? parseISO(value) : null;
  const valid = parsed && !Number.isNaN(parsed.getTime());
  const [month, setMonth] = useState(() => startOfMonth(valid ? parsed : new Date()));

  // Follow an externally-set value (the reconcile dialog defaults the date from
  // the selection) rather than staying on whatever month was last browsed.
  useEffect(() => {
    if (valid) setMonth(startOfMonth(parsed));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  return (
    <label className={`form-control w-full ${className}`}>
      {label && <span className="label-text mb-1 block text-sm text-base-content/70">{label}</span>}
      <PickerPopover
        label={valid ? format(parsed, 'MMM d, yyyy') : gettext('Select a date')}
        icon={<CalendarIcon />}
        testId={testId}
        onClear={allowClear && value ? () => onChange('') : null}
        buttonClassName="input input-bordered flex w-full items-center gap-2 font-normal justify-start"
      >
        {({ close }) => (
          <DayGrid
            month={month}
            onMonthChange={setMonth}
            value={value}
            onSelect={(iso) => {
              onChange(iso);
              close();
            }}
            testId={testId ? `${testId}-grid` : undefined}
          />
        )}
      </PickerPopover>
    </label>
  );
};

export default DateField;
