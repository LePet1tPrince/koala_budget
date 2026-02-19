import { Box } from '@mui/material';
import React from 'react';
import { format, isValid, parseISO } from 'date-fns';

import { AdapterDateFns } from '@mui/x-date-pickers/AdapterDateFns';
import { DatePicker as MUIDatePicker } from '@mui/x-date-pickers/DatePicker';
import { LocalizationProvider } from '@mui/x-date-pickers/LocalizationProvider';

// Helper to safely parse ISO string to Date object
const safeParseISO = (dateString) => {
  if (!dateString) return null;
  const date = parseISO(dateString);
  return isValid(date) ? date : null;
};

// Helper to safely format Date object to 'yyyy-MM-dd' string
const safeFormat = (date) => {
  return date && isValid(date) ? format(date, 'yyyy-MM-dd') : '';
};

/**
 * Single date picker component using MUI DatePicker.
 *
 * @param {Object} props
 * @param {string} props.value - Date value as ISO string (yyyy-MM-dd)
 * @param {function} props.onChange - Callback with new date as ISO string
 * @param {string} props.label - Label for the date picker
 * @param {string} props.minDate - Minimum selectable date as ISO string
 * @param {string} props.maxDate - Maximum selectable date as ISO string
 * @param {string} props.size - Size of the text field ('small' | 'medium')
 * @param {boolean} props.disabled - Whether the picker is disabled
 * @param {boolean} props.required - Whether the field is required
 * @param {string} props.error - Error message to display
 */
const DatePicker = ({
  value,
  onChange,
  label = 'Select date',
  minDate,
  maxDate,
  size = 'small',
  disabled = false,
  required = false,
  error,
}) => {
  const dateValue = safeParseISO(value);
  const minDateValue = safeParseISO(minDate);
  const maxDateValue = safeParseISO(maxDate);

  const handleChange = (newValue) => {
    const formatted = safeFormat(newValue);
    onChange(formatted);
  };

  return (
    <LocalizationProvider dateAdapter={AdapterDateFns}>
      <Box>
        <MUIDatePicker
          label={label}
          value={dateValue}
          onChange={handleChange}
          disabled={disabled}
          minDate={minDateValue || undefined}
          maxDate={maxDateValue || undefined}
          slotProps={{
            textField: {
              size,
              required,
              error: !!error,
              helperText: error,
            },
          }}
        />
      </Box>
    </LocalizationProvider>
  );
};

export default DatePicker;
