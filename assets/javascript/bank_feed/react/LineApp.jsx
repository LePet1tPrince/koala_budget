/* globals gettext */

import React, { useEffect, useState } from 'react';
import { apiRequest, handleApiError } from '../utils';

import AccountCard from './AccountCard';
import AccountGrid from './AccountGrid';
import LineTableMaterial from './LineTableMaterial';
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
      const response = await apiRequest(
        `/a/${teamSlug}/bankfeed/api/feed/?account=${selectedAccount.id}`
      );

      await handleApiError(response, gettext('Failed to load lines'));
      const data = await response.json();
      setLines(data);
    } catch (err) {
      console.error('Failed to load lines:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleAccountSelect = (account) => {
    setSelectedAccount(account);
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
      const plaidAccountResponse = await apiRequest(
        `/a/${teamSlug}/plaid/api/accounts/${selectedAccount.id}`
      );

      await handleApiError(plaidAccountResponse, 'Failed to fetch Plaid account');
      const plaidAccountsData = await plaidAccountResponse.json();

      if (plaidAccountsData.results && plaidAccountsData.results.length > 0) {
        const plaidAccount = plaidAccountsData.results[0];

        // Trigger sync task for this Plaid item
        const syncResponse = await apiRequest(
          `/a/${teamSlug}/plaid/api/items/${plaidAccount.item}/sync/`,
          { method: 'POST' }
        );

        await handleApiError(syncResponse, 'Failed to sync transactions');

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
      const response = await apiRequest(
        `/a/${teamSlug}/bankfeed/api/feed/categorize/`,
        {
          method: 'POST',
          body: JSON.stringify({
            rows: rows,
            category_id: categoryAccountId,
          }),
        }
      );

      await handleApiError(response, 'Failed to categorize transactions');

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

  /**
   * Handle adding a new line (manual transaction)
   */
  const handleAddLine = async (lineData) => {
    try {
      // For manual transactions, we need to create a journal entry
      // This would typically use the journal API
      const response = await apiRequest(
        `/a/${teamSlug}/journal/api/entries/`,
        {
          method: 'POST',
          body: JSON.stringify({
            entry_date: lineData.date,
            description: lineData.description,
            payee: lineData.payee,
            lines: [
              {
                account: selectedAccount.id,
                dr_amount: lineData.outflow || 0,
                cr_amount: lineData.inflow || 0,
              },
              {
                account: lineData.category,
                dr_amount: lineData.inflow || 0,
                cr_amount: lineData.outflow || 0,
              },
            ],
          }),
        }
      );

      await handleApiError(response, 'Failed to add line');

      // Reload the bank feed to show updated data
      await loadLines();
    } catch (err) {
      console.error('Failed to add line:', err);
      throw err;
    }
  };

  /**
   * Handle updating an existing line
   */
  const handleUpdateLine = async (lineId, lineData) => {
    try {
      // If a category is being set and the transaction isn't already categorized,
      // use the categorize API to create a journal entry
      if (lineData.category && !lineData.journal_entry_id) {
        const response = await apiRequest(
          `/a/${teamSlug}/bankfeed/api/feed/categorize/`,
          {
            method: 'POST',
            body: JSON.stringify({
              rows: [{ id: lineId }],
              category_id: lineData.category,
            }),
          }
        );

        await handleApiError(response, 'Failed to categorize transaction');
        await loadLines();
        return;
      }

      // For already categorized transactions or transactions without categories,
      // we may need a different approach (e.g., update the existing journal entry)
      throw new Error('Updating already categorized transactions not yet implemented');

    } catch (err) {
      console.error('Failed to update line:', err);
      throw err;
    }
  };

  /**
   * Handle deleting a line
   */
  const handleDeleteLine = async (lineId) => {
    try {
      // Parse the composite ID
      const [source, id] = lineId.split('-');

      if (source === 'manual' || source === 'csv') {
        // Delete manual transaction - would need to find and delete the journal entry
        throw new Error('Deleting manual transactions not yet implemented');
      } else if (source === 'plaid') {
        // Cannot delete Plaid transactions
        throw new Error('Cannot delete Plaid transactions');
      } else if (source === 'ledger') {
        // Delete ledger transaction - would need to delete the journal entry
        throw new Error('Deleting ledger transactions not yet implemented');
      }

      await loadLines();
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
          <AccountGrid accounts={accounts}
             selectedAccount={selectedAccount}
             handleAccountSelect={handleAccountSelect}  />
          // <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          //   {accounts.map((account) => (
          //     <AccountCard
          //       key={account.id}
          //       account={account}
          //       isSelected={selectedAccount?.id === account.id}
          //       onClick={handleAccountSelect}
          //     />
          //   ))}
          // </div>
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
            <LineTableMaterial
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
