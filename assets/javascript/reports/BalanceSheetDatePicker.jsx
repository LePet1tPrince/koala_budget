import React, { useEffect, useState } from 'react';
import { endOfMonth, endOfYear, format, isValid, parseISO, startOfMonth, subMonths, subYears } from 'date-fns';

import PickerPopover, {
  CalendarIcon,
  DayGrid,
  PanelHeading,
  PickerActions,
  PresetList,
} from '../common/PickerPopover';
import { createRoot } from 'react-dom/client';

const safeParseISO = (dateString) => {
  if (!dateString) return null;
  const date = parseISO(dateString);
  return isValid(date) ? date : null;
};

const safeFormat = (date) => (date && isValid(date) ? format(date, 'yyyy-MM-dd') : '');

const formatDisplayDate = (dateString) => {
  const date = safeParseISO(dateString);
  return date ? format(date, 'MMM d, yyyy') : '';
};

// Each preset resolves to the END date of that period — a balance sheet is "as of" a day.
const presetRanges = [
  { label: 'Today', value: 'today' },
  { label: 'End of last month', value: 'lastMonth' },
  { label: 'End of this year', value: 'thisYear' },
  { label: 'End of last year', value: 'lastYear' },
];

const getPresetEndDate = (preset) => {
  const now = new Date();
  switch (preset) {
    case 'today':
      return now;
    case 'lastMonth':
      return endOfMonth(subMonths(now, 1));
    case 'thisYear':
      return endOfYear(now);
    case 'lastYear':
      return endOfYear(subYears(now, 1));
    default:
      return now;
  }
};

const BalanceSheetDatePickerWrapper = () => {
  const [asOfDate, setAsOfDate] = useState('');
  const [tempDate, setTempDate] = useState('');
  const [activePreset, setActivePreset] = useState('');
  const [gridMonth, setGridMonth] = useState(startOfMonth(new Date()));

  // Seed from `?as_of_date`, defaulting to today.
  useEffect(() => {
    const urlAsOfDate = new URLSearchParams(window.location.search).get('as_of_date');
    const initial = urlAsOfDate || format(new Date(), 'yyyy-MM-dd');
    setAsOfDate(initial);
    setTempDate(initial);
    const d = safeParseISO(initial);
    if (d) setGridMonth(startOfMonth(d));
  }, []);

  const navigateTo = (newDate) => {
    if (newDate && newDate !== asOfDate) {
      const url = new URL(window.location);
      url.searchParams.set('as_of_date', newDate);
      window.location.href = url.toString();
    }
  };

  return (
    <PickerPopover
      label={asOfDate ? `As of ${formatDisplayDate(asOfDate)}` : 'Select date'}
      icon={<CalendarIcon />}
      testId="balance-sheet-date-trigger"
      onClear={() => navigateTo(format(new Date(), 'yyyy-MM-dd'))}
      panelClassName="w-max"
    >
      {({ close }) => (
        <div className="flex flex-col gap-4 sm:flex-row sm:gap-5">
          <PresetList
            presets={presetRanges}
            active={activePreset}
            onSelect={(preset) => {
              setActivePreset(preset);
              const d = getPresetEndDate(preset);
              setTempDate(safeFormat(d));
              setGridMonth(startOfMonth(d));
            }}
          />

          <div className="flex flex-col gap-3">
            <PanelHeading>Custom Date</PanelHeading>
            <DayGrid
              month={gridMonth}
              onMonthChange={setGridMonth}
              value={tempDate}
              testId="balance-sheet-as-of"
              onSelect={(iso) => {
                setTempDate(iso);
                setActivePreset('');
              }}
            />
            <PickerActions
              onCancel={() => {
                setTempDate(asOfDate);
                close();
              }}
              onApply={() => {
                navigateTo(tempDate);
                close();
              }}
            />
          </div>
        </div>
      )}
    </PickerPopover>
  );
};

const el = document.getElementById('balance-sheet-date-picker');

if (!el) {
  console.warn('Balance sheet date picker mount point not found');
} else {
  createRoot(el).render(<BalanceSheetDatePickerWrapper />);
}
