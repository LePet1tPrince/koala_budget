/* globals gettext */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

import Icon from '../common/Icon';
import Spinner from '../common/Spinner';
import { portalTarget, useAnchoredPosition } from '../common/popoverPosition';

const VALUE_SEARCH_DEBOUNCE_MS = 250;

/** The empty-string facet value stands for "this row has nothing in this column". */
const NO_VALUE = '';

const hasChildren = (node) => Array.isArray(node.children) && node.children.length > 0;

/** Does anything below `node` carry a ticked value? Drives the tri-state box. */
const anyDescendantSelected = (node, draft) =>
  hasChildren(node) &&
  node.children.some((child) => draft.has(child.value) || anyDescendantSelected(child, draft));

/** Every value at or below `node`, so ticking a branch can clear what it subsumes. */
const subtreeValues = (node) => [
  node.value,
  ...(hasChildren(node) ? node.children.flatMap(subtreeValues) : []),
];

/**
 * One row of a hierarchical value list.
 *
 * A branch is a filter value in its own right — ticking 2025 means "every date
 * in 2025", not "these 300 days", which is what keeps three selected years out
 * of the query string. A node already covered by a ticked ancestor therefore
 * reads as checked but is disabled: untick the ancestor to pick inside it.
 * Subtracting one month from a selected year would need a filter language that
 * can say "except", and the tree is the wrong place to invent one.
 */
const TreeRow = ({ node, depth, draft, expanded, impliedBy, onToggleExpand, onToggle, label }) => {
  const branch = hasChildren(node);
  const open = expanded.has(node.value);
  const selected = draft.has(node.value);
  const implied = Boolean(impliedBy);
  const partial = !selected && !implied && anyDescendantSelected(node, draft);

  return (
    <>
      <div
        className="flex items-center gap-1 rounded-lg pr-3 text-sm hover:bg-base-200"
        style={{ paddingLeft: `${0.75 + depth * 1.1}rem` }}
      >
        {branch ? (
          <button
            type="button"
            className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded text-base-content/40 hover:text-base-content"
            onClick={() => onToggleExpand(node.value)}
            aria-expanded={open}
            aria-label={open ? gettext('Collapse') : gettext('Expand')}
            data-testid={`tree-toggle-${node.value}`}
          >
            <Icon name="chevron-right" className={`w-3.5 h-3.5 transition-transform ${open ? 'rotate-90' : ''}`} />
          </button>
        ) : (
          <span className="h-5 w-5 shrink-0" />
        )}

        <label
          className={`flex flex-1 items-center gap-2 py-1.5 ${implied ? 'cursor-default' : 'cursor-pointer'}`}
          title={implied ? gettext('Included by “{parent}”').replace('{parent}', impliedBy) : undefined}
        >
          <input
            type="checkbox"
            className="checkbox checkbox-xs rounded-sm"
            checked={selected || implied}
            disabled={implied}
            ref={(el) => {
              if (el) el.indeterminate = partial;
            }}
            onChange={() => onToggle(node)}
          />
          <span className={`flex-1 truncate ${branch ? 'font-medium' : ''}`} data-testid="column-value-label">
            {label(node)}
          </span>
          <span className="badge badge-sm badge-ghost tabular-nums">{node.count}</span>
        </label>
      </div>

      {branch &&
        open &&
        node.children.map((child) => (
          <TreeRow
            key={child.value}
            node={child}
            depth={depth + 1}
            draft={draft}
            expanded={expanded}
            impliedBy={impliedBy || (selected ? label(node) : null)}
            onToggleExpand={onToggleExpand}
            onToggle={onToggle}
            label={label}
          />
        ))}
    </>
  );
};

/**
 * Sort + value-filter menu for one column of the transactions table.
 *
 * The values come from the server, not from the rows on screen: the table
 * pages in as you scroll, so a list built from loaded rows would offer the
 * first page's payees and quietly pretend the rest of the ledger has none.
 * `fetchFacets` asks the API for the column's values under the filters that
 * are currently applied elsewhere; some columns answer with a flat list and
 * some (dates, the two account columns) with a tree.
 *
 * Selections are staged locally and committed with Apply — each commit is a
 * round trip to re-query the ledger, so ticking six payees shouldn't cost six
 * of them. `Select all` / `Clear` act on the staged selection, so a long
 * selection can be thrown away and restarted without closing the menu.
 *
 * Props:
 *   column       – { key, label, formatValue, ascLabel, descLabel, searchable }
 *   selected     – array of currently applied `{ value, label }`
 *   sort         – { key, dir } currently applied to the table, or null
 *   onSortChange – (sort | null) => void
 *   onApply      – (entries) => void, empty array clears the column's filter
 *   fetchFacets  – (columnKey, query) => Promise<{values, hierarchical, truncated}>
 */
