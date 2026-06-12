/**
 * Utility functions for bank feed React components
 */

/**
 * Whether a Date represents a date-only value parsed as UTC midnight
 * (e.g. `new Date('2026-06-12')`, which is how the generated API client
 * parses date-only fields). Local Dates from pickers sit at local midnight,
 * which is only UTC midnight when the user's timezone is UTC — in which
 * case both interpretations agree anyway.
 */
function isUtcMidnight(date) {
  return date.getUTCHours() === 0 && date.getUTCMinutes() === 0 && date.getUTCSeconds() === 0;
}

/**
 * Format date for display
 * @param {string|Date} dateString - Date to format
 * @returns {string} Formatted date string
 */
export function formatDate(dateString) {
  const date = dateString instanceof Date ? dateString : new Date(dateString);
  // Date-only values must be rendered in UTC, otherwise users west of UTC
  // see the previous day.
  return isUtcMidnight(date) ? date.toLocaleDateString(undefined, { timeZone: 'UTC' }) : date.toLocaleDateString();
}

/**
 * Format date for input field / API submission (YYYY-MM-DD)
 * @param {string|Date} dateVal - Date to format
 * @returns {string} Date in YYYY-MM-DD format
 */
export function formatDateForInput(dateVal) {
  if (!dateVal) return '';
  if (typeof dateVal === 'string') return dateVal.slice(0, 10);
  const date = dateVal;
  // UTC-midnight Dates are date-only values: read them in UTC. Picker Dates
  // sit at local midnight: read them in local time. Never use toISOString(),
  // which shifts local-midnight dates to the previous day east of UTC.
  const utc = isUtcMidnight(date);
  const year = utc ? date.getUTCFullYear() : date.getFullYear();
  const month = String((utc ? date.getUTCMonth() : date.getMonth()) + 1).padStart(2, '0');
  const day = String(utc ? date.getUTCDate() : date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

/**
 * Capitalize first letter of string
 * @param {string} val - String to capitalize
 * @returns {string} Capitalized string
 */
export function ProperCase(val) {
    return String(val).charAt(0).toUpperCase() + String(val).slice(1);
}