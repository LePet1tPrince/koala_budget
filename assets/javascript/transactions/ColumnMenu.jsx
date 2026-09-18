/* globals gettext */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

import Icon from '../common/Icon';
import Spinner from '../common/Spinner';
import { portalTarget, useAnchoredPosition } from '../common/popoverPosition';

const VALUE_SEARCH_DEBOUNCE_MS = 250;

/** The empty-string facet value stands for "this row has nothing in this column". */
const NO_VALUE = '';

/**
 * Sort + value-filter menu for one column of the transactions table.
 *
 * The values come from the server, not from the rows on screen: the table
 * pages in as you scroll, so a list built from loaded rows would offer the
 * first page's payees and quietly pretend the rest of the ledger has none.
 * `fetchFacets` asks the API for the column's distinct values under the
 * filters that are currently applied elsewhere.
 *
 * Selections are staged locally and committed with Apply -- each commit is a
 * round trip to re-query the ledger, so ticking six payees shouldn't cost six
 * of them.
 *
 * Props:
 *   column       – { key, label, kind, formatValue }
 *   selected     – array of currently applied values (wire strings)
 *   sort         – { key, dir } currently applied to the table, or null
 *   onSortChange – (sort | null) => void
 *   onApply      – (values) => void, empty array clears the column's filter
 *   fetchFacets  – (columnKey, query) => Promise<{values, truncated}>
 */
