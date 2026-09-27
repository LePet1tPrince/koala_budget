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

/**
 * Simple arithmetic in an amount field: "45.20+12.80", "3*19.99", "120/4",
 * "1,200 - 85.50". Evaluated by a small recursive-descent parser, never
 * `eval`. Supports + - * / (also x, ×, ÷ and a Unicode minus), unary minus,
 * parentheses for grouping, and the same "$" / "," tolerance as a plain amount.
 * `*` and `/` bind tighter than `+` and `-`.
 *
 * A lone parenthesised number is still the accounting negative -- "(45.00)" is
 * -45.00 -- because `sanitizeAmount` sees it before this does; parentheses
 * only group once there is an operator in play.
 */
const MAX_EXPRESSION_LENGTH = 200;

function tokenize(text) {
  const tokens = [];
  const pattern = /\d+\.?\d*|\.\d+|[-+*/()]/y;
  while (pattern.lastIndex < text.length) {
    const match = pattern.exec(text);
    if (!match) return null;
    tokens.push(match[0]);
  }
  return tokens;
}

function evaluateTokens(tokens) {
  let pos = 0;
  const peek = () => tokens[pos];

  // factor := ('+'|'-') factor | '(' expr ')' | number
  function factor() {
    const token = tokens[pos++];
    if (token === '-') return -factor();
    if (token === '+') return factor();
    if (token === '(') {
      const value = expr();
      if (tokens[pos++] !== ')') throw new Error('unbalanced');
      return value;
    }
    if (token === undefined || !/\d/.test(token)) throw new Error('expected a number');
    return parseFloat(token);
  }

  // term := factor (('*'|'/') factor)*
  function term() {
    let value = factor();
    while (peek() === '*' || peek() === '/') {
      const op = tokens[pos++];
      const right = factor();
      if (op === '/' && right === 0) throw new Error('division by zero');
      value = op === '*' ? value * right : value / right;
    }
    return value;
  }

  // expr := term (('+'|'-') term)*
  function expr() {
    let value = term();
    while (peek() === '+' || peek() === '-') {
      const op = tokens[pos++];
      const right = term();
      value = op === '+' ? value + right : value - right;
    }
    return value;
  }

  const value = expr();
  if (pos !== tokens.length) throw new Error('trailing input');
  return value;
}

/** Round half away from zero to cents, absorbing float noise (1.005 -> 1.01). */
function toCentsString(value) {
  const cents = Math.round(Math.abs(value) * 100 + 1e-7);
  const result = (Math.sign(value) * cents) / 100;
  return (Object.is(result, -0) ? 0 : result).toFixed(2);
}

/**
 * The result of a formula typed into an amount field, as "12.34" -- or null
 * when the text is not a formula (a plain number, blank, or something that
 * doesn't evaluate). This is what a field swaps in when the user leaves it.
 */
export function computeFormula(raw) {
  if (raw === null || raw === undefined) return null;
  const text = String(raw)
    .replace(/[\s\u00a0\u2009\u202f]/g, '')
    .replace(/[$€£,]/g, '')
    .replace(/\u2212/g, '-')
    .replace(/[x×X]/g, '*')
    .replace(/÷/g, '/');
  if (text === '' || text.length > MAX_EXPRESSION_LENGTH) return null;
  if (sanitizeAmount(raw) !== null) return null;
  // Needs an operator between two operands; a bare "-5" or "(5)" is a number.
  if (!/[\d.)]\s*[-+*/]/.test(text)) return null;

  const tokens = tokenize(text);
  if (!tokens) return null;
  let value;
  try {
    value = evaluateTokens(tokens);
  } catch {
    return null;
  }
  return Number.isFinite(value) ? toCentsString(value) : null;
}

/**
 * A typed amount -- plain number or formula -- normalized to "12.34", or null
 * when it is neither. Use this for anything the user typed; keep
 * `sanitizeAmount` for pasted spreadsheet cells, where "2026-01" is a label
 * and must not be read as 2025.
 */
export function evaluateAmount(raw) {
  return sanitizeAmount(raw) ?? computeFormula(raw);
}

/** The numeric value of a typed amount (formulas included), or null when it isn't one. */
export function parseAmount(raw) {
  const evaluated = evaluateAmount(raw);
  return evaluated === null ? null : parseFloat(evaluated);
}

/**
 * A typed amount for an API payload: the evaluated figure, the fallback when
 * the field is blank, or the raw text so the server can refuse it by name.
 */
export function amountForPayload(raw, blank = '0') {
  if (raw === null || raw === undefined || String(raw).trim() === '') return blank;
  return evaluateAmount(raw) ?? String(raw);
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
