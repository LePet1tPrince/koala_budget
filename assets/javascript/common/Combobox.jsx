import React, { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

import { portalTarget, useAnchoredPosition } from './popoverPosition';

/* globals gettext */

/**
 * Filterable combobox, replacing MUI's `Autocomplete` (restyle plan Phase 7).
 *
 * Two modes, matching the two ways `Autocomplete` was used here:
 *
 *  - object mode (default): `options` are objects, `value`/`onChange` carry the
 *    selected object or null, and `getGroup` optionally renders group headings.
 *  - `freeText`: `options` are strings offered as suggestions, and `value`/`onChange`
 *    carry whatever the user typed — MUI's `freeSolo`.
 *
 * The list is portaled and fixed-positioned rather than absolutely placed, because
 * daisyUI's `.modal-box` scrolls its overflow and would clip a dropdown near the
 * bottom of a form. It portals into the nearest ancestor `<dialog>` when there is
 * one: a `<dialog>` is painted in the browser's top layer, so a list portaled to
 * `document.body` would disappear *behind* the modal it belongs to.
 */
const Combobox = ({
  label,
  value,
  onChange,
  options = [],
  getLabel = (o) => (typeof o === 'string' ? o : (o?.label ?? '')),
  getGroup = null,
  getKey = (o) => (typeof o === 'string' ? o : o?.id),
  freeText = false,
  disabled = false,
  placeholder = '',
  error = '',
  helperText = '',
  testId,
}) => {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const rootRef = useRef(null);
  const inputRef = useRef(null);
  const listRef = useRef(null);
  const listId = useId();

  // In object mode the input shows the selection until the user starts typing;
  // in free-text mode the input *is* the value.
  const text = freeText ? (value ?? '') : open ? query : value ? getLabel(value) : '';

  const filtered = useMemo(() => {
    const needle = (freeText ? (value ?? '') : query).trim().toLowerCase();
    if (!needle) return options;
    return options.filter((o) => getLabel(o).toLowerCase().includes(needle));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [options, query, value, freeText]);

  const close = useCallback(() => {
    setOpen(false);
    setQuery('');
    setActive(0);
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (e) => {
      if (rootRef.current && !rootRef.current.contains(e.target) && !e.target.closest(`[data-combobox="${listId}"]`)) {
        close();
      }
    };
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [open, close, listId]);

  const { style: listStyle, measure } = useAnchoredPosition(open, rootRef, listRef, { matchWidth: true });

  useEffect(() => {
    if (open) measure();
  }, [open, filtered.length, measure]);

  const commit = (option) => {
    onChange(freeText ? getLabel(option) : option);
    close();
    inputRef.current?.blur();
  };

  const onKeyDown = (e) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!open) {
        setOpen(true);
        return;
      }
      const step = e.key === 'ArrowDown' ? 1 : -1;
      setActive((i) => Math.min(Math.max(i + step, 0), filtered.length - 1));
    } else if (e.key === 'Enter') {
      if (open && filtered[active]) {
        e.preventDefault();
        commit(filtered[active]);
      }
    } else if (e.key === 'Escape') {
      if (open) {
        // The list is the innermost dismissible, so Escape must close it alone.
        // A native <dialog> closes on Escape as a *default action* of the keydown,
        // not by propagation, so stopPropagation is not enough — without
        // preventDefault the whole modal closes out from under the list.
        e.preventDefault();
        e.stopPropagation();
        close();
      }
    }
  };

  // Group headings, in the order the options arrive — `buildCategoryOptions`
  // already sorts them, so no regrouping is needed.
  const rows = [];
  let lastGroup = null;
  filtered.forEach((option, i) => {
    if (getGroup) {
      const group = getGroup(option);
      if (group !== lastGroup) {
        rows.push({ kind: 'group', label: group, key: `g-${group}-${i}` });
        lastGroup = group;
      }
    }
    rows.push({
      kind: 'option',
      option,
      index: i,
      key: `o-${getKey(option) ?? i}`,
    });
  });

  const list = open
    ? createPortal(
        <ul
          ref={listRef}
          id={listId}
          data-combobox={listId}
          role="listbox"
          className="fixed z-[1200] overflow-y-auto rounded-xl border border-base-300 bg-base-100 p-1 shadow-lg"
          style={
            listStyle
              ? { ...listStyle, maxHeight: Math.min(listStyle.maxHeight, 256) }
              : // First paint measures the list, so keep it out of sight until placed.
                { top: 0, left: 0, visibility: 'hidden' }
          }
        >
          {rows.length === 0 && <li className="px-3 py-2 text-sm text-base-content/70">{gettext('No matches')}</li>}
          {rows.map((row) =>
            row.kind === 'group' ? (
              <li
                key={row.key}
                role="presentation"
                className="px-3 pt-2 pb-1 text-xs font-semibold uppercase tracking-wide text-base-content/70"
              >
                {row.label}
              </li>
            ) : (
              <li key={row.key}>
                <button
                  type="button"
                  role="option"
                  aria-selected={row.index === active}
                  className={`block w-full truncate rounded-lg px-3 py-2 text-left text-sm ${
                    row.index === active ? 'bg-base-200' : 'hover:bg-base-200'
                  }`}
                  onMouseEnter={() => setActive(row.index)}
                  onClick={() => commit(row.option)}
                >
                  {getLabel(row.option)}
                </button>
              </li>
            ),
          )}
        </ul>,
        portalTarget(rootRef.current),
      )
    : null;

  return (
    <label className="form-control w-full">
      {label && <span className="label-text mb-1 block text-sm text-base-content/70">{label}</span>}
      <div className="relative" ref={rootRef}>
        <input
          ref={inputRef}
          type="text"
          role="combobox"
          aria-expanded={open}
          aria-controls={open ? listId : undefined}
          aria-autocomplete="list"
          className={`input input-bordered w-full ${error ? 'input-error' : ''}`}
          disabled={disabled}
          placeholder={placeholder}
          value={text}
          data-testid={testId}
          onFocus={() => setOpen(true)}
          onChange={(e) => {
            setOpen(true);
            setActive(0);
            if (freeText) onChange(e.target.value);
            else setQuery(e.target.value);
          }}
          onKeyDown={onKeyDown}
        />
        {!freeText && value && !disabled && (
          <button
            type="button"
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded-full p-1 hover:bg-base-200"
            aria-label={gettext('Clear')}
            onClick={() => {
              onChange(null);
              close();
            }}
          >
            <svg className="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
              <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
            </svg>
          </button>
        )}
      </div>
      {(error || helperText) && (
        <span className={`mt-1 block text-xs ${error ? 'text-error' : 'text-base-content/70'}`}>
          {error || helperText}
        </span>
      )}
      {list}
    </label>
  );
};

export default Combobox;
