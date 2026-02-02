/* globals SERVER_URL_BASE */
'use strict';

import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import TransactionsTable from './TransactionsTable';
import { getApiConfiguration, getApiHeaders } from '../api';

const TransactionsApp = () => {
  const [transactions, setTransactions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const apiUrls = JSON.parse(document.getElementById('api-urls').textContent);

  useEffect(() => {
    const fetchTransactions = async () => {
      try {
        const response = await fetch(apiUrls.transactions_list, {
          headers: getApiHeaders(),
        });
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        const data = await response.json();
        setTransactions(data);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchTransactions();
  }, []);

  if (loading) {
    return (
      <div className="text-center py-12 text-gray-500">
        Loading transactions...
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-center py-12 text-red-500">
        Error loading transactions: {error}
      </div>
    );
  }

  return <TransactionsTable transactions={transactions} />;
};

// Mount the React app
const domContainer = document.querySelector('#transactions-app');
if (domContainer) {
  const root = createRoot(domContainer);
  root.render(<TransactionsApp />);
}
