/**
 * Formula support for server-rendered amount fields.
 *
 * Any `<input data-amount-input>` on any page accepts simple arithmetic
 * ("45.20+12.80", "3*19.99"): when the field commits -- `change`, Enter, or
 * losing focus -- a formula is replaced by its result before the page's own
 * handlers read the value. The listeners are on `document` in the capture
 * phase, which runs ahead of listeners on the input itself, so code such as
 * the budget auto-save and the goal cards sees "58.00", never "45.20+12.80".
 *
 * An `input` event is dispatched after the swap so live previews (the cover
 * dialog's hint) redraw. React components use `common/AmountInput.jsx`
 * instead, since a controlled input must be updated through its state.
 */
import { computeFormula } from './amount';

const SELECTOR = 'input[data-amount-input]';

function settle(event) {
  const input = event.target;
  if (!(input instanceof HTMLInputElement) || !input.matches(SELECTOR)) return;
  const result = computeFormula(input.value);
  if (result === null) return;
  input.value = result;
  input.dispatchEvent(new Event('input', { bubbles: true }));
}

document.addEventListener('change', settle, true);
document.addEventListener('focusout', settle, true);
document.addEventListener(
  'keydown',
  (event) => {
    if (event.key === 'Enter') settle(event);
  },
  true,
);
