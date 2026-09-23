/**
 * Parsing and formatting money the way the rest of the app does.
 *
 * `sanitizeAmount` started life in the budget grid, where it had to survive
 * whatever Excel put on the clipboard. The split editor needs exactly the same
 * tolerance -- someone pasting "$1,234.56" or "(45.00)" into a leg means the
 * same thing they meant in the grid -- so it lives here rather than in two
 * places that could drift apart.
 */

/**
 * Parse one pasted/typed cell into a normalized amount string, or null if it
 * isn't a number. Handles common spreadsheet formats: "$1,234.56", "(45.00)"
 * (negative), currency symbols, thin/non-breaking spaces.
 */
export function sanitizeAmount(raw) {
  if (raw === null || raw === undefined) return null;
  let text = String(raw).replace(/[\s   ]/g, '');
  if (text === '') return null;

  let negative = false;
  const parens = text.match(/^\((.*)\)$/);
  if (parens) {
    negative = true;
    text = parens[1];
  }
  text = text.replace(/[$€£]/g, '').replace(/,/g, '');
  if (text.startsWith('-')) {
    negative = !negative;
    text = text.slice(1);
  }
  if (text === '' || !/^\d*\.?\d*$/.test(text) || !/\d/.test(text)) return null;

  const value = parseFloat(text);
  if (!isFinite(value)) return null;
  return (negative ? -value : value).toFixed(2);
}

/** The numeric value of a typed amount, or null when it isn't one. */
export function parseAmount(raw) {
  const sanitized = sanitizeAmount(raw);
  return sanitized === null ? null : parseFloat(sanitized);
}

/**
 * Integer cents from an API amount string ("-12.75" -> -1275). Sums of money
 * are done in cents so a long column of ticks never drifts by a float's worth.
 */
export const toCents = (value) => Math.round((Number(value) || 0) * 100);

/** Round to cents, so a sum of parsed amounts can be compared exactly. */
export const round2 = (value) => Math.round(value * 100) / 100;

/**
 * `$1,234.50` / `-$3.00` -- matching the `currency` template filter.
 *
 * Deliberately not `Intl.NumberFormat` with `style: 'currency'`, which renders
 * CAD as "CA$1,234.50" and has already had to be backed out once.
 */
export function formatMoney(value) {
  const amount = Number(value) || 0;
  const sign = amount < 0 ? '-' : '';
  return `${sign}$${Math.abs(amount).toLocaleString('en-CA', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}
