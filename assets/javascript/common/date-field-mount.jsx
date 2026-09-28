'use strict';

import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';

import DateField from './DateField';

/**
 * The shared `DateField` for server-rendered Django forms.
 *
 * Each `<input type="date" data-date-field>` is the no-JS path; with JS on it
 * becomes a hidden input that the picker writes ISO `yyyy-MM-dd` into, so the
 * form posts exactly what the native input would have. `data-allow-clear`
 * offers a clear button (an optional date), `data-testid` carries over to the
 * picker's trigger.
 */
const FormDateField = ({ input, testId }) => {
  const [value, setValue] = useState(input.value);
  return (
    <DateField
      value={value}
      onChange={(iso) => {
        input.value = iso;
        setValue(iso);
        input.dispatchEvent(new Event('change', { bubbles: true }));
      }}
      allowClear={input.hasAttribute('data-allow-clear')}
      disabled={input.disabled}
      testId={testId}
    />
  );
};

document.querySelectorAll('input[data-date-field]').forEach((input) => {
  const mount = document.createElement('div');
  input.after(mount);
  input.type = 'hidden';
  const testId = input.dataset.testid;
  input.removeAttribute('data-testid');
  createRoot(mount).render(<FormDateField input={input} testId={testId} />);
});
