import React, { useEffect, useState } from 'react';
import { format, startOfMonth } from 'date-fns';

import DateRangePicker from '../common/DateRangePicker';
import { createRoot } from 'react-dom/client';

// Shows the range the server rendered the report with (`data-start-date` /
// `data-end-date`): the URL's dates, else the book's default timeframe, else the
// report's own default. Reading it from the page rather than recomputing it here
// means the picker can never disagree with the report under it.
const DateRangePickerWrapper = ({ initialStart, initialEnd, allTimeStart }) => {
  const [startDate, setStartDate] = useState(initialStart);
  const [endDate, setEndDate] = useState(initialEnd);

  // Reflect a defaulted range in the URL without navigating, so a reload or a
  // shared link keeps it even if the book's default changes later. A real reload
  // here would throw away anything already on the page, including a message popup.
  useEffect(() => {
    const url = new URL(window.location);
    if (initialStart && initialEnd && !(url.searchParams.get('start_date') && url.searchParams.get('end_date'))) {
      url.searchParams.set('start_date', initialStart);
      url.searchParams.set('end_date', initialEnd);
      url.searchParams.delete('period');
      window.history.replaceState({}, '', url.toString());
    }
  }, [initialStart, initialEnd]);

  const handleDateRangeApply = (newStartDate, newEndDate) => {
    setStartDate(newStartDate);
    setEndDate(newEndDate);

    const url = new URL(window.location);
    url.searchParams.set('start_date', newStartDate);
    url.searchParams.set('end_date', newEndDate);
    url.searchParams.delete('period');

    // Navigate to the new URL (triggers page reload with report)
    window.location.href = url.toString();
  };

  return (
    <DateRangePicker
      startDate={startDate}
      endDate={endDate}
      onApply={handleDateRangeApply}
      allTimeStart={allTimeStart || format(startOfMonth(new Date()), 'yyyy-MM-dd')}
    />
  );
};

// `data-all-time-start` (the book's first entry date) bounds the "All time" preset.
const el = document.getElementById('date-range-picker');

if (!el) {
  console.warn('Date range picker mount point not found');
} else {
  createRoot(el).render(
    <DateRangePickerWrapper
      initialStart={el.dataset.startDate || ''}
      initialEnd={el.dataset.endDate || ''}
      allTimeStart={el.dataset.allTimeStart || ''}
    />,
  );
}
