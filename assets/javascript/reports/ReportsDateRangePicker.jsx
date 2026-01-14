import React, { useEffect, useState } from 'react';
import { endOfMonth, format, startOfMonth } from 'date-fns';

import DateRangePickerMUI from '../common/DateRangePickerMUI';
import { createRoot } from 'react-dom/client';

// Component that integrates with URL parameters
const DateRangePickerWrapper = () => {
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');

  // Handle date range changes
  const handleDateRangeApply = (newStartDate, newEndDate) => {
    setStartDate(newStartDate);
    setEndDate(newEndDate);

    // Build URL with query parameters (only start_date and end_date)
    const url = new URL(window.location);
    url.searchParams.set('start_date', newStartDate);
    url.searchParams.set('end_date', newEndDate);
    // Remove period parameter if it exists
    url.searchParams.delete('period');

    // Navigate to the new URL (triggers page reload with report)
    window.location.href = url.toString();
  };

  // Get initial values from URL parameters or set defaults
  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const urlStartDate = urlParams.get('start_date');
    const urlEndDate = urlParams.get('end_date');

    if (urlStartDate && urlEndDate) {
      // Use dates from URL
      setStartDate(urlStartDate);
      setEndDate(urlEndDate);
    } else {
      // Set default to current month and auto-load report
      const now = new Date();
      const startOfCurrentMonth = startOfMonth(now);
      const endOfCurrentMonth = endOfMonth(now);

      const defaultStart = format(startOfCurrentMonth, 'yyyy-MM-dd');
      const defaultEnd = format(endOfCurrentMonth, 'yyyy-MM-dd');

      setStartDate(defaultStart);
      setEndDate(defaultEnd);

      // Auto-load report with default dates
      setTimeout(() => {
        handleDateRangeApply(defaultStart, defaultEnd);
      }, 100); // Small delay to ensure component is mounted
    }
  }, [handleDateRangeApply]);

  return (
    <DateRangePickerMUI
      startDate={startDate}
      endDate={endDate}
      onApply={handleDateRangeApply}
    />
  );
};

// Mount the React app
const el = document.getElementById('date-range-picker');

if (!el) {
  console.warn('Date range picker mount point not found');
} else {
  createRoot(el).render(<DateRangePickerWrapper />);
}
