import React, { useEffect, useState } from 'react';
import { format, startOfMonth, startOfYear } from 'date-fns';

import DateRangePicker from '../common/DateRangePicker';
import { createRoot } from 'react-dom/client';

// Component that integrates with URL parameters
const DateRangePickerWrapper = ({ defaultRange }) => {
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
      // No params: this is exactly the range the server already rendered the
      // page with (see the matching default in the view -- start of month, or
      // start of year on the account page, through today), so just reflect it
      // in the URL instead of navigating -- a real reload here would throw
      // away anything already on the page, including a just-shown message popup.
      const now = new Date();
      const rangeStart = defaultRange === 'year' ? startOfYear(now) : startOfMonth(now);
      const defaultStart = format(rangeStart, 'yyyy-MM-dd');
      const defaultEnd = format(now, 'yyyy-MM-dd');

      setStartDate(defaultStart);
      setEndDate(defaultEnd);

      const url = new URL(window.location);
      url.searchParams.set('start_date', defaultStart);
      url.searchParams.set('end_date', defaultEnd);
      url.searchParams.delete('period');
      window.history.replaceState({}, '', url.toString());
    }
  }, [defaultRange]);

  return (
    <DateRangePicker
      startDate={startDate}
      endDate={endDate}
      onApply={handleDateRangeApply}
    />
  );
};

// Mount the React app. `data-default-range="year"` on the mount point opts a
// page into a this-year default instead of the usual this-month one.
const el = document.getElementById('date-range-picker');

if (!el) {
  console.warn('Date range picker mount point not found');
} else {
  createRoot(el).render(<DateRangePickerWrapper defaultRange={el.dataset.defaultRange || 'month'} />);
}
