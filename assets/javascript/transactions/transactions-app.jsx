/* globals gettext */
'use strict';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import TransactionsTable from './TransactionsTable';
import TransactionEditModal from './TransactionEditModal';
import { getTransactionsApi } from './transactionsApi';
import Toast from '../common/Toast';
import { getApiHeaders } from '../api';

const SEARCH_DEBOUNCE_MS = 300;

/** Read a json_script tag, tolerating a page that doesn't render it. */
const readJson = (id, fallback) => {
  const node = document.getElementById(id);
  return node ? JSON.parse(node.textContent) : fallback;
};

/**
 * Which filters an edit could have moved a row out of.
 *
 * `payee` is `payee_name` on a row and `payee` in the payload; the account
 * columns are two views of one edit, since changing either side of a transaction
 * can move it out of a debit *or* a credit filter.
 */
const FILTER_KEYS_FOR = {
  date: ['date'],
  payee: ['payee'],
  description: ['description'],
  account_id: ['debit_account', 'credit_account'],
  category_id: ['debit_account', 'credit_account'],
  splits: ['debit_account', 'credit_account'],
  remove_split: ['debit_account', 'credit_account'],
  inflow: ['amount', 'debit_account', 'credit_account'],
  outflow: ['amount', 'debit_account', 'credit_account'],
};

