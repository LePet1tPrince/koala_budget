import React, { useEffect, useState } from 'react';
import { format, isValid, parse, startOfYear, subMonths, subYears } from 'date-fns';

import PickerPopover, {
  CalendarIcon,
  MonthGrid,
  PickerActions,
  PresetList,
} from './PickerPopover';

// Values are 'yyyy-MM' strings throughout.
const safeParseMonth = (monthString) => {
  if (!monthString) return null;
  const date = parse(monthString, 'yyyy-MM', new Date());
  return isValid(date) ? date : null;
};

const safeFormatMonth = (date) => (date && isValid(date) ? format(date, 'yyyy-MM') : '');

const formatDisplayMonth = (monthString) => {
  const date = safeParseMonth(monthString);
  return date ? format(date, 'MMM yyyy') : '';
};

const presetRanges = [
  { label: 'Last 3 months', value: 'last3months' },
  { label: 'Last 6 months', value: 'last6months' },
  { label: 'Last 12 months', value: 'last12months' },
  { label: 'This year', value: 'thisYear' },
  { label: 'Last year', value: 'lastYear' },
  { label: 'All time', value: 'allTime' },
];

const getPresetRange = (value) => {
  const now = new Date();
  switch (value) {
    case 'last3months':
      return { start: subMonths(now, 2), end: now };
    case 'last6months':
      return { start: subMonths(now, 5), end: now };
    case 'last12months':
      return { start: subMonths(now, 11), end: now };
    case 'thisYear':
      return { start: startOfYear(now), end: now };
    case 'lastYear': {
      const d = subYears(now, 1);
      return { start: startOfYear(d), end: new Date(d.getFullYear(), 11, 1) };
    }
    case 'allTime':
      return { start: null, end: null };
    default:
      return { start: null, end: null };
  }
};

/**
 * A start/end month range. Both sides are picked from a month grid rather than
 * `<input type="month">`, which Firefox does not implement.
 */
const MonthRangePicker = ({ startMonth, endMonth, onApply, preset }) => {
  const [tempStart, setTempStart] = useState(startMonth || '');
  const [tempEnd, setTempEnd] = useState(endMonth || '');
  const [activeRange, setActiveRange] = useState(preset || '');
  const [editing, setEditing] = useState('start'); // which side the grid edits
  const [gridYear, setGridYear] = useState(new Date().getFullYear());

  useEffect(() => {
    setTempStart(startMonth || '');
    setTempEnd(endMonth || '');
    setActiveRange(preset || '');
  }, [startMonth, endMonth, preset]);

  useEffect(() => {
    if (preset && !startMonth && !endMonth) {
      const { start, end } = getPresetRange(preset);
      if (start && end) {
        setTempStart(safeFormatMonth(start));
        setTempEnd(safeFormatMonth(end));
        onApply(safeFormatMonth(start), safeFormatMonth(end));
      }
    }
  }, [preset, startMonth, endMonth, onApply]);

  const handlePresetClick = (value) => {
    setActiveRange(value);
    const { start, end } = getPresetRange(value);
    setTempStart(safeFormatMonth(start));
    setTempEnd(safeFormatMonth(end));
  };

  const handleGridSelect = (year, monthIdx) => {
    const value = safeFormatMonth(new Date(year, monthIdx, 1));
    setActiveRange('');
    if (editing === 'start') {
      setTempStart(value);
      // Keep the range ordered, then move the grid on to the end month.
      if (tempEnd && value > tempEnd) setTempEnd(value);
      setEditing('end');
    } else {
      setTempEnd(value);
      if (tempStart && value < tempStart) setTempStart(value);
    }
  };

  const editedValue = editing === 'start' ? tempStart : tempEnd;
  const editedDate = safeParseMonth(editedValue);

  // Jump the grid to the year of whichever side is being edited, but only when the
  // side changes — otherwise this would fight the year arrows.
  useEffect(() => {
    if (editedDate) setGridYear(editedDate.getFullYear());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editing]);

  const getDisplayText = () => {
    if (!startMonth && !endMonth) return 'Select month range';
    if (startMonth && endMonth) {
      return `${formatDisplayMonth(startMonth)} – ${formatDisplayMonth(endMonth)}`;
    }
    if (startMonth) return `From ${formatDisplayMonth(startMonth)}`;
    return `Until ${formatDisplayMonth(endMonth)}`;
  };

  return (
    <PickerPopover
      label={getDisplayText()}
      icon={<CalendarIcon />}
      testId="month-range-picker-trigger"
      onClear={(startMonth || endMonth) ? () => onApply('', '') : null}
      panelClassName="w-max"
    >
      {({ close }) => (
        <div className="flex gap-3">
          <PresetList presets={presetRanges} active={activeRange} onSelect={handlePresetClick} />

          <div className="flex flex-col gap-2">
            {/* Which end of the range the grid below is setting. */}
            <div role="tablist" className="tabs tabs-box tabs-xs">
              <button
                type="button"
                role="tab"
                className={`tab ${editing === 'start' ? 'tab-active' : ''}`}
                onClick={() => setEditing('start')}
              >
                Start: {formatDisplayMonth(tempStart) || '—'}
              </button>
              <button
                type="button"
                role="tab"
                className={`tab ${editing === 'end' ? 'tab-active' : ''}`}
                onClick={() => setEditing('end')}
              >
                End: {formatDisplayMonth(tempEnd) || '—'}
              </button>
            </div>

            <MonthGrid
              year={gridYear}
              onYearChange={setGridYear}
              selectedYear={editedDate ? editedDate.getFullYear() : null}
              selectedMonth={editedDate ? editedDate.getMonth() : null}
              onSelect={handleGridSelect}
            />

            <PickerActions
              onCancel={() => {
                setTempStart(startMonth || '');
                setTempEnd(endMonth || '');
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

export default MonthRangePicker;
