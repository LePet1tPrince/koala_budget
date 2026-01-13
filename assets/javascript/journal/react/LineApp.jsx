/* globals gettext */

import React, { useEffect, useState } from 'react';

import AccountCard from './AccountCard';
import BankFeedTable from './BankFeedTable';
import PlaidLinkButton from './PlaidLinkButton';

/**
 * LineApp - Main application component for managing lines
 * Manages account selection and bank feed operations
 */
const LineApp = ({ accounts, allAccounts, allPayees, teamSlug }) => {
  const [selectedAccount, setSelectedAccount] = useState(null);
  const [lines, setLines] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);

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
      // Use the new bank feed API endpoint that combines ledger and Plaid data
      const response = await fetch(
        `/a/${teamSlug}/plaid/api/bank-feed/?account=${selectedAccount.account_id}`
      );

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const data = await response.json();
      setLines(data);
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

  /**
   * Categorize bank feed rows (for Plaid transactions)
   */
  const handleCategorize = async (rows, categoryAccountId) => {
    try {
      const response = await fetch(
        `/a/${teamSlug}/plaid/api/bank-feed/categorize/`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken(),
          },
          body: JSON.stringify({
            rows: rows,
            category_account_id: categoryAccountId,
          }),
        }
      );

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || 'Failed to categorize transactions');
      }

      // Reload the bank feed to show updated data
      await loadLines();
    } catch (err) {
      console.error('Failed to categorize:', err);
      throw err;
    }
  };

  /**
   * Handle editing ledger transactions (redirect to journal entry edit)
   */
  const handleEditLedgerTransaction = (row) => {
    if (row.source === 'ledger' && row.journal_line_id) {
      // For now, we'll just reload the data
      // In the future, this could open an edit modal or redirect to journal entry edit
      console.log('Edit ledger transaction:', row);
      // TODO: Implement ledger transaction editing
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
            <BankFeedTable
              lines={lines}
              selectedAccount={selectedAccount}
              allAccounts={allAccounts}
              allPayees={allPayees}
              onCategorize={handleCategorize}
              onEditLedger={handleEditLedgerTransaction}
            />
          )}
        </section>
      )}
    </div>
  );
};

export default LineApp;
