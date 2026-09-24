/* globals SERVER_URL_BASE */
'use strict';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import TransactionsTable from './TransactionsTable';
import { getApiConfiguration, getApiHeaders } from '../api';

const SEARCH_DEBOUNCE_MS = 300;

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
  const [columnFilters, setColumnFilters] = useState(() => {
    // A link can open the page already filtered (a goal's "see its spending").
    const el = document.getElementById('initial-filters');
    return el ? JSON.parse(el.textContent) : {};
  });
  // { key, dir } or null for the API's default newest-first ordering.
  const [sort, setSort] = useState(null);

  const apiUrls = JSON.parse(document.getElementById('api-urls').textContent);

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
  }, [filterParams, sort]);

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
    />
  );
};

// Mount the React app
const domContainer = document.querySelector('#transactions-app');
if (domContainer) {
  const root = createRoot(domContainer);
  root.render(<TransactionsApp />);
}
