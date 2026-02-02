import React, { useState } from 'react';
import {
  Box,
  Button,
  IconButton,
  Popover,
  Typography,
} from '@mui/material';
import ChevronLeftIcon from '@mui/icons-material/ChevronLeft';
import ChevronRightIcon from '@mui/icons-material/ChevronRight';
import { addMonths, format, parse, subMonths, isValid } from 'date-fns';

const MONTH_LABELS = [
  'Jan', 'Feb', 'Mar', 'Apr',
  'May', 'Jun', 'Jul', 'Aug',
  'Sep', 'Oct', 'Nov', 'Dec',
];

/**
 * Budget Month Picker - a compact month selector with prev/next arrows
 * and a dropdown grid for jumping to any month.
 *
 * Reads the current month from the `month` URL query parameter (YYYY-MM-DD)
 * and navigates by updating it.
 *
 * @param {Object} props
 * @param {string} props.initialMonth - Current month as YYYY-MM-DD string
 */
const BudgetMonthPicker = ({ initialMonth }) => {
  const currentMonth = parseMonth(initialMonth);
  const [anchorEl, setAnchorEl] = useState(null);
  const [pickerYear, setPickerYear] = useState(currentMonth.getFullYear());

  const open = Boolean(anchorEl);

  const navigateToMonth = (date) => {
    const url = new URL(window.location);
    url.searchParams.set('month', format(date, 'yyyy-MM-dd'));
    window.location.href = url.toString();
  };

  const handlePrev = () => navigateToMonth(subMonths(currentMonth, 1));
  const handleNext = () => navigateToMonth(addMonths(currentMonth, 1));

  const handleOpen = (e) => {
    setPickerYear(currentMonth.getFullYear());
    setAnchorEl(e.currentTarget);
  };

  const handleClose = () => setAnchorEl(null);

  const handleMonthSelect = (monthIndex) => {
    const selected = new Date(pickerYear, monthIndex, 1);
    handleClose();
    navigateToMonth(selected);
  };

  const currentMonthIndex = currentMonth.getMonth();
  const currentYear = currentMonth.getFullYear();

  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
      <IconButton onClick={handlePrev} size="small" aria-label="Previous month">
        <ChevronLeftIcon />
      </IconButton>

      <Button
        onClick={handleOpen}
        variant="text"
        sx={{
          textTransform: 'none',
          fontWeight: 700,
          fontSize: '1.1rem',
          color: 'text.primary',
          px: 1.5,
          minWidth: 'auto',
        }}
      >
        {format(currentMonth, 'MMMM yyyy')}
      </Button>

      <IconButton onClick={handleNext} size="small" aria-label="Next month">
        <ChevronRightIcon />
      </IconButton>

      <Popover
        open={open}
        anchorEl={anchorEl}
        onClose={handleClose}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
        transformOrigin={{ vertical: 'top', horizontal: 'center' }}
      >
        <Box sx={{ p: 2, width: 260 }}>
          {/* Year navigation */}
          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1.5 }}>
            <IconButton size="small" onClick={() => setPickerYear((y) => y - 1)} aria-label="Previous year">
              <ChevronLeftIcon fontSize="small" />
            </IconButton>
            <Typography variant="subtitle1" fontWeight={700}>
              {pickerYear}
            </Typography>
            <IconButton size="small" onClick={() => setPickerYear((y) => y + 1)} aria-label="Next year">
              <ChevronRightIcon fontSize="small" />
            </IconButton>
          </Box>

          {/* Month grid */}
          <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 0.5 }}>
            {MONTH_LABELS.map((label, idx) => {
              const isSelected = idx === currentMonthIndex && pickerYear === currentYear;
              return (
                <Button
                  key={label}
                  size="small"
                  variant={isSelected ? 'contained' : 'text'}
                  onClick={() => handleMonthSelect(idx)}
                  sx={{
                    minWidth: 0,
                    py: 0.75,
                    fontSize: '0.8rem',
                    fontWeight: isSelected ? 700 : 400,
                  }}
                >
                  {label}
                </Button>
              );
            })}
          </Box>
        </Box>
      </Popover>
    </Box>
  );
};

function parseMonth(str) {
  if (!str) return new Date(new Date().getFullYear(), new Date().getMonth(), 1);
  const date = parse(str, 'yyyy-MM-dd', new Date());
  return isValid(date) ? new Date(date.getFullYear(), date.getMonth(), 1) : new Date(new Date().getFullYear(), new Date().getMonth(), 1);
}

export default BudgetMonthPicker;
