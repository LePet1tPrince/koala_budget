/* globals gettext */
import React, { useEffect, useState } from 'react';

import AccountCard from './AccountCard';
import { JournalApi } from 'api-client';
import TransactionTable from './TransactionTable';
import { getApiConfiguration } from '../../api';

/**
 * JournalApp - Main application component
 * Manages account selection and transaction CRUD operations
 */
const JournalApp = ({ accounts, allAccounts, allPayees, apiUrls, teamSlug }) => {
  const [selectedAccount, setSelectedAccount] = useState(null);
  const [transactions, setTransactions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Create API client instance
  const apiClient = new JournalApi(getApiConfiguration(SERVER_URL_BASE));

  // Load transactions when account is selected
  useEffect(() => {
    if (selectedAccount) {
      loadTransactions();
    } else {
      setTransactions([]);
    }
  }, [selectedAccount]);

  const loadTransactions = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await apiClient.simpleTransactionsList({
        teamSlug: teamSlug,
        // Note: The API doesn't support filtering by account yet, so we'll filter client-side
      });
      // Filter transactions by selected account
      const filteredTransactions = response.results.filter(
        (t) => t.account === selectedAccount.account_id
      );
      setTransactions(filteredTransactions);
    } catch (err) {
      console.error('Failed to load transactions:', err);
      setError(gettext('Failed to load transactions'));
    } finally {
      setLoading(false);
    }
  };

  const handleAccountSelect = (account) => {
    setSelectedAccount(account);
  };

  const handleAddTransaction = async (transactionData) => {
    console.log('=== handleAddTransaction called ===');
    console.log('Transaction data received:', transactionData);
    console.log('Team slug:', teamSlug);
    console.log('API client:', apiClient);

    try {
      // Convert date string to Date object for the API client
      const apiData = {
        ...transactionData,
        date: new Date(transactionData.date),
      };

      // Convert empty string payee to null
      if (apiData.payee === '') {
        apiData.payee = null;
      }

      console.log('Calling apiClient.simpleTransactionsCreate with:', {
        teamSlug: teamSlug,
        simpleTransaction: apiData,
      });

      const newTransaction = await apiClient.simpleTransactionsCreate({
        teamSlug: teamSlug,
        simpleTransaction: apiData,
      });

      console.log('Transaction created successfully:', newTransaction);
      setTransactions([...transactions, newTransaction]);
    } catch (err) {
      console.error('=== ERROR in handleAddTransaction ===');
      console.error('Error object:', err);
      console.error('Error message:', err.message);
      console.error('Error stack:', err.stack);

      // If it's a response error, log the response details
      if (err.response) {
        console.error('Response status:', err.response.status);
        console.error('Response headers:', err.response.headers);
        console.error('Response data:', err.response.data);
      }

      // If it's a request error
      if (err.request) {
        console.error('Request:', err.request);
      }

      throw err;
    }
  };

  const handleUpdateTransaction = async (transactionId, transactionData) => {
    try {
      // Convert date string to Date object if present
      const apiData = { ...transactionData };
      if (apiData.date && typeof apiData.date === 'string') {
        apiData.date = new Date(apiData.date);
      }

      // Convert empty string payee to null
      if (apiData.payee === '') {
        apiData.payee = null;
      }

      const updatedTransaction = await apiClient.simpleTransactionsPartialUpdate({
        teamSlug: teamSlug,
        id: transactionId,
        patchedSimpleTransaction: apiData,
      });
      setTransactions(
        transactions.map((t) => (t.id === transactionId ? updatedTransaction : t))
      );
    } catch (err) {
      console.error('Failed to update transaction:', err);
      throw err;
    }
  };

  const handleDeleteTransaction = async (transactionId) => {
    try {
      await apiClient.simpleTransactionsDestroy({
        teamSlug: teamSlug,
        id: transactionId,
      });
      setTransactions(transactions.filter((t) => t.id !== transactionId));
    } catch (err) {
      console.error('Failed to delete transaction:', err);
      throw err;
    }
  };

  return (
    <div className="space-y-6">
      {/* Account Selection Cards */}
      <section className="app-card">
        <h2 className="pg-subtitle mb-4">{gettext('Select Account')}</h2>
        {accounts.length === 0 ? (
          <div className="alert alert-warning">
            <i className="fa fa-exclamation-triangle"></i>
            <span>
              {gettext('No accounts with bank feeds found. Please add an account with a bank feed to get started.')}
            </span>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {accounts.map((account) => (
              <AccountCard
                key={account.account_id}
                account={account}
                isSelected={selectedAccount?.account_id === account.account_id}
                onClick={handleAccountSelect}
              />
            ))}
          </div>
        )}
      </section>

      {/* Transactions Table */}
      {selectedAccount && (
        <section className="app-card">
          <h2 className="pg-subtitle mb-4">
            {gettext('Transactions for')} {selectedAccount.name}
          </h2>
          {error && (
            <div className="alert alert-error mb-4">
              <i className="fa fa-exclamation-circle"></i>
              <span>{error}</span>
            </div>
          )}
          {loading ? (
            <div className="flex justify-center items-center py-12">
              <span className="loading loading-spinner loading-lg"></span>
            </div>
          ) : (
            <TransactionTable
              transactions={transactions}
              selectedAccount={selectedAccount}
              allAccounts={allAccounts}
              allPayees={allPayees}
              onAdd={handleAddTransaction}
              onUpdate={handleUpdateTransaction}
              onDelete={handleDeleteTransaction}
            />
          )}
        </section>
      )}
    </div>
  );
};

export default JournalApp;
