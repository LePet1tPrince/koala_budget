/* globals gettext */

import React, { useEffect, useState } from 'react';

import AccountCard from './AccountCard';
import AccountGrid from './AccountGrid';
import LineTableMaterial from './LineTableMaterial';
import PlaidLinkButton from './PlaidLinkButton';
import { CSVUploadWizard } from './CSVUploadWizard';

/**
 * LineApp - Main application component for managing lines
 * Manages account selection and bank feed operations
 */
const LineApp = ({ accounts, allAccounts, allPayees, teamSlug, bankFeedClient, plaidClient, journalClient }) => {
  const [selectedAccount, setSelectedAccount] = useState(null);
  const [lines, setLines] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [showUploadWizard, setShowUploadWizard] = useState(false);

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
      // Use the bank feed API client
      const data = await bankFeedClient.bankFeedFeedList({
        teamSlug: teamSlug,
        account: selectedAccount.id,
      });
      setLines(data.results || []);
    } catch (err) {
      console.error('Failed to load lines:', err);
      setError(err.message || gettext('Failed to load lines'));
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
      // First, get all Plaid accounts and find one mapped to this ledger account
      const plaidAccountsData = await plaidClient.plaidAccountsList({
        teamSlug: teamSlug,
      });

      // Find Plaid account mapped to the selected ledger account
      const plaidAccount = plaidAccountsData.results?.find(
        (pa) => pa.account === selectedAccount.id
      );

      if (plaidAccount) {
        // Trigger sync task for this Plaid item
        await plaidClient.plaidItemsSync({
          teamSlug: teamSlug,
          id: plaidAccount.item,
        });

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
      await bankFeedClient.bankFeedTransactionsCategorize({
        teamSlug: teamSlug,
        categorizeTransactionsRequest: {
          rows: rows,
          categoryId: categoryAccountId,
        },
      });

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
      // Use the simple lines API which creates a 2-line journal entry
      await journalClient.simpleLinesCreate({
        teamSlug: teamSlug,
        simpleLine: {
          entryDate: lineData.date,
          description: lineData.description,
          payee: lineData.payee,
          account: selectedAccount.id,
          category: lineData.category,
          inflow: lineData.inflow || '0',
          outflow: lineData.outflow || '0',
        },
      });

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
        await bankFeedClient.bankFeedTransactionsCategorize({
          teamSlug: teamSlug,
          categorizeTransactionsRequest: {
            rows: [{ id: lineId }],
            categoryId: lineData.category,
          },
        });
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
          <div className="flex gap-2">
            <PlaidLinkButton
              teamSlug={teamSlug}
              allAccounts={allAccounts}
              onSuccess={handlePlaidSuccess}
              plaidClient={plaidClient}
            />
          </div>
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
            <div className="flex gap-2">
              <button
                onClick={() => setShowUploadWizard(true)}
                disabled={loading}
                className="btn btn-outline btn-sm"
              >
                <i className="fa fa-upload mr-2"></i>
                {gettext('Upload CSV/Excel')}
              </button>
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

      {/* CSV Upload Wizard Modal */}
      {showUploadWizard && selectedAccount && (
        <CSVUploadWizard
          teamSlug={teamSlug}
          selectedAccount={selectedAccount}
          allAccounts={allAccounts}
          bankFeedClient={bankFeedClient}
          onComplete={(result) => {
            setShowUploadWizard(false);
            // Reload lines to show newly imported transactions
            loadLines();
          }}
          onCancel={() => setShowUploadWizard(false)}
        />
      )}
    </div>
  );
};

export default LineApp;
