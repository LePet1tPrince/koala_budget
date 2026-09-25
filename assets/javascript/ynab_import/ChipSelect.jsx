/* globals gettext */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

import Icon from '../common/Icon';
import { portalTarget, useAnchoredPosition } from '../common/popoverPosition';
import NewNameForm from './NewNameForm';

// Past this many options the menu grows a filter box.
const FILTER_AT = 8;

/**
 * A chip showing the current choice; clicking it opens the list to choose from,
 * ending in a "New …" row that names one on the spot.
 *
 * There is no way to type a value into the chip itself: every row picks from the
 * same list, so a typo can only ever be made once -- when the name is created --
 * and it then shows up at the top of the screen where it can be seen.
 *
 * `onCreate(raw)` returns `{ name }` (the name to select, which may be an existing
 * one the user retyped) or `{ error }`.
 */
const ChipSelect = ({ value, options, onChange, onCreate, createLabel, createPlaceholder, ariaLabel, testId }) => {
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [query, setQuery] = useState('');
  const triggerRef = useRef(null);
  const panelRef = useRef(null);

  const close = useCallback(() => {
    setOpen(false);
    setCreating(false);
    setQuery('');
  }, []);

  const { style, measure } = useAnchoredPosition(open, triggerRef, panelRef, { minWidth: 224 });

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return needle ? options.filter((option) => option.toLowerCase().includes(needle)) : options;
  }, [options, query]);

  // The panel changes size as the list filters and the new-name form opens.
  useEffect(() => {
    if (open) measure();
  }, [open, creating, filtered.length, measure]);

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (e) => {
      if (triggerRef.current?.contains(e.target) || panelRef.current?.contains(e.target)) return;
      close();
    };
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [open, close]);

  // Once placed, put focus on the current choice so arrow-free keyboard use
  // (Tab / Shift+Tab, Enter) starts from where the row already is.
  useEffect(() => {
    if (!open || !style || creating) return;
    const panel = panelRef.current;
    const target = panel?.querySelector('input[type="text"]') || panel?.querySelector('[aria-selected="true"]');
    (target || panel?.querySelector('[role="option"]'))?.focus();
    // Only on opening: refocusing as the filter narrows would steal the caret.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, Boolean(style)]);

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

  const panel = open
    ? createPortal(
        <div
          ref={panelRef}
          className="fixed z-[1200] flex flex-col overflow-hidden rounded-xl border border-base-300 bg-base-100 p-1 shadow-lg"
          style={
            style ? { ...style, maxHeight: Math.min(style.maxHeight, 360) } : { top: 0, left: 0, visibility: 'hidden' }
          }
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.preventDefault();
              close();
              triggerRef.current?.focus();
            }
          }}
          data-testid={testId ? `${testId}-menu` : undefined}
        >
          {options.length > FILTER_AT && (
            <input
              type="text"
              className="input input-bordered input-sm m-1 w-auto"
              placeholder={gettext('Filter')}
              aria-label={gettext('Filter')}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && filtered.length === 1) {
                  e.preventDefault();
                  choose(filtered[0]);
                }
              }}
            />
          )}
          <ul role="listbox" aria-label={ariaLabel} className="min-h-0 overflow-y-auto">
            {filtered.map((option) => {
              const selected = option === value;
              return (
                <li key={option}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={selected}
                    className={`flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-left text-sm hover:bg-base-200 focus:bg-base-200 focus:outline-none ${
                      selected ? 'font-medium' : ''
                    }`}
                    onClick={() => choose(option)}
                  >
                    <Icon
                      name="check"
                      className={`h-4 w-4 shrink-0 text-primary ${selected ? '' : 'invisible'}`}
                      aria-hidden="true"
                    />
                    <span className="truncate" title={option}>
                      {option}
                    </span>
                  </button>
                </li>
              );
            })}
            {filtered.length === 0 && (
              <li className="px-3 py-1.5 text-sm text-base-content/70">{gettext('No matches')}</li>
            )}
          </ul>
          <div className="mt-1 border-t border-base-300 pt-1">
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
              <button
                type="button"
                className="flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-left text-sm text-primary hover:bg-base-200 focus:bg-base-200 focus:outline-none"
                onClick={() => setCreating(true)}
                data-testid={testId ? `${testId}-new` : undefined}
              >
                <Icon name="plus" className="h-4 w-4 shrink-0" aria-hidden="true" />
                {createLabel}
              </button>
            )}
          </div>
        </div>,
        portalTarget(triggerRef.current),
      )
    : null;

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
      {panel}
    </>
  );
};

export default ChipSelect;
