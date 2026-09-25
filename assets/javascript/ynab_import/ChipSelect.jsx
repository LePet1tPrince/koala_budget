/* globals gettext */

import React, { useCallback, useRef, useState } from 'react';

import Icon from '../common/Icon';
import ChipPopover from './ChipPopover';
import NewNameForm from './NewNameForm';
import PickList from './PickList';

/**
 * A chip showing the current choice; clicking it opens the list to choose from,
 * ending in a "New …" row that names one on the spot.
 *
 * There is no way to type a value into the chip itself: every row picks from the
 * same list, so a typo can only ever be made once -- when the name is created --
 * and it then shows up at the top of the screen where it can be seen.
 *
 * The list is a `PickList`: a filter box with ↑/↓ and Tab/Shift+Tab moving the
 * highlight and Enter taking it.
 *
 * `onCreate(raw)` returns `{ name }` (the name to select, which may be an existing
 * one the user retyped) or `{ error }`.
 */
const ChipSelect = ({ value, options, onChange, onCreate, createLabel, createPlaceholder, ariaLabel, testId }) => {
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const triggerRef = useRef(null);

  const close = useCallback(() => {
    setOpen(false);
    setCreating(false);
  }, []);

  const choose = (name) => {
    onChange(name);
    close();
    triggerRef.current?.focus();
  };

  const create = (raw) => {
    const result = onCreate(raw);
    if (result.error) return result.error;
    choose(result.name);
    return null;
  };

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className="chip-select"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`${ariaLabel}: ${value}`}
        onClick={() => (open ? close() : setOpen(true))}
        data-testid={testId}
        data-value={value}
      >
        <span className="truncate" title={value}>
          {value}
        </span>
        <Icon name="chevron-down" className="h-3.5 w-3.5 shrink-0 opacity-60" aria-hidden="true" />
      </button>
      <ChipPopover open={open} triggerRef={triggerRef} onClose={close} testId={testId ? `${testId}-menu` : undefined}>
        {creating ? (
          <div className="p-2">
            <NewNameForm
              placeholder={createPlaceholder}
              onSubmit={create}
              onCancel={() => setCreating(false)}
              testId={testId ? `${testId}-new-form` : undefined}
            />
          </div>
        ) : (
          <PickList
            options={options}
            value={value}
            onPick={choose}
            ariaLabel={ariaLabel}
            actions={[
              {
                key: 'new',
                label: createLabel,
                onPick: () => setCreating(true),
                testId: testId ? `${testId}-new` : undefined,
              },
            ]}
          />
        )}
      </ChipPopover>
    </>
  );
};

export default ChipSelect;
