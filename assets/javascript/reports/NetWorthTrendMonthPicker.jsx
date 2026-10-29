import React, { useState } from 'react';

import MonthRangePicker from '../common/MonthRangePicker';
import { createRoot } from 'react-dom/client';

// Shows the months the server rendered the report with (`data-start-month` /
// `data-end-month`, yyyy-MM): the URL's months, else the book's default
// timeframe, else the report's own default — so no redirect is needed.
const NetWorthTrendMonthPickerWrapper = ({ initialStart, initialEnd }) => {
  const [startMonth, setStartMonth] = useState(initialStart);
  const [endMonth, setEndMonth] = useState(initialEnd);

  const handleMonthRangeApply = (newStartMonth, newEndMonth) => {
    setStartMonth(newStartMonth);
    setEndMonth(newEndMonth);

    const url = new URL(window.location);
    url.searchParams.set('start_month', newStartMonth);
    url.searchParams.set('end_month', newEndMonth);

    // Navigate to the new URL (triggers page reload with report)
    window.location.href = url.toString();
  };

  return (
    <MonthRangePicker
      startMonth={startMonth}
      endMonth={endMonth}
      onApply={handleMonthRangeApply}
    />
  );
};

const el = document.getElementById('month-range-picker');

if (el) {
  createRoot(el).render(
    <NetWorthTrendMonthPickerWrapper
      initialStart={el.dataset.startMonth || ''}
      initialEnd={el.dataset.endMonth || ''}
    />,
  );
}
