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
  DayGrid,
  PickerActions,
  PresetList,
  RangeTabs,
} from './PickerPopover';

const safeParseISO = (dateString) => {
  if (!dateString) return null;
  const date = parseISO(dateString);
  return isValid(date) ? date : null;
};

const safeFormat = (date) => (date && isValid(date) ? format(date, 'yyyy-MM-dd') : '');

const formatDisplay = (value) => {
  const d = safeParseISO(value);
  return d ? format(d, 'MMM d, yyyy') : '';
};

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
  const [editing, setEditing] = useState('start');
  const [gridMonth, setGridMonth] = useState(startOfMonth(new Date()));

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

  const editedValue = editing === 'start' ? tempStart : tempEnd;
  const editedDate = safeParseISO(editedValue);

  // Show the month of whichever side is being edited. Keyed on the side and its
  // value so the month arrows are not fought: moving them does not change the
  // edited value, and picking a day sets a value in the month already shown.
  useEffect(() => {
    if (editedDate) setGridMonth(startOfMonth(editedDate));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editing, editedValue]);

  const handlePresetClick = (value) => {
    setActiveRange(value);
    const { start, end } = getPresetRange(value);
    setTempStart(safeFormat(start));
    setTempEnd(safeFormat(end));
    setEditing('start');
  };

  const handleDaySelect = (iso) => {
    setActiveRange('');
    if (editing === 'start') {
      setTempStart(iso);
      // Keep the range ordered, then move on to the end date.
      if (tempEnd && iso > tempEnd) setTempEnd(iso);
      setEditing('end');
    } else {
      setTempEnd(iso);
      if (tempStart && iso < tempStart) setTempStart(iso);
    }
  };

  const getDisplayText = () => {
    if (!startDate && !endDate) return 'Filter by Date';
    if (startDate && endDate) return `${formatDisplay(startDate)} – ${formatDisplay(endDate)}`;
    if (startDate) return `From ${formatDisplay(startDate)}`;
    return `Until ${formatDisplay(endDate)}`;
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
        <div className="flex flex-col gap-4 sm:flex-row sm:gap-5">
          <PresetList presets={presetRanges} active={activeRange} onSelect={handlePresetClick} />

          <div className="flex flex-col gap-3">
            <RangeTabs
              editing={editing}
              onEditingChange={setEditing}
              startLabel={formatDisplay(tempStart)}
              endLabel={formatDisplay(tempEnd)}
            />

            <DayGrid
              month={gridMonth}
              onMonthChange={setGridMonth}
              rangeStart={tempStart}
              rangeEnd={tempEnd}
              onSelect={handleDaySelect}
              testId="date-range-grid"
            />

            <PickerActions
              onCancel={() => {
                setTempStart(startDate || '');
                setTempEnd(endDate || '');
                setEditing('start');
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
