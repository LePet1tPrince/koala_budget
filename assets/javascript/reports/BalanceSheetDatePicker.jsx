import React, { useEffect, useRef, useState } from 'react';
import {
  Box,
  Button,
  Divider,
  IconButton,
  List,
  ListItemButton,
  ListItemText,
  Popover,
  Stack,
  Typography,
} from '@mui/material';
import {
  endOfMonth,
  endOfYear,
  format,
  isValid,
  parseISO,
  subDays,
  subMonths,
  subYears,
} from 'date-fns';
import ClearIcon from '@mui/icons-material/Clear';
import { AdapterDateFns } from '@mui/x-date-pickers/AdapterDateFns';
import { DatePicker } from '@mui/x-date-pickers/DatePicker';
import { LocalizationProvider } from '@mui/x-date-pickers/LocalizationProvider';
import { createRoot } from 'react-dom/client';

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

// Helper to format date for display (e.g., "Jan 1, 2024")
const formatDisplayDate = (date) => {
  if (!date || !isValid(date)) return '';
  return format(date, 'MMM d, yyyy');
};

// Preset ranges - each returns the END date of that period
const presetRanges = [
  { label: 'Today', value: 'today' },
  { label: 'End of last month', value: 'lastMonth' },
  { label: 'End of this year', value: 'thisYear' },
  { label: 'End of last year', value: 'lastYear' },
];

// Get the end date for a preset
const getPresetEndDate = (preset) => {
  const now = new Date();

  switch (preset) {
    case 'today':
      return now;
    case 'lastMonth':
      const lastMonth = subMonths(now, 1);
      return endOfMonth(lastMonth);
    case 'thisYear':
      return endOfYear(now);
    case 'lastYear':
      const lastYear = subYears(now, 1);
      return endOfYear(lastYear);
    default:
      return now;
  }
};

// Component that integrates with URL parameters
const BalanceSheetDatePickerWrapper = () => {
  const [anchorEl, setAnchorEl] = useState(null);
  const [asOfDate, setAsOfDate] = useState('');
  const [tempDate, setTempDate] = useState(null);
  const [activePreset, setActivePreset] = useState('');
  const isInitialMount = useRef(true);

  // Get initial value from URL parameter or set default to today
  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const urlAsOfDate = urlParams.get('as_of_date');

    if (urlAsOfDate) {
      setAsOfDate(urlAsOfDate);
      setTempDate(safeParseISO(urlAsOfDate));
    } else {
      const today = format(new Date(), 'yyyy-MM-dd');
      setAsOfDate(today);
      setTempDate(new Date());
    }

    isInitialMount.current = false;
  }, []);

  const handleClick = (event) => {
    setTempDate(safeParseISO(asOfDate));
    setActivePreset('');
    setAnchorEl(event.currentTarget);
  };

  const handleClose = () => {
    setAnchorEl(null);
  };

  const handleApply = () => {
    const newDate = safeFormat(tempDate);
    if (newDate && newDate !== asOfDate) {
      // Build URL with query parameter
      const url = new URL(window.location);
      url.searchParams.set('as_of_date', newDate);
      window.location.href = url.toString();
    }
    handleClose();
  };

  const handlePresetClick = (preset) => {
    setActivePreset(preset);
    const endDate = getPresetEndDate(preset);
    setTempDate(endDate);
  };

  const handleClear = (e) => {
    e.stopPropagation();
    // Reset to today
    const today = new Date();
    const todayStr = format(today, 'yyyy-MM-dd');
    if (todayStr !== asOfDate) {
      const url = new URL(window.location);
      url.searchParams.set('as_of_date', todayStr);
      window.location.href = url.toString();
    }
  };

  const open = Boolean(anchorEl);
  const id = open ? 'date-picker-popover' : undefined;

  // Get display text for the button
  const getDisplayText = () => {
    const date = safeParseISO(asOfDate);
    if (!date) return 'Select date';
    return `As of ${formatDisplayDate(date)}`;
  };

  return (
    <LocalizationProvider dateAdapter={AdapterDateFns}>
      <Box>
        <Button
          aria-describedby={id}
          variant="outlined"
          onClick={handleClick}
          sx={{ textTransform: 'none', color: 'text.secondary', borderColor: 'grey.400' }}
          endIcon={
            asOfDate && (
              <IconButton
                size="small"
                onClick={handleClear}
                sx={{ mr: -1, ml: 0.5 }}
                aria-label="Reset to today"
              >
                <ClearIcon fontSize="small" />
              </IconButton>
            )
          }
        >
          {getDisplayText()}
        </Button>
        <Popover
          id={id}
          open={open}
          anchorEl={anchorEl}
          onClose={handleClose}
          anchorOrigin={{
            vertical: 'bottom',
            horizontal: 'left',
          }}
          transformOrigin={{
            vertical: 'top',
            horizontal: 'left',
          }}
        >
          <Box sx={{ display: 'flex', p: 2, width: 'auto' }}>
            {/* Preset Ranges */}
            <Stack spacing={1} sx={{ borderRight: 1, borderColor: 'divider', pr: 2, mr: 2, minWidth: 150 }}>
              <Typography variant="overline" sx={{ pl: 2 }}>Presets</Typography>
              <List dense disablePadding>
                {presetRanges.map((range) => (
                  <ListItemButton
                    key={range.value}
                    selected={activePreset === range.value}
                    onClick={() => handlePresetClick(range.value)}
                  >
                    <ListItemText primary={range.label} />
                  </ListItemButton>
                ))}
              </List>
            </Stack>

            {/* Date Picker and Actions */}
            <Stack spacing={2}>
              <Typography variant="overline">Custom Date</Typography>
              <DatePicker
                label="As of date"
                value={tempDate}
                onChange={(newValue) => {
                  setTempDate(newValue);
                  setActivePreset('');
                }}
                slotProps={{ textField: { size: 'small' } }}
              />
              <Divider sx={{ my: 1 }} />
              <Stack direction="row" spacing={1} justifyContent="flex-end">
                <Button onClick={handleClose} size="small">
                  Cancel
                </Button>
                <Button variant="contained" onClick={handleApply} size="small">
                  Apply
                </Button>
              </Stack>
            </Stack>
          </Box>
        </Popover>
      </Box>
    </LocalizationProvider>
  );
};

// Mount the React app
const el = document.getElementById('balance-sheet-date-picker');

if (el) {
  createRoot(el).render(<BalanceSheetDatePickerWrapper />);
}
