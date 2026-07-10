import React, { useEffect, useState } from 'react';
import { format, subMonths } from 'date-fns';

import MonthRangePicker from '../common/MonthRangePicker';
import { createRoot } from 'react-dom/client';

// Component that integrates with URL parameters
const NetWorthTrendMonthPickerWrapper = () => {
  const [startMonth, setStartMonth] = useState('');
  const [endMonth, setEndMonth] = useState('');

  // Handle month range changes
  const handleMonthRangeApply = (newStartMonth, newEndMonth) => {
    setStartMonth(newStartMonth);
    setEndMonth(newEndMonth);

    // Build URL with query parameters
    const url = new URL(window.location);
    url.searchParams.set('start_month', newStartMonth);
    url.searchParams.set('end_month', newEndMonth);

    // Navigate to the new URL (triggers page reload with report)
    window.location.href = url.toString();
  };

  // Get initial values from URL parameters or set defaults
  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const urlStartMonth = urlParams.get('start_month');
    const urlEndMonth = urlParams.get('end_month');

    if (urlStartMonth && urlEndMonth) {
      // Use months from URL
      setStartMonth(urlStartMonth);
      setEndMonth(urlEndMonth);
    } else {
      // Mirror the server-side default (last 12 months) — the server already
      // rendered that report, so no redirect is needed.
      const now = new Date();
      setStartMonth(format(subMonths(now, 12), 'yyyy-MM'));
      setEndMonth(format(now, 'yyyy-MM'));
    }
  }, []);

  return (
    <MonthRangePicker
      startMonth={startMonth}
      endMonth={endMonth}
      onApply={handleMonthRangeApply}
    />
  );
};

// Mount the React app
const el = document.getElementById('month-range-picker');

if (el) {
  createRoot(el).render(<NetWorthTrendMonthPickerWrapper />);
}
