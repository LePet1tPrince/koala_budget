import React from 'react';
import { computeFormula } from './amount';

/**
 * A text input for an amount that also takes simple arithmetic.
 *
 * Typing "45.20+12.80" or "3*19.99" is left alone while the user types; on
 * blur or Enter the formula is replaced by its result ("58.00", "59.97"),
 * reported through `onValueChange` like any other edit. A plain number is
 * never reformatted here -- callers keep whatever formatting they already do.
 *
 * A text input rather than `type="number"`, which would refuse the operators.
 * Every other prop (className, disabled, aria-*, data-testid, onKeyDown,
 * onBlur, …) passes straight through to the `<input>`.
 */
const AmountInput = React.forwardRef(function AmountInput(
  { value, onValueChange, onBlur, onKeyDown, ...rest },
  ref,
) {
  const settle = (input) => {
    const result = computeFormula(input.value);
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
