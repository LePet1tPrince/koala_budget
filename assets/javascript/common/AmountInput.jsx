import React, { useRef } from 'react';
import { computeFormula, evaluateAmount } from './amount';

// What an amount or formula can be made of: digits, separators, currency
// symbols, operators (x/× multiply, ÷ divide, Unicode minus) and parentheses.
const NOT_AMOUNT_CHARS = /[^0-9.,$€£+\-*/xX×÷\u2212()\s\u00a0\u2009\u202f]/g;

/**
 * `strict` clean-up of what was typed: characters that can't be part of an
 * amount are dropped; if what remains still isn't a number or formula, the
 * field goes back to what it held when focused (or blank).
 */
export function cleanAmountText(text, fallback = '') {
  const stripped = String(text ?? '').replace(NOT_AMOUNT_CHARS, '').trim();
  if (stripped === '') return String(text ?? '').trim() === '' ? '' : fallback;
  if (evaluateAmount(stripped) !== null) return stripped;
  return fallback;
}

/**
 * A text input for an amount that also takes simple arithmetic.
 *
 * Typing "45.20+12.80" or "3*19.99" is left alone while the user types; on
 * blur or Enter the formula is replaced by its result ("58.00", "59.97"),
 * reported through `onValueChange` like any other edit. A plain number is
 * never reformatted here -- callers keep whatever formatting they already do.
 *
 * A text input rather than `type="number"`, which would refuse the operators.
 * With `strict`, leaving the field also discards anything that is not an
 * amount: "jjj" disappears and "12abc" becomes "12" (see `cleanAmountText`).
 *
 * Every other prop (className, disabled, aria-*, data-testid, onKeyDown,
 * onBlur, onFocus, …) passes straight through to the `<input>`.
 */
const AmountInput = React.forwardRef(function AmountInput(
  { value, onValueChange, onBlur, onKeyDown, onFocus, strict = false, ...rest },
  ref,
) {
  // The value when the field was entered: what `strict` falls back to.
  const valueOnFocus = useRef('');

  const settle = (input) => {
    let text = input.value;
    if (strict) {
      const fallback = evaluateAmount(valueOnFocus.current) !== null ? valueOnFocus.current : '';
      const cleaned = cleanAmountText(text, fallback);
      if (cleaned !== text) {
        text = cleaned;
        onValueChange(cleaned);
      }
    }
    const result = computeFormula(text);
    if (result !== null) onValueChange(result);
  };

  return (
    <input
      ref={ref}
      type="text"
      inputMode="decimal"
      autoComplete="off"
      {...rest}
      value={value ?? ''}
      onChange={(e) => onValueChange(e.target.value)}
      onFocus={(e) => {
        valueOnFocus.current = e.target.value;
        onFocus?.(e);
      }}
      onBlur={(e) => {
        settle(e.target);
        onBlur?.(e);
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter') settle(e.target);
        onKeyDown?.(e);
      }}
    />
  );
});

export default AmountInput;
