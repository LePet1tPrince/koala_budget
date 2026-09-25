/* globals gettext */

import React, { useEffect, useMemo, useRef, useState } from 'react';

import Icon from '../common/Icon';
import useListNavigation from '../common/useListNavigation';

/**
 * A filter box over a list of names, driven from the keyboard.
 *
 * Focus stays in the filter box, so typing always narrows the list, while
 * ↑/↓ and Tab/Shift+Tab move the highlight (wrapping at both ends) and Enter takes
 * it -- the same behaviour as the CSV wizard's account picker, through the same
 * `common/useListNavigation` hook. `actions` are rows after the names (a "New …"
 * row, say) that the highlight reaches like any option.
 *
 * `onPick(name)` receives the chosen name; an action runs its own `onPick`.
 */
const PickList = ({ options, value, onPick, actions = [], ariaLabel, testId, emptyText }) => {
  const [query, setQuery] = useState('');
  const inputRef = useRef(null);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return needle ? options.filter((option) => option.toLowerCase().includes(needle)) : options;
  }, [options, query]);

  const rows = [
    ...filtered.map((name) => ({ key: `o:${name}`, name })),
    ...actions.map((action) => ({ key: `a:${action.key}`, action })),
  ];
  const nav = useListNavigation(rows.length, { tabCycles: true });

  // Open on the current choice, so the list starts from where the row already is.
  // Focus in an effect rather than `autoFocus`: the popover this sits in is still
  // hidden while it measures itself, and a hidden input cannot take focus.
  useEffect(() => {
    const index = options.indexOf(value);
    nav.setActive(index >= 0 ? index : 0);
    inputRef.current?.focus();
    // Only on opening: the panel mounts fresh each time it opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const take = (row) => {
    if (!row) return;
    if (row.action) row.action.onPick();
    else onPick(row.name);
  };

  return (
    <div className="flex min-h-0 flex-col">
      <input
        type="text"
        className="input input-bordered input-sm m-1 w-auto"
        placeholder={gettext('Filter')}
        aria-label={gettext('Filter')}
        ref={inputRef}
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          nav.setActive(0);
        }}
        onKeyDown={(e) => nav.onKeyDown(e, { onPick: (index) => take(rows[index]) })}
        data-testid={testId ? `${testId}-filter` : undefined}
      />
      <ul role="listbox" aria-label={ariaLabel} className="min-h-0 overflow-y-auto">
        {rows.slice(0, filtered.length).map((row, index) => {
          const selected = row.name === value;
          return (
            <li key={row.key}>
              <button
                type="button"
                role="option"
                tabIndex={-1}
                aria-selected={selected}
                {...nav.itemProps(index)}
                className={`flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-left text-sm focus:outline-none ${
                  index === nav.active ? 'bg-base-200' : 'hover:bg-base-200'
                } ${selected ? 'font-medium' : ''}`}
                onClick={() => take(row)}
              >
                <Icon
                  name="check"
                  className={`h-4 w-4 shrink-0 text-primary ${selected ? '' : 'invisible'}`}
                  aria-hidden="true"
                />
                <span className="truncate" title={row.name}>
                  {row.name}
                </span>
              </button>
            </li>
          );
        })}
        {filtered.length === 0 && (
          <li className="px-3 py-1.5 text-sm text-base-content/70">{emptyText || gettext('No matches')}</li>
        )}
      </ul>
      {actions.length > 0 && (
        <ul className="mt-1 border-t border-base-300 pt-1">
          {rows.slice(filtered.length).map((row, offset) => {
            const index = filtered.length + offset;
            return (
              <li key={row.key}>
                <button
                  type="button"
                  tabIndex={-1}
                  {...nav.itemProps(index)}
                  className={`flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-left text-sm text-primary focus:outline-none ${
                    index === nav.active ? 'bg-base-200' : 'hover:bg-base-200'
                  }`}
                  onClick={() => take(row)}
                  data-testid={row.action.testId}
                >
                  <Icon name={row.action.icon || 'plus'} className="h-4 w-4 shrink-0" aria-hidden="true" />
                  {row.action.label}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
};

export default PickList;
