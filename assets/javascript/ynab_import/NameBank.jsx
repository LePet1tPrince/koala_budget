/* globals gettext */

import React, { useState } from 'react';

import Icon from '../common/Icon';
import NewNameForm from './NewNameForm';

/**
 * The list every row on a screen picks from, shown once at the top.
 *
 * Each chip carries how many rows use it, so a group nothing is in yet reads as
 * such. A name the user added and no row uses can be taken off again; names the
 * import suggested stay, since unused ones are simply not created.
 *
 * `onAdd(raw)` returns an error message, or nothing when the name was added.
 */
const NameBank = ({ label, names, counts, removable = [], onRemove, onAdd, addLabel, addPlaceholder, testId }) => {
  const [adding, setAdding] = useState(false);

  const add = (raw) => {
    const problem = onAdd(raw);
    if (!problem) setAdding(false);
    return problem;
  };

  return (
    <div className="flex flex-wrap items-center gap-2" data-testid={testId}>
      {label && <span className="mr-1 text-sm font-medium text-base-content/70">{label}</span>}
      {names.map((name) => {
        const count = counts[name] || 0;
        const canRemove = count === 0 && removable.includes(name);
        return (
          <span
            key={name}
            className={`name-chip ${count === 0 ? 'is-unused' : ''}`}
            data-testid={testId ? `${testId}-chip` : undefined}
            data-name={name}
          >
            <span className="truncate" title={name}>
              {name}
            </span>
            <span
              className="money text-xs text-base-content/70"
              aria-label={gettext('{n} using it').replace('{n}', count)}
            >
              {count}
            </span>
            {canRemove && (
              <button
                type="button"
                className="-mr-1 rounded-full p-0.5 hover:bg-base-300"
                aria-label={gettext('Remove {name}').replace('{name}', name)}
                onClick={() => onRemove(name)}
              >
                <Icon name="x" className="h-3 w-3" aria-hidden="true" />
              </button>
            )}
          </span>
        );
      })}
      {adding ? (
        <NewNameForm
          placeholder={addPlaceholder}
          onSubmit={add}
          onCancel={() => setAdding(false)}
          testId={testId ? `${testId}-new-form` : undefined}
        />
      ) : (
        <button
          type="button"
          className="btn btn-ghost btn-sm btn-circle border border-dashed border-base-300"
          aria-label={addLabel}
          title={addLabel}
          onClick={() => setAdding(true)}
          data-testid={testId ? `${testId}-add` : undefined}
        >
          <Icon name="plus" className="h-4 w-4" aria-hidden="true" />
        </button>
      )}
    </div>
  );
};

export default NameBank;
