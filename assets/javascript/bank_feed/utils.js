/**
 * Utility functions for bank feed React components
 */

/**
 * Format date for display
 * @param {string|Date} dateString - Date to format
 * @returns {string} Formatted date string
 */
export function formatDate(dateString) {
  return new Date(dateString).toLocaleDateString();
}

/**
 * Format date for input field (YYYY-MM-DD)
 * @param {string|Date} dateVal - Date to format
 * @returns {string} Date in YYYY-MM-DD format
 */
export function formatDateForInput(dateVal) {
  if (!dateVal) return '';
  const date = dateVal instanceof Date ? dateVal : new Date(dateVal);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
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