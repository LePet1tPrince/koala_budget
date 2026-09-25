/* globals gettext */

import React, { useState } from 'react';

/**
 * One-line "name it" form: the + on the name bank and the "New …" row in a chip
 * menu both open this.
 *
 * `onSubmit(raw)` returns an error message, or nothing when the name was taken.
 */
const NewNameForm = ({ placeholder, submitLabel, onSubmit, onCancel, testId }) => {
  const [value, setValue] = useState('');
  const [error, setError] = useState('');

  const submit = () => {
    const problem = onSubmit(value);
    if (problem) setError(problem);
  };

  return (
    <div className="flex flex-col gap-1" data-testid={testId}>
      <div className="flex items-center gap-1.5">
        <input
          type="text"
          className={`input input-bordered input-sm w-48 ${error ? 'input-error' : ''}`}
          placeholder={placeholder}
          value={value}
          maxLength={200}
          // eslint-disable-next-line jsx-a11y/no-autofocus
          autoFocus
          aria-label={placeholder}
          aria-invalid={Boolean(error)}
          onChange={(e) => {
            setValue(e.target.value);
            setError('');
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              submit();
            } else if (e.key === 'Escape') {
              // The innermost dismissible: close this form, not the menu around it.
              e.preventDefault();
              e.stopPropagation();
              onCancel();
            }
          }}
        />
        <button type="button" className="btn btn-primary btn-sm" onClick={submit}>
          {submitLabel || gettext('Add')}
        </button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onCancel}>
          {gettext('Cancel')}
        </button>
      </div>
      {error && (
        <span className="text-xs text-error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
};

export default NewNameForm;
