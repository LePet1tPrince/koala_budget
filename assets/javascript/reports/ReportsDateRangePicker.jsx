import React, { useEffect, useState } from 'react';

import DateRangePickerMUI from '../common/DateRangePickerMUI';
import { createRoot } from 'react-dom/client';

// Component that integrates with Django form
const DateRangePickerWrapper = () => {
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');

  // Get initial values from Django form fields
  useEffect(() => {
    const startInput = document.querySelector('input[name="start_date"]');
    const endInput = document.querySelector('input[name="end_date"]');

    if (startInput) {
      setStartDate(startInput.value || '');
    }
    if (endInput) {
      setEndDate(endInput.value || '');
    }
  }, []);

  // Handle date range changes
  const handleDateRangeApply = (newStartDate, newEndDate) => {
    setStartDate(newStartDate);
    setEndDate(newEndDate);

    // Update the Django form fields
    const startInput = document.querySelector('input[name="start_date"]');
    const endInput = document.querySelector('input[name="end_date"]');

    if (startInput) {
      startInput.value = newStartDate;
      // Trigger change event so Django form validation works
      startInput.dispatchEvent(new Event('change', { bubbles: true }));
    }
    if (endInput) {
      endInput.value = newEndDate;
      // Trigger change event so Django form validation works
      endInput.dispatchEvent(new Event('change', { bubbles: true }));
    }

    // Auto-submit the form to update the report
    const form = document.querySelector('form[method="get"]');
    if (form) {
      // Set period to 'custom' when using date picker
      const periodRadios = form.querySelectorAll('input[name="period"]');
      const customRadio = Array.from(periodRadios).find(radio => radio.value === 'custom');
      if (customRadio) {
        customRadio.checked = true;
        customRadio.dispatchEvent(new Event('change', { bubbles: true }));
      }

      // Submit the form
      form.submit();
    }
  };

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
