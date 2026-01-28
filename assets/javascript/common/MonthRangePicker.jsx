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
import React, { useEffect, useState } from 'react';
import {
  endOfMonth,
  endOfYear,
  format,
  isValid,
  parse,
  startOfMonth,
  startOfYear,
  subMonths,
  subYears,
} from 'date-fns';

import { AdapterDateFns } from '@mui/x-date-pickers/AdapterDateFns';
import ClearIcon from '@mui/icons-material/Clear';
import { DatePicker } from '@mui/x-date-pickers/DatePicker';
import { LocalizationProvider } from '@mui/x-date-pickers/LocalizationProvider';

// Helper to safely parse YYYY-MM string to Date object
const safeParseMonth = (monthString) => {
  if (!monthString) return null;
  const date = parse(monthString, 'yyyy-MM', new Date());
  return isValid(date) ? date : null;
};

// Helper to safely format Date object to 'yyyy-MM' string
const safeFormatMonth = (date) => {
  return date && isValid(date) ? format(date, 'yyyy-MM') : '';
};

// Helper to format date for display (e.g., "Jan 2024")
const formatDisplayMonth = (date) => {
  if (!date || !isValid(date)) return '';
  return format(date, 'MMM yyyy');
};

const presetRanges = [
  { label: 'Last 3 months', value: 'last3months' },
  { label: 'Last 6 months', value: 'last6months' },
  { label: 'Last 12 months', value: 'last12months' },
  { label: 'This year', value: 'thisYear' },
  { label: 'Last year', value: 'lastYear' },
  { label: 'All time', value: 'allTime' },
];

/**
 * Month Range Picker component using MUI DatePicker with month/year views only.
 *
 * @param {Object} props
 * @param {string} props.startMonth - Start month as YYYY-MM string
 * @param {string} props.endMonth - End month as YYYY-MM string
 * @param {function} props.onApply - Callback with (startMonth, endMonth) as YYYY-MM strings
 * @param {string} props.preset - Optional preset to apply on mount
 */
const MonthRangePicker = ({ startMonth, endMonth, onApply, preset }) => {
  const [anchorEl, setAnchorEl] = useState(null);
  const [tempStartMonth, setTempStartMonth] = useState(safeParseMonth(startMonth));
  const [tempEndMonth, setTempEndMonth] = useState(safeParseMonth(endMonth));
  const [activeRange, setActiveRange] = useState(preset || '');

  // Update temp months when props change
  useEffect(() => {
    setTempStartMonth(safeParseMonth(startMonth));
    setTempEndMonth(safeParseMonth(endMonth));
    setActiveRange(preset || '');
  }, [startMonth, endMonth, preset]);

  // Apply preset when component mounts with a preset
  useEffect(() => {
    if (preset && !startMonth && !endMonth) {
      const { start, end } = getPresetRange(preset);
      if (start && end) {
        setTempStartMonth(start);
        setTempEndMonth(end);
        onApply(safeFormatMonth(start), safeFormatMonth(end));
      }
    }
  }, [preset, startMonth, endMonth, onApply]);

  const getPresetRange = (value) => {
    const now = new Date();
    let start = null;
    let end = null;

    switch (value) {
      case 'last3months':
        end = startOfMonth(now);
        start = startOfMonth(subMonths(now, 2));
        break;
      case 'last6months':
        end = startOfMonth(now);
        start = startOfMonth(subMonths(now, 5));
        break;
      case 'last12months':
        end = startOfMonth(now);
        start = startOfMonth(subMonths(now, 11));
        break;
      case 'thisYear':
        start = startOfYear(now);
        end = startOfMonth(now);
        break;
      case 'lastYear':
        const lastYear = subYears(now, 1);
        start = startOfYear(lastYear);
        end = endOfYear(lastYear);
        break;
      case 'allTime':
        // Default to 5 years back
        start = startOfYear(subYears(now, 5));
        end = startOfMonth(now);
        break;
      default:
        break;
    }

    return { start, end };
  };

  const handleClick = (event) => {
    setTempStartMonth(safeParseMonth(startMonth));
    setTempEndMonth(safeParseMonth(endMonth));
    setActiveRange('');
    setAnchorEl(event.currentTarget);
  };

  const handleClose = () => {
    setAnchorEl(null);
  };

  const handleApply = () => {
    onApply(safeFormatMonth(tempStartMonth), safeFormatMonth(tempEndMonth));
    handleClose();
  };

  const handleClearAll = (e) => {
    e.stopPropagation();
    setTempStartMonth(null);
    setTempEndMonth(null);
    setActiveRange('');
    onApply('', '');
  };

  const handlePresetClick = (value) => {
    setActiveRange(value);
    const { start, end } = getPresetRange(value);
    setTempStartMonth(start);
    setTempEndMonth(end);
  };

  const open = Boolean(anchorEl);
  const id = open ? 'month-range-popover' : undefined;

  // Get display text for the button
  const getDisplayText = () => {
    const start = safeParseMonth(startMonth);
    const end = safeParseMonth(endMonth);
    if (!start && !end) return 'Select month range';
    if (start && end) return `${formatDisplayMonth(start)} – ${formatDisplayMonth(end)}`;
    if (start) return `From ${formatDisplayMonth(start)}`;
    if (end) return `Until ${formatDisplayMonth(end)}`;
    return 'Select month range';
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
            (startMonth || endMonth) && (
              <IconButton
                size="small"
                onClick={handleClearAll}
                sx={{ mr: -1, ml: 0.5 }}
                aria-label="Clear month range"
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

            {/* Month Pickers and Actions */}
            <Stack spacing={2}>
              <Typography variant="overline">Custom Range</Typography>
              <DatePicker
                label="Start month"
                value={tempStartMonth}
                onChange={(newValue) => {
                  setTempStartMonth(newValue);
                  setActiveRange('');
                }}
                views={['year', 'month']}
                openTo="month"
                slotProps={{ textField: { size: 'small' } }}
                maxDate={tempEndMonth || undefined}
              />
              <DatePicker
                label="End month"
                value={tempEndMonth}
                onChange={(newValue) => {
                  setTempEndMonth(newValue);
                  setActiveRange('');
                }}
                views={['year', 'month']}
                openTo="month"
                slotProps={{ textField: { size: 'small' } }}
                minDate={tempStartMonth || undefined}
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

export default MonthRangePicker;