const TransactionsApp = () => {
  const [transactions, setTransactions] = useState([]);
  const [nextUrl, setNextUrl] = useState(null);
  const [initialLoading, setInitialLoading] = useState(true);
  const [refetching, setRefetching] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(null);
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  // { [columnKey]: [{ value, label }] } -- the values ticked in each column's
  // menu. An absent or empty entry means that column isn't filtering anything.
  // The label rides along because a hierarchical column's value is a branch
  // token (`2025-03`, `g:12`) that nothing on the client could turn back into
  // "Mar 2025" or "Employment Income".
  const [columnFilters, setColumnFilters] = useState({});
  // { key, dir } or null for the API's default newest-first ordering.
  const [sort, setSort] = useState(null);

  // The transactions the edit modal is open on. An array from the outset: the
  // modal already handles a selection, so wiring checkboxes up later changes
  // what fills this and nothing else.
  const [editing, setEditing] = useState([]);
  const [toast, setToast] = useState(null);

  const apiUrls = JSON.parse(document.getElementById('api-urls').textContent);
  const teamSlug = readJson('team-slug', '');
  const allAccounts = useMemo(() => readJson('all-accounts', []), []);
  const allPayees = useMemo(() => readJson('all-payees', []), []);
  const api = useMemo(() => getTransactionsApi(teamSlug), [teamSlug]);

  // Bumped to force the list effect to re-run when an edit moved a row out of
  // the filters currently applied — the params themselves have not changed, so
  // nothing else would.
  const [reloadToken, setReloadToken] = useState(0);

  // Debounce free-text search so we don't hit the API on every keystroke.
  useEffect(() => {
    const handle = setTimeout(() => setSearch(searchInput.trim()), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [searchInput]);

  // Every filter runs server-side against the whole ledger, so the params are
  // built once here and shared by the row fetch and the column value lists.
  const filterParams = useMemo(() => {
    const params = new URLSearchParams();
    if (search) params.set('search', search);
    if (startDate) params.set('start_date', startDate);
    if (endDate) params.set('end_date', endDate);
    Object.entries(columnFilters).forEach(([key, entries]) => {
      entries.forEach((entry) => params.append(`f_${key}`, entry.value));
    });
    return params;
  }, [search, startDate, endDate, columnFilters]);

  // Any change to the filters or the ordering re-fetches from page 1 rather
  // than re-arranging the rows already loaded, which would only sort the pages
  // the user happens to have scrolled through.
  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setRefetching(true);
      setError(null);
      try {
        const params = new URLSearchParams(filterParams);
        if (sort) {
          params.set('sort', sort.key);
          params.set('dir', sort.dir);
        }
        const qs = params.toString();
        const url = qs ? `${apiUrls.transactions_list}?${qs}` : apiUrls.transactions_list;

        const response = await fetch(url, { headers: getApiHeaders() });
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        const data = await response.json();
        if (cancelled) return;

        setTransactions(data.results || []);
        setNextUrl(data.next || null);
      } catch (err) {
        if (!cancelled) setError(err.message);
      } finally {
        if (!cancelled) {
          setInitialLoading(false);
          setRefetching(false);
        }
      }
    };

    load();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterParams, sort, reloadToken]);

  const handleLoadMore = useCallback(async () => {
    if (!nextUrl || loadingMore) return;
    setLoadingMore(true);
    try {
      const response = await fetch(nextUrl, { headers: getApiHeaders() });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const data = await response.json();
      setTransactions((prev) => [...prev, ...(data.results || [])]);
      setNextUrl(data.next || null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoadingMore(false);
    }
  }, [nextUrl, loadingMore]);

  const handleDateApply = useCallback((start, end) => {
    setStartDate(start);
    setEndDate(end);
  }, []);

  const handleColumnFilterChange = useCallback((columnKey, entries) => {
    setColumnFilters((prev) => {
      const next = { ...prev };
      if (entries.length === 0) delete next[columnKey];
      else next[columnKey] = entries;
      return next;
    });
  }, []);

  const handleClearColumnFilters = useCallback(() => setColumnFilters({}), []);

  /**
   * The distinct values of one column, for its filter menu.
   *
   * The column's own selection is deliberately still sent: the server drops it
   * when building the list (a column that only offered the values you'd
   * already ticked couldn't be un-ticked) but uses it for every other column's
   * counts.
   */
  const fetchFacets = useCallback(
    async (columnKey, query) => {
      const params = new URLSearchParams(filterParams);
      params.set('column', columnKey);
      if (query) params.set('q', query);
      const response = await fetch(`${apiUrls.transactions_facets}?${params.toString()}`, {
        headers: getApiHeaders(),
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      return response.json();
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [filterParams]
  );

  // --- editing ---------------------------------------------------------

  const openEditor = useCallback(
    async (row) => {
      // The row the table holds is a display projection -- it has account names
      // but no ids, and no split legs to edit. The detail fetch is what the
      // modal actually opens on.
      try {
        const detail = await api.fetchDetail(row.id);
        setEditing([detail]);
      } catch (err) {
        setToast({ message: err.message, severity: 'error' });
      }
    },
    [api]
  );

  /**
   * Fold the server's updated rows back into the list.
   *
   * A row whose edit touched a column the list is currently filtered, sorted or
   * date-ranged by may no longer belong where it is -- or at all -- so those
   * refetch rather than patch. Everything else patches, which is the common case
   * and costs no round trip.
   */
  const absorb = useCallback(
    (rows, changedKeys) => {
      const affected = changedKeys.flatMap((key) => FILTER_KEYS_FOR[key] || []);
      const movesTheRow =
        affected.some((key) => (columnFilters[key] || []).length > 0 || sort?.key === key) ||
        (changedKeys.includes('date') && Boolean(startDate || endDate));

      if (movesTheRow) {
        setReloadToken((n) => n + 1);
        return;
      }
      const byId = new Map(rows.map((row) => [row.id, row]));
      setTransactions((prev) => prev.map((row) => byId.get(row.id) ?? row));
    },
    [columnFilters, sort, startDate, endDate]
  );

  const handleSave = useCallback(
    async (ids, updates) => {
      const { results } = await api.saveEdits(ids, updates);
      absorb(results, Object.keys(updates));
      setToast({
        message: ids.length > 1 ? gettext('Transactions updated') : gettext('Transaction updated'),
        severity: 'success',
      });
    },
    [api, absorb]
  );

  const handleDelete = useCallback(
    async (ids) => {
      await api.deleteTransactions(ids);
      const gone = new Set(ids);
      setTransactions((prev) => prev.filter((row) => !gone.has(row.id)));
      setToast({ message: gettext('Transaction deleted'), severity: 'success' });
    },
    [api]
  );

  const handleSetStatus = useCallback(
    async (ids, statusValue) => {
      const { results } = await api.setStatus(ids, statusValue);
      absorb(results, ['status']);
      setToast({
        message: statusValue === 'void' ? gettext('Transaction voided') : gettext('Transaction restored'),
        severity: 'success',
      });
    },
    [api, absorb]
  );

  if (initialLoading) {
    return (
      <div className="text-center py-12 text-base-content/70">
        Loading transactions...
      </div>
    );
  }

  if (error && transactions.length === 0) {
    return (
      <div className="text-center py-12 text-red-500">
        Error loading transactions: {error}
      </div>
    );
  }

  return (
    <>
      <TransactionsTable
        transactions={transactions}
        search={searchInput}
        onSearchChange={setSearchInput}
        startDate={startDate}
        endDate={endDate}
        onDateApply={handleDateApply}
        columnFilters={columnFilters}
        onColumnFilterChange={handleColumnFilterChange}
        onClearColumnFilters={handleClearColumnFilters}
        sort={sort}
        onSortChange={setSort}
        fetchFacets={fetchFacets}
        onLoadMore={handleLoadMore}
        hasMore={Boolean(nextUrl)}
        loadingMore={loadingMore}
        refetching={refetching}
        error={transactions.length > 0 ? error : null}
        onEditRow={openEditor}
      />

      <TransactionEditModal
        open={editing.length > 0}
        transactions={editing}
        allAccounts={allAccounts}
        allPayees={allPayees}
        teamSlug={teamSlug}
        onSave={handleSave}
        onDelete={handleDelete}
        onSetStatus={handleSetStatus}
        onClose={() => setEditing([])}
      />

      <Toast
        open={Boolean(toast)}
        message={toast?.message || ''}
        severity={toast?.severity || 'info'}
        onClose={() => setToast(null)}
        testId="transactions-toast"
      />
    </>
  );
};

// Mount the React app
const domContainer = document.querySelector('#transactions-app');
if (domContainer) {
  const root = createRoot(domContainer);
  root.render(<TransactionsApp />);
}
