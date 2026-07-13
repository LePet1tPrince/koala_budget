/* globals SERVER_URL_BASE */
'use strict';

import React, { useCallback, useEffect, useState } from 'react';
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

  const apiUrls = JSON.parse(document.getElementById('api-urls').textContent);

  // Debounce free-text search so we don't hit the API on every keystroke.
  useEffect(() => {
    const handle = setTimeout(() => setSearch(searchInput.trim()), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [searchInput]);

  // Search and date filters run server-side against the whole ledger, so any
  // change to them re-fetches from page 1 rather than filtering loaded rows.
  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setRefetching(true);
      setError(null);
      try {
        const params = new URLSearchParams();
        if (search) params.set('search', search);
        if (startDate) params.set('start_date', startDate);
        if (endDate) params.set('end_date', endDate);
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
  }, [search, startDate, endDate]);

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

  if (initialLoading) {
    return (
      <div className="text-center py-12 text-gray-500">
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
