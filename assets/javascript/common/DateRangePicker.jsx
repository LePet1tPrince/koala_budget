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

import DateTextInput from './DateTextInput';
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
  { label: 'Last 3 months', value: 'last3Months' },
  { label: 'Last 6 months', value: 'last6Months' },
  { label: 'Last 12 months', value: 'last12Months' },
  { label: 'This year', value: 'thisYear' },
  { label: 'Last year', value: 'lastYear' },
  { label: 'All time', value: 'allTime' },
];

// `allTimeStart` (yyyy-MM-dd) bounds "All time" for pages that need a concrete
// range; without it "All time" means no date filter at all.
const getPresetRange = (value, allTimeStart) => {
  const now = new Date();
  switch (value) {
    case 'last7days':
      return { start: subDays(now, 6), end: now };
    case 'last30days':
      return { start: subDays(now, 29), end: now };
    case 'thisMonth':
      return { start: startOfMonth(now), end: endOfMonth(now) };
    case 'lastMonth':
    case 'last3Months':
    case 'last6Months':
    case 'last12Months': {
      // Full months before this one -- the same ranges as a book's default
      // report timeframe (apps/reports/timeframes.py).
      const months = { lastMonth: 1, last3Months: 3, last6Months: 6, last12Months: 12 }[value];
      return { start: startOfMonth(subMonths(now, months)), end: endOfMonth(subMonths(now, 1)) };
    }
    case 'thisYear':
      return { start: startOfYear(now), end: endOfYear(now) };
    case 'lastYear': {
      const d = subYears(now, 1);
      return { start: startOfYear(d), end: endOfYear(d) };
    }
    case 'allTime': {
      const start = safeParseISO(allTimeStart);
      return start ? { start, end: now } : { start: null, end: null };
    }
    default:
      return { start: null, end: null };
  }
};

// The preset a range is, if any -- so a report opened on the book's default
// timeframe shows "Last 3 months" ticked rather than a bare pair of dates.
const presetFor = (start, end, allTimeStart) =>
  presetRanges.find(({ value }) => {
    const range = getPresetRange(value, allTimeStart);
    return safeFormat(range.start) === (start || '') && safeFormat(range.end) === (end || '');
  })?.value || '';

const DateRangePicker = ({ startDate, endDate, onApply, preset, allTimeStart }) => {
  const [tempStart, setTempStart] = useState(startDate || '');
  const [tempEnd, setTempEnd] = useState(endDate || '');
  const [activeRange, setActiveRange] = useState(preset || presetFor(startDate, endDate, allTimeStart));
  const [editing, setEditing] = useState('start');
  const [gridMonth, setGridMonth] = useState(startOfMonth(new Date()));

  useEffect(() => {
    setTempStart(startDate || '');
    setTempEnd(endDate || '');
    setActiveRange(preset || presetFor(startDate, endDate, allTimeStart));
  }, [startDate, endDate, preset, allTimeStart]);

  // A `preset` with no dates yet means "apply this range on mount".
  useEffect(() => {
    if (preset && !startDate && !endDate) {
      const { start, end } = getPresetRange(preset, allTimeStart);
      if (start && end) {
        setTempStart(safeFormat(start));
        setTempEnd(safeFormat(end));
        onApply(safeFormat(start), safeFormat(end));
      }
    }
  }, [preset, startDate, endDate, onApply, allTimeStart]);

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
    const { start, end } = getPresetRange(value, allTimeStart);
    setTempStart(safeFormat(start));
    setTempEnd(safeFormat(end));
    setEditing('start');
  };

  // Set the side being edited, keeping the range ordered.
  const setEditedSide = (iso) => {
    setActiveRange('');
    if (editing === 'start') {
      setTempStart(iso);
      if (tempEnd && iso > tempEnd) setTempEnd(iso);
    } else {
      setTempEnd(iso);
      if (tempStart && iso < tempStart) setTempStart(iso);
    }
  };

  const handleDaySelect = (iso) => {
    setEditedSide(iso);
    // Move on to the end date.
    if (editing === 'start') setEditing('end');
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

            {/* Typing a date sets the side being edited as soon as it is a real
                date; Enter on the start moves to the end, Enter on the end applies.
                Keyed by side so switching sides starts the box afresh. */}
            <DateTextInput
              key={editing}
              value={editedValue}
              autoFocus
              label={editing === 'start' ? 'Type start date' : 'Type end date'}
              onPreview={setEditedSide}
              onCommit={(iso) => {
                if (editing === 'start') {
                  setEditing('end');
                  return;
                }
                const start = tempStart && tempStart <= iso ? tempStart : iso;
                onApply(start, iso);
                close();
              }}
              testId={`date-range-${editing}-text`}
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
