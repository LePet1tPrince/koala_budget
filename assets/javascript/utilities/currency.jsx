/**
 * Format a number as currency
 * @param {number|string} amount - The amount to format (accepts Decimal strings from the API)
 * @param {string} currency - Currency code (default: 'USD')
 * @param {string} [locale] - Locale string (defaults to the browser locale)
 * @returns {string} Formatted currency string
 */
export const formatCurrency = (amount, currency = 'USD', locale = undefined) => {
  const value = typeof amount === 'string' ? parseFloat(amount) : amount;
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency: currency,
  }).format(Number.isFinite(value) ? value : 0);
};
