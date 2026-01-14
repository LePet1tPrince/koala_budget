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

import { AdapterDateFns } from '@mui/x-date-pickers/AdapterDateFns';
import ClearIcon from '@mui/icons-material/Clear';
import { DatePicker } from '@mui/x-date-pickers/DatePicker';
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

// Helper to format date for display (e.g., "Jan 1, 2024")
const formatDisplayDate = (date) => {
  if (!date || !isValid(date)) return '';
  return format(date, 'MMM d, yyyy');
};

const presetRanges = [
  { label: 'Last 7 days', value: 'last7days' },
  { label: 'Last 30 days', value: 'last30days' },
  { label: 'This month', value: 'thisMonth' },
  { label: 'Last month', value: 'lastMonth' },
  { label: 'This year', value: 'thisYear' },
  { label: 'Last year', value: 'lastYear' },
];

const DateRangePickerMUI = ({ startDate, endDate, onApply, preset }) => {
  const [anchorEl, setAnchorEl] = useState(null);
  const [tempStartDate, setTempStartDate] = useState(safeParseISO(startDate));
  const [tempEndDate, setTempEndDate] = useState(safeParseISO(endDate));
  const [activeRange, setActiveRange] = useState(preset || '');
  const buttonRef = useRef(null);

  // Update temp dates when props change
  useEffect(() => {
    setTempStartDate(safeParseISO(startDate));
    setTempEndDate(safeParseISO(endDate));
    // Update active range if preset prop changes
    setActiveRange(preset || '');
  }, [startDate, endDate, preset]);

  // Apply preset when component mounts with a preset
  useEffect(() => {
    if (preset && !startDate && !endDate) {
      const now = new Date();
      let start = null;
      let end = null;

      switch (preset) {
        case 'last7days':
          end = now;
          start = subDays(now, 6);
          break;
        case 'last30days':
          end = now;
          start = subDays(now, 29);
          break;
        case 'thisMonth':
          start = startOfMonth(now);
          end = endOfMonth(now);
          break;
        case 'lastMonth':
          const lastMonthDate = subMonths(now, 1);
          start = startOfMonth(lastMonthDate);
          end = endOfMonth(lastMonthDate);
          break;
        case 'thisYear':
          start = startOfYear(now);
          end = endOfYear(now);
          break;
        case 'lastYear':
          const lastYearDate = subYears(now, 1);
          start = startOfYear(lastYearDate);
          end = endOfYear(lastYearDate);
          break;
        default:
          break;
      }

      if (start && end) {
        setTempStartDate(start);
        setTempEndDate(end);
        // Automatically apply the preset dates
        onApply(safeFormat(start), safeFormat(end));
      }
    }
  }, [preset, startDate, endDate, onApply]); // Include dependencies

  const handleClick = (event) => {
    // Reset temp dates to current props when opening
    setTempStartDate(safeParseISO(startDate));
    setTempEndDate(safeParseISO(endDate));
    setActiveRange(''); // Reset active preset
    setAnchorEl(event.currentTarget);
  };

  const handleClose = () => {
    setAnchorEl(null);
  };

  const handleApply = () => {
    onApply(safeFormat(tempStartDate), safeFormat(tempEndDate));
    handleClose();
  };

  const handleClearAll = (e) => {
    e.stopPropagation(); // Prevent opening the popover
    setTempStartDate(null);
    setTempEndDate(null);
    setActiveRange('');
    onApply('', ''); // Apply empty dates immediately
  };

  const handlePresetClick = (value) => {
    setActiveRange(value);
    const now = new Date();
    let start = null;
    let end = null;

    switch (value) {
      case 'last7days':
        end = now;
        start = subDays(now, 6);
        break;
      case 'last30days':
        end = now;
        start = subDays(now, 29);
        break;
      case 'thisMonth':
        start = startOfMonth(now);
        end = endOfMonth(now); // Use end of month for consistency
        break;
      case 'lastMonth':
        const lastMonthDate = subMonths(now, 1);
        start = startOfMonth(lastMonthDate);
        end = endOfMonth(lastMonthDate);
        break;
      case 'thisYear':
        start = startOfYear(now);
        end = endOfYear(now); // Use end of year
        break;
      case 'lastYear':
        const lastYearDate = subYears(now, 1);
        start = startOfYear(lastYearDate);
        end = endOfYear(lastYearDate);
        break;
      default:
        break;
    }
    setTempStartDate(start);
    setTempEndDate(end);
  };

  const open = Boolean(anchorEl);
  const id = open ? 'date-range-popover' : undefined;

  // Get display text for the button
  const getDisplayText = () => {
    const start = safeParseISO(startDate);
    const end = safeParseISO(endDate);
    if (!start && !end) return 'Select date range';
    if (start && end) return `${formatDisplayDate(start)} – ${formatDisplayDate(end)}`;
    if (start) return `From ${formatDisplayDate(start)}`;
    if (end) return `Until ${formatDisplayDate(end)}`;
    return 'Select date range'; // Fallback
  };

  return (
    <LocalizationProvider dateAdapter={AdapterDateFns}>
      <Box>
        <Button
          ref={buttonRef}
          aria-describedby={id}
          variant="outlined"
          onClick={handleClick}
          sx={{ textTransform: 'none', color: 'text.secondary', borderColor: 'grey.400' }}
          endIcon={
            (startDate || endDate) && (
              <IconButton
                size="small"
                onClick={handleClearAll}
                sx={{ mr: -1, ml: 0.5 }}
                aria-label="Clear date range"
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
                    selected={activeRange === range.value}
                    onClick={() => handlePresetClick(range.value)}
                  >
                    <ListItemText primary={range.label} />
                  </ListItemButton>
                ))}
              </List>
            </Stack>

            {/* Date Pickers and Actions */}
            <Stack spacing={2}>
              <Typography variant="overline">Custom Range</Typography>
              <DatePicker
                label="Start date"
                value={tempStartDate}
                onChange={(newValue) => {
                  setTempStartDate(newValue);
                  setActiveRange(''); // Clear preset selection
                }}
                slotProps={{ textField: { size: 'small' } }}
                maxDate={tempEndDate || undefined} // Prevent start date after end date
              />
              <DatePicker
                label="End date"
                value={tempEndDate}
                onChange={(newValue) => {
                  setTempEndDate(newValue);
                  setActiveRange(''); // Clear preset selection
                }}
                slotProps={{ textField: { size: 'small' } }}
                minDate={tempStartDate || undefined} // Prevent end date before start date
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

export default DateRangePickerMUI;