const ColumnMenu = ({ column, selected, sort, onSortChange, onApply, fetchFacets }) => {
  const [open, setOpen] = useState(false);
  // value -> label, so Apply can hand the chip bar something readable for a
  // branch token like `g:12` that no client-side formatter could decode.
  const [draft, setDraft] = useState(() => new Map());
  const [expanded, setExpanded] = useState(() => new Set());
  const [query, setQuery] = useState('');
  const [facets, setFacets] = useState(null);
  const [hierarchical, setHierarchical] = useState(false);
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
    setDraft(new Map(selected.map((entry) => [entry.value, entry.label])));
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
        setHierarchical(Boolean(data.hierarchical));
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
  }, [open, facets, expanded, measure]);

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

  /** What a node reads as in the list. A tree's labels arrive display-ready. */
  const labelOf = useCallback(
    (node) => {
      if (hierarchical) return node.label;
      if (node.value === NO_VALUE) return gettext('(none)');
      return column.formatValue(node.value, node.label);
    },
    [column, hierarchical]
  );

  /** What the applied-filter chip says — "Feb" alone means nothing outside its year. */
  const chipLabelOf = useCallback(
    (node) => (hierarchical ? node.full || node.label : labelOf(node)),
    [hierarchical, labelOf]
  );

  const toggle = (node) => {
    setDraft((prev) => {
      const next = new Map(prev);
      if (next.has(node.value)) {
        next.delete(node.value);
      } else {
        // Ticking a branch subsumes anything under it, so drop the redundant
        // descendants rather than sending both to the API.
        subtreeValues(node).forEach((value) => next.delete(value));
        next.set(node.value, chipLabelOf(node));
      }
      return next;
    });
  };

  const toggleExpand = (value) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(value)) next.delete(value);
      else next.add(value);
      return next;
    });
  };

  // Ticking every top-level node covers the whole tree in one value per root.
  const allRootsTicked = rows.length > 0 && rows.every((row) => draft.has(row.value));

  const selectAll = () => {
    setDraft((prev) => {
      const next = new Map(prev);
      rows.forEach((row) => {
        subtreeValues(row).forEach((value) => next.delete(value));
        next.set(row.value, chipLabelOf(row));
      });
      return next;
    });
  };

  const clearDraft = () => setDraft(new Map());

  const apply = () => {
    onApply(Array.from(draft, ([value, label]) => ({ value, label })));
    close();
  };

  const setSort = (dir) => {
    onSortChange(isSorted && sort.dir === dir ? null : { key: column.key, dir });
    close();
  };

  // While searching, show every match rather than making the user open each
  // branch to find out whether the thing they typed is in there.
  const effectiveExpanded = useMemo(() => {
    if (!query.trim() || !hierarchical) return expanded;
    const all = new Set(expanded);
    const walk = (nodes) =>
      nodes.forEach((node) => {
        if (hasChildren(node)) {
          all.add(node.value);
          walk(node.children);
        }
      });
    walk(rows);
    return all;
  }, [query, hierarchical, expanded, rows]);

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
        {column.ascLabel}
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
        {column.descLabel}
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

      <div className="flex items-center gap-2 px-3 py-1.5 text-xs">
        <button
          type="button"
          className="link link-primary"
          onClick={selectAll}
          disabled={rows.length === 0 || allRootsTicked}
          data-testid={`column-select-all-${column.key}`}
        >
          {gettext('Select all')}
        </button>
        <span className="text-base-content/40">·</span>
        <button
          type="button"
          className="link link-primary"
          onClick={clearDraft}
          disabled={draft.size === 0}
          data-testid={`column-clear-selection-${column.key}`}
        >
          {gettext('Clear')}
        </button>
        <span className="ml-auto text-base-content/70" data-testid={`column-selected-count-${column.key}`}>
          {draft.size > 0 ? gettext('{n} selected').replace('{n}', draft.size) : gettext('Showing all')}
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

        {rows.map((node) => (
          <TreeRow
            key={node.value}
            node={node}
            depth={0}
            draft={draft}
            expanded={effectiveExpanded}
            impliedBy={null}
            onToggleExpand={toggleExpand}
            onToggle={toggle}
            label={labelOf}
          />
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
          onClick={close}
          data-testid={`column-cancel-${column.key}`}
        >
          {gettext('Cancel')}
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
