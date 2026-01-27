/* globals gettext */

import React, { useEffect, useState, useMemo, useCallback } from 'react';
import { Alert, Snackbar } from '@mui/material';

import AccountCard from './AccountCard';
import AccountGrid from './AccountGrid';
import LineTableMaterial from './LineTableMaterial';
import PlaidLinkButton from './PlaidLinkButton';
import { CSVUploadWizard } from './CSVUploadWizard';
import BatchActionBar from './BatchActionBar';
import { getBatchOperationsApi } from '../bank_feed';

/**
 * LineApp - Main application component for managing lines
 * Manages account selection and bank feed operations
 */
const LineApp = ({ accounts: initialAccounts, allAccounts, allPayees, teamSlug, bankFeedClient, plaidClient, journalClient, uploadApi }) => {
  // Store accounts in state so we can update reconciled_balance after reconciliation
  const [accounts, setAccounts] = useState(initialAccounts);
  const [selectedAccount, setSelectedAccount] = useState(null);
  const [lines, setLines] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [showUploadWizard, setShowUploadWizard] = useState(false);

  // Batch selection state
  const [selectedIds, setSelectedIds] = useState(new Set());

  // Filter mode state (synced from LineTableMaterial)
  const [filterMode, setFilterMode] = useState('to_review');

  // Snackbar state for batch operations
  const [snackbar, setSnackbar] = useState({
    open: false,
    message: '',
    severity: 'info',
  });

  // Batch operations API
  const batchApi = useMemo(() => getBatchOperationsApi(teamSlug), [teamSlug]);

  // Show snackbar helper
  const showSnackbar = useCallback((message, severity = 'info') => {
    setSnackbar({ open: true, message, severity });
  }, []);

  // Close snackbar
  const handleCloseSnackbar = () => {
    setSnackbar({ ...snackbar, open: false });
  };

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
   * Handle editing a transaction from the edit modal
   * Supports both ledger transactions (full CRUD) and uncategorized transactions (batch endpoints)
   */
  const handleEditTransaction = async (updatedData) => {
    try {
      const { id, source, journal_entry_id, date, category, inflow, outflow, payee, description } = updatedData;

      // For ledger transactions (categorized), use the simple lines partial update
      if (source === 'ledger') {
        // Extract the actual line ID from the composite ID (e.g., "ledger-123" -> 123)
        const lineId = id.includes('-') ? id.split('-')[1] : id;

        // Format date as ISO string if it's a Date object
        const formattedDate = date instanceof Date ? date.toISOString().split('T')[0] : date;

        await journalClient.simpleLinesPartialUpdate({
          teamSlug: teamSlug,
          id: parseInt(lineId, 10),
          patchedSimpleLine: {
            entryDate: formattedDate,
            category: category?.id || category,
            inflow: inflow || '0',
            outflow: outflow || '0',
            payee: payee || '',
            description: description || '',
          },
        });

        await loadLines();
        showSnackbar(gettext('Transaction updated successfully'), 'success');
        return;
      }

      // For uncategorized transactions, use batch endpoints with single-item arrays
      // Track what we need to update
      const promises = [];

      // Find the original transaction to compare changes
      const originalTransaction = lines.find(l => l.id === id);

      // Update category if changed (also sets payee/description if this creates a new journal entry)
      if (category && category.id && (!originalTransaction?.category || originalTransaction.category.id !== category.id)) {
        promises.push(batchApi.batchCategorize([id], category.id));
      }

      // Update payee if changed (for uncategorized transactions)
      if (payee !== undefined && payee !== originalTransaction?.payee) {
        promises.push(batchApi.batchSetPayee([id], payee));
      }

      // Update description if changed
      if (description !== undefined && description !== originalTransaction?.description) {
        promises.push(batchApi.batchSetDescription([id], description));
      }

      if (promises.length > 0) {
        await Promise.all(promises);
        await loadLines();
        showSnackbar(gettext('Transaction updated successfully'), 'success');
      }

    } catch (err) {
      console.error('Failed to update transaction:', err);
      showSnackbar(err.message || gettext('Failed to update transaction'), 'error');
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

  // Batch operation handlers

  /**
   * Batch categorize selected transactions
   */
  const handleBatchCategorize = async (categoryId) => {
    try {
      await batchApi.batchCategorize([...selectedIds], categoryId);
      setSelectedIds(new Set());
      await loadLines();
      showSnackbar(gettext('Transactions categorized successfully'), 'success');
    } catch (err) {
      console.error('Failed to batch categorize:', err);
      showSnackbar(err.message || gettext('Failed to categorize transactions'), 'error');
    }
  };

  /**
   * Batch move selected transactions to another account
   */
  const handleBatchMoveAccount = async (accountId) => {
    try {
      await batchApi.batchMoveAccount([...selectedIds], accountId);
      setSelectedIds(new Set());
      await loadLines();
      showSnackbar(gettext('Transactions moved successfully'), 'success');
    } catch (err) {
      console.error('Failed to batch move account:', err);
      showSnackbar(err.message || gettext('Failed to move transactions'), 'error');
    }
  };

  /**
   * Batch set payee on selected transactions
   */
  const handleBatchSetPayee = async (payee) => {
    try {
      await batchApi.batchSetPayee([...selectedIds], payee);
      setSelectedIds(new Set());
      await loadLines();
      showSnackbar(gettext('Payee updated successfully'), 'success');
    } catch (err) {
      console.error('Failed to batch set payee:', err);
      showSnackbar(err.message || gettext('Failed to update payee'), 'error');
    }
  };

  /**
   * Batch set description on selected transactions
   */
  const handleBatchSetDescription = async (description) => {
    try {
      await batchApi.batchSetDescription([...selectedIds], description);
      setSelectedIds(new Set());
      await loadLines();
      showSnackbar(gettext('Description updated successfully'), 'success');
    } catch (err) {
      console.error('Failed to batch set description:', err);
      showSnackbar(err.message || gettext('Failed to update description'), 'error');
    }
  };

  /**
   * Batch archive selected transactions
   */
  const handleBatchArchive = async () => {
    try {
      await batchApi.batchArchive([...selectedIds]);
      setSelectedIds(new Set());
      await loadLines();
      showSnackbar(gettext('Transactions archived successfully'), 'success');
    } catch (err) {
      console.error('Failed to batch archive:', err);
      showSnackbar(err.message || gettext('Failed to archive transactions'), 'error');
    }
  };

  /**
   * Batch unarchive selected transactions
   */
  const handleBatchUnarchive = async () => {
    try {
      await batchApi.batchUnarchive([...selectedIds]);
      setSelectedIds(new Set());
      await loadLines();
      showSnackbar(gettext('Transactions unarchived successfully'), 'success');
    } catch (err) {
      console.error('Failed to batch unarchive:', err);
      showSnackbar(err.message || gettext('Failed to unarchive transactions'), 'error');
    }
  };

  /**
   * Batch duplicate selected transactions
   */
  const handleBatchDuplicate = async () => {
    try {
      await batchApi.batchDuplicate([...selectedIds]);
      setSelectedIds(new Set());
      await loadLines();
      showSnackbar(gettext('Transactions duplicated successfully'), 'success');
    } catch (err) {
      console.error('Failed to batch duplicate:', err);
      showSnackbar(err.message || gettext('Failed to duplicate transactions'), 'error');
    }
  };

  /**
   * Batch reconcile selected transactions
   */
  const handleBatchReconcile = async (adjustmentAmount = 0) => {
    try {
      // Calculate the reconciling amount before clearing selection
      const reconcilingAmount = selectedRows.reduce((sum, row) => {
        const inflow = parseFloat(row.inflow) || 0;
        const outflow = parseFloat(row.outflow) || 0;
        return sum + inflow - outflow;
      }, 0);

      await batchApi.batchReconcile([...selectedIds], adjustmentAmount);
      setSelectedIds(new Set());
      await loadLines();

      // Update the account's reconciled_balance
      const totalChange = reconcilingAmount + (parseFloat(adjustmentAmount) || 0);
      updateAccountReconciledBalance(totalChange);

      showSnackbar(gettext('Transactions reconciled successfully'), 'success');
    } catch (err) {
      console.error('Failed to batch reconcile:', err);
      showSnackbar(err.message || gettext('Failed to reconcile transactions'), 'error');
    }
  };

  /**
   * Batch unreconcile selected transactions
   */
  const handleBatchUnreconcile = async () => {
    try {
      // Calculate the amount being unreconciled before clearing selection
      const unreconcilingAmount = selectedRows.reduce((sum, row) => {
        const inflow = parseFloat(row.inflow) || 0;
        const outflow = parseFloat(row.outflow) || 0;
        return sum + inflow - outflow;
      }, 0);

      await batchApi.batchUnreconcile([...selectedIds]);
      setSelectedIds(new Set());
      await loadLines();

      // Update the account's reconciled_balance (subtract the unreconciled amount)
      updateAccountReconciledBalance(-unreconcilingAmount);

      showSnackbar(gettext('Transactions unreconciled successfully'), 'success');
    } catch (err) {
      console.error('Failed to batch unreconcile:', err);
      showSnackbar(err.message || gettext('Failed to unreconcile transactions'), 'error');
    }
  };

  /**
   * Update the reconciled_balance on the selected account and in the accounts list
   */
  const updateAccountReconciledBalance = (amountChange) => {
    if (!selectedAccount) return;

    const currentBalance = parseFloat(selectedAccount.reconciled_balance) || 0;
    const newBalance = currentBalance + amountChange;

    // Update the selected account
    const updatedSelectedAccount = {
      ...selectedAccount,
      reconciled_balance: String(newBalance),
    };
    setSelectedAccount(updatedSelectedAccount);

    // Update the accounts list
    setAccounts(prevAccounts =>
      prevAccounts.map(acc =>
        acc.id === selectedAccount.id
          ? { ...acc, reconciled_balance: String(newBalance) }
          : acc
      )
    );
  };

  /**
   * Handle selection change from table
   */
  const handleSelectionChange = (newSelectedIds) => {
    setSelectedIds(newSelectedIds);
  };

  /**
   * Get selected rows data
   */
  const selectedRows = useMemo(() => {
    return lines.filter(l => selectedIds.has(l.id));
  }, [lines, selectedIds]);

  /**
   * Determine which archive/unarchive button to show based on selection
   */
  // Handle both camelCase (from generated API client) and snake_case (raw API)
  const isArchived = (r) => r.isArchived ?? r.is_archived ?? false;

  const showArchiveButton = useMemo(() => {
    // Show archive if any selected row is not archived
    return selectedRows.some(r => !isArchived(r));
  }, [selectedRows]);

  const showUnarchiveButton = useMemo(() => {
    // Show unarchive if any selected row is archived
    return selectedRows.some(r => isArchived(r));
  }, [selectedRows]);

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
              onAdd={handleAddLine}
              onDelete={handleDeleteLine}
              onEditTransaction={handleEditTransaction}
              selectedIds={selectedIds}
              onSelectionChange={handleSelectionChange}
              onFilterModeChange={setFilterMode}
            />
          )}
        </section>
      )}

      {/* CSV Upload Wizard Modal */}
      {showUploadWizard && selectedAccount && (
        <CSVUploadWizard
          selectedAccount={selectedAccount}
          allAccounts={allAccounts}
          uploadApi={uploadApi}
          onComplete={(result) => {
            setShowUploadWizard(false);
            // Reload lines to show newly imported transactions
            loadLines();
          }}
          onCancel={() => setShowUploadWizard(false)}
        />
      )}

      {/* Batch Action Bar */}
      <BatchActionBar
        selectedCount={selectedIds.size}
        selectedRows={selectedRows}
        allAccounts={allAccounts}
        bankFeedAccounts={accounts}
        onCategorize={handleBatchCategorize}
        onMoveAccount={handleBatchMoveAccount}
        onSetPayee={handleBatchSetPayee}
        onSetDescription={handleBatchSetDescription}
        onArchive={handleBatchArchive}
        onUnarchive={handleBatchUnarchive}
        onDuplicate={handleBatchDuplicate}
        onReconcile={handleBatchReconcile}
        onUnreconcile={handleBatchUnreconcile}
        onClearSelection={() => setSelectedIds(new Set())}
        showArchive={showArchiveButton}
        showUnarchive={showUnarchiveButton}
        filterMode={filterMode}
        selectedAccount={selectedAccount}
      />

      {/* Snackbar for batch operations */}
      <Snackbar
        open={snackbar.open}
        autoHideDuration={6000}
        onClose={handleCloseSnackbar}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert onClose={handleCloseSnackbar} severity={snackbar.severity} sx={{ width: '100%' }}>
          {snackbar.message}
        </Alert>
      </Snackbar>
    </div>
  );
};

export default LineApp;
