/* globals gettext */

import React, { useEffect, useState } from 'react';

import AccountCard from './AccountCard';
import { JournalApi } from 'api-client';
import LineTable from './LineTable';
import PlaidLinkButton from './PlaidLinkButton';
import { getApiConfiguration } from '../../api';

/**
 * LineApp - Main application component for managing lines
 * Manages account selection and line CRUD operations
 */
const LineApp = ({ accounts, allAccounts, allPayees, apiUrls, teamSlug }) => {
  const [selectedAccount, setSelectedAccount] = useState(null);
  const [lines, setLines] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);

  // Create API client instance
  const apiClient = new JournalApi(getApiConfiguration(SERVER_URL_BASE));

  // Load lines when account is selected
  useEffect(() => {
    if (selectedAccount) {
      loadLines();
    } else {
      setLines([]);
    }
  }, [selectedAccount]);

  const loadLines = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await apiClient.simpleLinesList({
        teamSlug: teamSlug,
        // Note: The API doesn't support filtering by account yet, so we'll filter client-side
      });
      // Filter lines by selected account
      const filteredLines = response.results.filter(
        (l) => l.account === selectedAccount.account_id
      );
      setLines(filteredLines);
    } catch (err) {
      console.error('Failed to load lines:', err);
      setError(gettext('Failed to load lines'));
    } finally {
      setLoading(false);
    }
  };

  const handleAccountSelect = (account) => {
    setSelectedAccount(account);
  };

  /**
   * Helper function to get CSRF token
   */
  const getCsrfToken = () => {
    const cookieMatch = document.cookie.match(/csrftoken=([^;]+)/);
    if (cookieMatch) {
      return cookieMatch[1];
    }
    const csrfInput = document.querySelector('[name=csrfmiddlewaretoken]');
    return csrfInput ? csrfInput.value : '';
  };

  /**
   * Refresh bank feed data from Plaid
   */
  const handleRefresh = async () => {
    if (!selectedAccount) return;

    setRefreshing(true);
    setError(null);

    try {
      // First, get the Plaid account for this ledger account
      const plaidAccountResponse = await fetch(
        `/a/${teamSlug}/plaid/api/accounts/?account=${selectedAccount.account_id}`
      );

      if (!plaidAccountResponse.ok) {
        throw new Error('Failed to fetch Plaid account');
      }

      const plaidAccountsData = await plaidAccountResponse.json();

      if (plaidAccountsData.results && plaidAccountsData.results.length > 0) {
        const plaidAccount = plaidAccountsData.results[0];

        // Trigger sync task for this Plaid item
        const syncResponse = await fetch(
          `/a/${teamSlug}/plaid/api/items/${plaidAccount.item}/sync/`,
          {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': getCsrfToken(),
            },
          }
        );

        if (!syncResponse.ok) {
          throw new Error('Failed to sync transactions');
        }

        // Wait a moment for sync to complete, then reload lines
        setTimeout(() => {
          loadLines();
          setRefreshing(false);
        }, 2000);
      } else {
        // No Plaid account linked to this ledger account
        setError(gettext('This account is not linked to a bank feed.'));
        setRefreshing(false);
      }
    } catch (err) {
      console.error('Failed to refresh:', err);
      setError(gettext('Failed to refresh bank feed. Please try again.'));
      setRefreshing(false);
    }
  };

  /**
   * Handle successful Plaid Link - reload page to show new accounts
   */
  const handlePlaidSuccess = () => {
    window.location.reload();
  };

  const handleAddLine = async (lineData) => {
    try {
      // Convert date string to Date object for the API client
      const apiData = {
        ...lineData,
        date: new Date(lineData.date),
      };

      // Convert empty string payee to null
      if (apiData.payee === '') {
        apiData.payee = null;
      }

      // Convert empty string inflow/outflow to 0
      if (apiData.inflow === '' || apiData.inflow === null || apiData.inflow === undefined) {
        apiData.inflow = '0';
      }
      if (apiData.outflow === '' || apiData.outflow === null || apiData.outflow === undefined) {
        apiData.outflow = '0';
      }

      const newLine = await apiClient.simpleLinesCreate({
        teamSlug: teamSlug,
        simpleLine: apiData,
      });

      setLines([...lines, newLine]);
    } catch (err) {
      console.error('Failed to add line:', err);
      throw err;
    }
  };

  const handleUpdateLine = async (lineId, lineData) => {
    try {
      // Convert date string to Date object if present
      const apiData = { ...lineData };
      if (apiData.date && typeof apiData.date === 'string') {
        apiData.date = new Date(apiData.date);
      }

      // Convert empty string payee to null
      if (apiData.payee === '') {
        apiData.payee = null;
      }

      // Convert empty string inflow/outflow to 0
      if (apiData.inflow === '' || apiData.inflow === null || apiData.inflow === undefined) {
        apiData.inflow = '0';
      }
      if (apiData.outflow === '' || apiData.outflow === null || apiData.outflow === undefined) {
        apiData.outflow = '0';
      }

      const updatedLine = await apiClient.simpleLinesPartialUpdate({
        teamSlug: teamSlug,
        id: lineId,
        patchedSimpleLine: apiData,
      });
      setLines(
        lines.map((l) => (l.lineId === lineId ? updatedLine : l))
      );
    } catch (err) {
      console.error('Failed to update line:', err);
      throw err;
    }
  };

  const handleDeleteLine = async (lineId) => {
    try {
      await apiClient.simpleLinesDestroy({
        teamSlug: teamSlug,
        id: lineId,
      });
      setLines(lines.filter((l) => l.lineId !== lineId));
    } catch (err) {
      console.error('Failed to delete line:', err);
      throw err;
    }
  };

  return (
    <div className="space-y-6">
      {/* Account Selection Cards */}
      <section className="app-card">
        <div className="flex justify-between items-center mb-4">
          <h2 className="pg-subtitle">{gettext('Select Account')}</h2>
          <PlaidLinkButton
            teamSlug={teamSlug}
            allAccounts={allAccounts}
            onSuccess={handlePlaidSuccess}
          />
        </div>
        {accounts.length === 0 ? (
          <div className="alert alert-warning">
            <i className="fa fa-exclamation-triangle"></i>
            <span>
              {gettext('No accounts with bank feeds found. Please link a bank account to get started.')}
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

      {/* Lines Table */}
      {selectedAccount && (
        <section className="app-card">
          <div className="flex justify-between items-center mb-4">
            <h2 className="pg-subtitle">
              {gettext('Lines for')} {selectedAccount.name}
            </h2>
            <button
              onClick={handleRefresh}
              disabled={refreshing || loading}
              className="btn btn-outline btn-sm"
            >
              {refreshing ? (
                <>
                  <span className="loading loading-spinner loading-xs"></span>
                  {gettext('Refreshing...')}
                </>
              ) : (
                <>
                  <i className="fa fa-refresh mr-2"></i>
                  {gettext('Refresh')}
                </>
              )}
            </button>
          </div>
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
            <LineTable
              lines={lines}
              selectedAccount={selectedAccount}
              allAccounts={allAccounts}
              allPayees={allPayees}
              onAdd={handleAddLine}
              onUpdate={handleUpdateLine}
              onDelete={handleDeleteLine}
            />
          )}
        </section>
      )}
    </div>
  );
};

export default LineApp;
