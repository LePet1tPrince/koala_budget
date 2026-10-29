import React, { useEffect, useRef, useState } from 'react';
import { format, isValid, parseISO } from 'date-fns';

/* globals gettext */

/**
 * A typed date, day first: `ddmmyyyy` ("16102026"), or the same with separators
 * ("16/10/2026", "1.2.2026", "16-10-2026"). Returns ISO `yyyy-MM-dd`, or null for
 * anything else — including a date that does not exist (31022026), which a
 * `new Date()` would quietly roll over into March.
 */
export const parseTypedDate = (text) => {
  const t = (text || '').trim();
  const m = t.match(/^(\d{2})(\d{2})(\d{4})$/) || t.match(/^(\d{1,2})[\s./-](\d{1,2})[\s./-](\d{4})$/);
  if (!m) return null;
  const [day, month, year] = m.slice(1).map(Number);
  // A 4-digit year below 1000 would land in the 1900s: `new Date(12, …)` is 1912.
  if (year < 1000) return null;
  const date = new Date(year, month - 1, day);
  if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) return null;
  return format(date, 'yyyy-MM-dd');
};

const display = (iso) => {
  const d = iso ? parseISO(iso) : null;
  return d && isValid(d) ? format(d, 'dd/MM/yyyy') : '';
};

/**
 * The text box at the top of a date picker's panel, so a date can be typed rather
 * than clicked. It shows the current value day first (`dd/MM/yyyy`), selected on
 * focus so typing replaces it. `autoFocus` focuses it as the panel opens, on
 * devices with a fine pointer.
 *
 * @param {string}   value     Current date, ISO. The box follows it when it changes
 *                             from outside (a day clicked in the grid).
 * @param {function} onPreview Called with the ISO date whenever the text is a
 *                             complete, real date — so the grid can move to it.
 * @param {function} onCommit  Called with `(iso, { via })` on Enter (`via: 'enter'`)
 *                             and, with `commitOnBlur`, on leaving the box having
 *                             typed a different date (`via: 'blur'`). Enter on text
 *                             that is not a date marks the box invalid instead.
 */
const DateTextInput = ({
  value,
  onPreview,
  onCommit,
  commitOnBlur = false,
  label,
  autoFocus = false,
  testId,
}) => {
  const [text, setText] = useState(() => display(value));
  const [invalid, setInvalid] = useState(false);
  const inputRef = useRef(null);
  // Escape closes the panel and should throw the typing away, and Enter has
  // already taken it, but the box can still blur on its way out; this keeps that
  // blur from committing.
  const cancelled = useRef(false);

  // Follow the value when it changes from outside -- but not while it is the date
  // being typed, or "16102026" would be rewritten under the cursor.
  useEffect(() => {
    setText((prev) => (parseTypedDate(prev) === value ? prev : display(value)));
    setInvalid(false);
  }, [value]);

  useEffect(() => {
    // Only with a mouse or trackpad: on a touch screen, focusing would throw up the
    // keyboard over the calendar every time the picker opens.
    if (!autoFocus || !window.matchMedia?.('(pointer: fine)').matches) return;
    inputRef.current?.focus();
    inputRef.current?.select();
  }, [autoFocus]);

  return (
    <label className="form-control block w-full">
      {label && <span className="mb-1 block text-xs text-base-content/70">{label}</span>}
      <input
        ref={inputRef}
        type="text"
        inputMode="numeric"
        autoComplete="off"
        placeholder={gettext('DDMMYYYY')}
        className={`input input-bordered input-sm w-full tabular-nums ${invalid ? 'input-error' : ''}`}
        value={text}
        aria-invalid={invalid}
        data-testid={testId}
        onFocus={(e) => e.target.select()}
        onChange={(e) => {
          cancelled.current = false;
          const next = e.target.value;
          setText(next);
          setInvalid(false);
          const iso = parseTypedDate(next);
          if (iso) onPreview?.(iso);
        }}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            cancelled.current = true;
            return;
          }
          if (e.key !== 'Enter') return;
          // Never let Enter submit a surrounding form.
          e.preventDefault();
          const iso = parseTypedDate(text);
          if (!iso) {
            setInvalid(true);
            return;
          }
          // Taken: the blur as the panel closes must not take it a second time.
          cancelled.current = true;
          onCommit(iso, { via: 'enter' });
        }}
        onBlur={() => {
          if (!commitOnBlur || cancelled.current || !text.trim()) return;
          const iso = parseTypedDate(text);
          if (!iso) setInvalid(true);
          else if (iso !== value) onCommit(iso, { via: 'blur' });
        }}
      />
      {invalid && (
        <span className="mt-1 block text-xs text-error" role="alert">
          {gettext('Type the date as DDMMYYYY, e.g. 16102026.')}
        </span>
      )}
    </label>
  );
};

export default DateTextInput;