const ColumnMenu = ({ column, selected, sort, onSortChange, onApply, fetchFacets }) => {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(() => new Set(selected));
  const [query, setQuery] = useState('');
  const [facets, setFacets] = useState(null);
  const [truncated, setTruncated] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const anchorRef = useRef(null);
  const panelRef = useRef(null);
  const { style, measure } = useAnchoredPosition(open, anchorRef, panelRef);

  const isSorted = sort && sort.key === column.key;
  const activeCount = selected.length;

  const close = useCallback(() => setOpen(false), []);

  // Re-stage from what's applied whenever the menu opens, so cancelling and
  // reopening never resurrects an abandoned draft.
  useEffect(() => {
    if (!open) return;
    setDraft(new Set(selected));
    setQuery('');
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!open) return undefined;
    let cancelled = false;
    const handle = setTimeout(async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await fetchFacets(column.key, query.trim());
        if (cancelled) return;
        setFacets(data.values || []);
        setTruncated(Boolean(data.truncated));
      } catch (err) {
        if (!cancelled) {
          setFacets([]);
          setError(err.message);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, facets === null ? 0 : VALUE_SEARCH_DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
  }, [open, query, column.key, fetchFacets]); // eslint-disable-line react-hooks/exhaustive-deps

  // A shorter list makes the panel shorter; re-measure so it stays anchored.
  useEffect(() => {
    if (open) measure();
  }, [open, facets, measure]);

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (e) => {
      if (anchorRef.current?.contains(e.target) || panelRef.current?.contains(e.target)) return;
      close();
    };
    const onKeyDown = (e) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        close();
      }
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open, close]);

  const rows = facets || [];

  const labelFor = useCallback(
    (row) => (row.value === NO_VALUE ? gettext('(none)') : column.formatValue(row.value, row.label)),
    [column]
  );

  const allVisibleTicked = useMemo(
    () => rows.length > 0 && rows.every((row) => draft.has(row.value)),
    [rows, draft]
  );

  const toggle = (value) => {
    setDraft((prev) => {
      const next = new Set(prev);
      if (next.has(value)) next.delete(value);
      else next.add(value);
      return next;
    });
  };

  const selectAllVisible = () => {
    setDraft((prev) => {
      const next = new Set(prev);
      rows.forEach((row) => next.add(row.value));
      return next;
    });
  };

  const apply = () => {
    onApply(Array.from(draft));
    close();
  };

  const clearFilter = () => {
    setDraft(new Set());
    onApply([]);
    close();
  };

  const setSort = (dir) => {
    onSortChange(isSorted && sort.dir === dir ? null : { key: column.key, dir });
    close();
  };

  const panel = (
    <div
      ref={panelRef}
      role="dialog"
      aria-label={gettext('Filter and sort {column}').replace('{column}', column.label)}
      data-testid={`column-menu-${column.key}`}
      className="fixed z-[60] flex w-72 max-w-[calc(100vw-1rem)] flex-col rounded-xl border border-base-300 bg-base-100 p-1.5 shadow-lg"
      style={style ? { top: style.top, left: style.left, maxHeight: style.maxHeight } : { visibility: 'hidden' }}
    >
      <button
        type="button"
        className={`flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-left text-sm hover:bg-base-200 ${
          isSorted && sort.dir === 'asc' ? 'text-primary font-medium' : ''
        }`}
        onClick={() => setSort('asc')}
        data-testid={`sort-asc-${column.key}`}
      >
        <Icon name="arrow-up" className="w-3.5 h-3.5 shrink-0" />
        {column.ascLabel || gettext('Sort ascending')}
      </button>
      <button
        type="button"
        className={`flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-left text-sm hover:bg-base-200 ${
          isSorted && sort.dir === 'desc' ? 'text-primary font-medium' : ''
        }`}
        onClick={() => setSort('desc')}
        data-testid={`sort-desc-${column.key}`}
      >
        <Icon name="arrow-down" className="w-3.5 h-3.5 shrink-0" />
        {column.descLabel || gettext('Sort descending')}
      </button>

      <div className="my-1.5 border-t border-base-300" />

      {column.searchable && (
        <label className="relative block px-1.5">
          <Icon
            name="search"
            className="pointer-events-none absolute left-3.5 top-1/2 z-10 w-3.5 h-3.5 -translate-y-1/2 text-base-content/40"
          />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={gettext('Search values…')}
            className="input input-bordered input-sm w-full pl-7"
            data-testid={`column-value-search-${column.key}`}
          />
        </label>
      )}

      <div className="flex items-center justify-between px-3 py-1.5 text-xs">
        <button
          type="button"
          className="link link-primary"
          onClick={selectAllVisible}
          disabled={rows.length === 0 || allVisibleTicked}
        >
          {gettext('Select all')}
        </button>
        <span className="text-base-content/70" data-testid={`column-selected-count-${column.key}`}>
          {draft.size > 0
            ? gettext('{n} selected').replace('{n}', draft.size)
            : gettext('Showing all')}
        </span>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {loading && rows.length === 0 && (
          <div className="flex items-center gap-2 px-3 py-4 text-sm text-base-content/70">
            <Spinner size="xs" /> {gettext('Loading values…')}
          </div>
        )}

        {error && <div className="px-3 py-3 text-sm text-error">{error}</div>}

        {!loading && !error && rows.length === 0 && (
          <div className="px-3 py-4 text-sm text-base-content/70">{gettext('No values match.')}</div>
        )}

        {rows.map((row) => (
          <label
            key={row.value}
            className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-1.5 text-sm hover:bg-base-200"
          >
            <input
              type="checkbox"
              className="checkbox checkbox-xs rounded-sm"
              checked={draft.has(row.value)}
              onChange={() => toggle(row.value)}
            />
            <span
              data-testid="column-value-label"
              className={`flex-1 truncate ${row.value === NO_VALUE ? 'italic text-base-content/70' : ''}`}
            >
              {labelFor(row)}
            </span>
            <span className="badge badge-sm badge-ghost tabular-nums">{row.count}</span>
          </label>
        ))}

        {truncated && (
          <div className="px-3 py-2 text-xs text-base-content/70">
            {gettext('Only the first values are listed — search to narrow them down.')}
          </div>
        )}
      </div>

      <div className="mt-1.5 flex items-center justify-end gap-2 border-t border-base-300 px-1.5 pt-1.5">
        <button
          type="button"
          className="btn btn-ghost btn-xs"
          onClick={clearFilter}
          data-testid={`column-clear-${column.key}`}
        >
          {gettext('Clear')}
        </button>
        <button
          type="button"
          className="btn btn-primary btn-xs"
          onClick={apply}
          data-testid={`column-apply-${column.key}`}
        >
          {gettext('Apply')}
        </button>
      </div>
    </div>
  );

  return (
    <>
      <button
        type="button"
        ref={anchorRef}
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={gettext('Filter and sort {column}').replace('{column}', column.label)}
        data-testid={`column-menu-btn-${column.key}`}
        className={`inline-flex h-5 w-5 shrink-0 items-center justify-center rounded transition-colors hover:bg-base-300 hover:text-base-content ${
          activeCount > 0 || isSorted ? 'text-primary' : 'text-base-content/40'
        } ${open ? 'bg-base-300 text-base-content' : ''}`}
      >
        <Icon name="chevron-down" className="w-3.5 h-3.5" />
      </button>
      {open && createPortal(panel, portalTarget(anchorRef.current))}
    </>
  );
};

export default ColumnMenu;
