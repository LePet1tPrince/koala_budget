import React, { useEffect, useState } from 'react';
import {
  endOfMonth,
  endOfYear,
  format,
  isValid,
  parseISO,
  startOfMonth,
  startOfYear,
  subDays,
  subMonths,
  subYears,
} from 'date-fns';

import PickerPopover, {
  CalendarIcon,
  DateField,
  PickerActions,
  PresetList,
} from './PickerPopover';

// 'yyyy-MM-dd' in, 'yyyy-MM-dd' out: the value format is also what `<input type="date">`
// speaks, so nothing has to be parsed to drive the fields — only the presets need dates.
const safeParseISO = (dateString) => {
  if (!dateString) return null;
  const date = parseISO(dateString);
  return isValid(date) ? date : null;
};

const safeFormat = (date) => (date && isValid(date) ? format(date, 'yyyy-MM-dd') : '');

const presetRanges = [
  { label: 'Last 7 days', value: 'last7days' },
  { label: 'Last 30 days', value: 'last30days' },
  { label: 'This month', value: 'thisMonth' },
  { label: 'Last month', value: 'lastMonth' },
  { label: 'This year', value: 'thisYear' },
  { label: 'Last year', value: 'lastYear' },
];

const getPresetRange = (value) => {
  const now = new Date();
  switch (value) {
    case 'last7days':
      return { start: subDays(now, 6), end: now };
    case 'last30days':
      return { start: subDays(now, 29), end: now };
    case 'thisMonth':
      return { start: startOfMonth(now), end: endOfMonth(now) };
    case 'lastMonth': {
      const d = subMonths(now, 1);
      return { start: startOfMonth(d), end: endOfMonth(d) };
    }
    case 'thisYear':
      return { start: startOfYear(now), end: endOfYear(now) };
    case 'lastYear': {
      const d = subYears(now, 1);
      return { start: startOfYear(d), end: endOfYear(d) };
    }
    default:
      return { start: null, end: null };
  }
};

const DateRangePicker = ({ startDate, endDate, onApply, preset }) => {
  const [tempStart, setTempStart] = useState(startDate || '');
  const [tempEnd, setTempEnd] = useState(endDate || '');
  const [activeRange, setActiveRange] = useState(preset || '');

  useEffect(() => {
    setTempStart(startDate || '');
    setTempEnd(endDate || '');
    setActiveRange(preset || '');
  }, [startDate, endDate, preset]);

  // A `preset` with no dates yet means "apply this range on mount".
  useEffect(() => {
    if (preset && !startDate && !endDate) {
      const { start, end } = getPresetRange(preset);
      if (start && end) {
        setTempStart(safeFormat(start));
        setTempEnd(safeFormat(end));
        onApply(safeFormat(start), safeFormat(end));
      }
    }
  }, [preset, startDate, endDate, onApply]);

  const handlePresetClick = (value) => {
    setActiveRange(value);
    const { start, end } = getPresetRange(value);
    setTempStart(safeFormat(start));
    setTempEnd(safeFormat(end));
  };

  const getDisplayText = () => {
    if (!startDate && !endDate) return 'Filter by Date';
    if (startDate && endDate) return `${startDate} – ${endDate}`;
    if (startDate) return `From ${startDate}`;
    return `Until ${endDate}`;
  };

  return (
    <PickerPopover
      label={getDisplayText()}
      icon={<CalendarIcon />}
      testId="date-range-picker-trigger"
      onClear={(startDate || endDate) ? () => onApply('', '') : null}
      panelClassName="w-max"
    >
      {({ close }) => (
        <div className="flex gap-3">
          <PresetList presets={presetRanges} active={activeRange} onSelect={handlePresetClick} />

          <div className="flex w-52 flex-col gap-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-base-content/70">
              Custom Range
            </p>
            <DateField
              label="Start date"
              value={tempStart}
              max={tempEnd}
              testId="date-range-start"
              onChange={(v) => {
                setTempStart(v);
                setActiveRange('');
              }}
            />
            <DateField
              label="End date"
              value={tempEnd}
              min={tempStart}
              testId="date-range-end"
              onChange={(v) => {
                setTempEnd(v);
                setActiveRange('');
              }}
            />
            <PickerActions
              onCancel={() => {
                setTempStart(startDate || '');
                setTempEnd(endDate || '');
                close();
              }}
              onApply={() => {
                onApply(tempStart, tempEnd);
                close();
              }}
            />
          </div>
        </div>
      )}
    </PickerPopover>
  );
};

export default DateRangePicker;
