/* globals gettext */
import React, { useEffect, useRef, useState } from 'react';
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

// Safely parse ISO date string to Date or null
const safeParseISO = (dateString) => {
  if (!dateString) return null;
  const d = parseISO(dateString);
  return isValid(d) ? d : null;
};

// Format date to yyyy-MM-dd
const safeFormat = (date) => {
  return date && isValid(date) ? format(date, 'yyyy-MM-dd') : '';
};

// Pretty display
const formatDisplayDate = (date) => {
  if (!date || !isValid(date)) return '';
  return format(date, 'MMM d, yyyy');
};

const presetRanges = [
  { label: gettext('Last 7 days'), value: 'last7days' },
  { label: gettext('Last 30 days'), value: 'last30days' },
  { label: gettext('This month'), value: 'thisMonth' },
  { label: gettext('Last month'), value: 'lastMonth' },
  { label: gettext('This year'), value: 'thisYear' },
  { label: gettext('Last year'), value: 'lastYear' },
];

const DateRangePicker = ({ startDate, endDate, onApply }) => {
  const [open, setOpen] = useState(false);
  const [tempStart, setTempStart] = useState(safeParseISO(startDate));
  const [tempEnd, setTempEnd] = useState(safeParseISO(endDate));
  const [activeRange, setActiveRange] = useState('');
  const containerRef = useRef(null);

  useEffect(() => {
    setTempStart(safeParseISO(startDate));
    setTempEnd(safeParseISO(endDate));
    setActiveRange('');
  }, [startDate, endDate]);

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    if (open) document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [open]);

  const handleToggle = () => {
    // Reset temps to props when opening
    if (!open) {
      setTempStart(safeParseISO(startDate));
      setTempEnd(safeParseISO(endDate));
      setActiveRange('');
    }
    setOpen(!open);
  };

  const handleApply = () => {
    onApply(safeFormat(tempStart), safeFormat(tempEnd));
    setOpen(false);
  };

  const handleClear = (e) => {
    e.stopPropagation();
    setTempStart(null);
    setTempEnd(null);
    setActiveRange('');
    onApply('', '');
  };

  const handlePresetClick = (value) => {
    setActiveRange(value);
    const now = new Date();
    let s = null;
    let e = null;
    switch (value) {
      case 'last7days':
        e = now;
        s = subDays(now, 6);
        break;
      case 'last30days':
        e = now;
        s = subDays(now, 29);
        break;
      case 'thisMonth':
        s = startOfMonth(now);
        e = endOfMonth(now);
        break;
      case 'lastMonth':
        const lm = subMonths(now, 1);
        s = startOfMonth(lm);
        e = endOfMonth(lm);
        break;
      case 'thisYear':
        s = startOfYear(now);
        e = endOfYear(now);
        break;
      case 'lastYear':
        const ly = subYears(now, 1);
        s = startOfYear(ly);
        e = endOfYear(ly);
        break;
      default:
        break;
    }
    setTempStart(s);
    setTempEnd(e);
  };

  const getDisplayText = () => {
    const s = safeParseISO(startDate);
    const e = safeParseISO(endDate);
    if (!s && !e) return gettext('Select date range');
    if (s && e) return `${formatDisplayDate(s)} – ${formatDisplayDate(e)}`;
    if (s) return `${gettext('From')} ${formatDisplayDate(s)}`;
    if (e) return `${gettext('Until')} ${formatDisplayDate(e)}`;
    return gettext('Select date range');
  };

  return (
    <div className="relative inline-block" ref={containerRef}>
      <button
        type="button"
        className="btn btn-outline btn-sm normal-case"
        onClick={handleToggle}
      >
        <span className="mr-2">{getDisplayText()}</span>
        {(startDate || endDate) && (
          <button
            type="button"
            className="btn btn-ghost btn-sm ml-2"
            onClick={handleClear}
            aria-label={gettext('Clear date range')}
          >
            <i className="fa fa-times" />
          </button>
        )}
      </button>

      {open && (
        <div className="absolute z-50 mt-2 w-96 bg-base-100 shadow-lg rounded-md p-4 border">
          <div className="flex space-x-4">
            <div className="w-40 pr-2 border-r">
              <div className="text-xs text-gray-500 mb-2">{gettext('Presets')}</div>
              <ul className="space-y-1">
                {presetRanges.map((p) => (
                  <li key={p.value}>
                    <button
                      type="button"
                      className={`w-full text-left py-1 px-2 rounded ${activeRange === p.value ? 'bg-primary text-white' : 'hover:bg-base-200'}`}
                      onClick={() => handlePresetClick(p.value)}
                    >
                      {p.label}
                    </button>
                  </li>
                ))}
              </ul>
            </div>

            <div className="flex-1">
              <div className="text-xs text-gray-500 mb-2">{gettext('Custom Range')}</div>
              <div className="grid grid-cols-2 gap-2 mb-3">
                <div>
                  <label className="label">
                    <span className="label-text text-sm">{gettext('Start date')}</span>
                  </label>
                  <input
                    type="date"
                    className="input input-sm input-bordered w-full"
                    value={tempStart ? safeFormat(tempStart) : ''}
                    onChange={(e) => setTempStart(e.target.value ? parseISO(e.target.value) : null)}
                    max={tempEnd ? safeFormat(tempEnd) : undefined}
                  />
                </div>
                <div>
                  <label className="label">
                    <span className="label-text text-sm">{gettext('End date')}</span>
                  </label>
                  <input
                    type="date"
                    className="input input-sm input-bordered w-full"
                    value={tempEnd ? safeFormat(tempEnd) : ''}
                    onChange={(e) => setTempEnd(e.target.value ? parseISO(e.target.value) : null)}
                    min={tempStart ? safeFormat(tempStart) : undefined}
                  />
                </div>
              </div>

              <div className="flex justify-end space-x-2">
                <button type="button" className="btn btn-sm" onClick={() => setOpen(false)}>{gettext('Cancel')}</button>
                <button type="button" className="btn btn-sm btn-primary" onClick={handleApply}>{gettext('Apply')}</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default DateRangePicker;
