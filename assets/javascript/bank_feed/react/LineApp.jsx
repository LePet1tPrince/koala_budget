/* globals gettext */

import React, { useEffect, useState, useMemo, useCallback, useRef } from 'react';
import { Alert, Snackbar } from '@mui/material';

import AccountGrid from './AccountGrid';
import LineTableMaterial from './LineTableMaterial';
import PlaidLinkButton from './PlaidLinkButton';
import { CSVUploadWizard } from './CSVUploadWizard';
import BatchActionBar from './BatchActionBar';
import TransferSuggestions from './TransferSuggestions';
import { getBatchOperationsApi, getTransactionApi } from '../bank_feed';
import { formatCurrency } from '../../utilities/currency';

/**
 * LineApp - Main application component for managing lines
 * Manages account selection and bank feed operations
 */
const LineApp = ({ accounts: initialAccounts, allAccounts, allPayees, allAccountGroups, teamSlug, bankFeedClient, plaidClient, journalClient, uploadApi }) => {
  // Store accounts in state so we can update reconciled_balance after reconciliation
  const [accounts, setAccounts] = useState(initialAccounts);
  const [selectedAccount, setSelectedAccount] = useState(null);
  const [lines, setLines] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [showUploadWizard, setShowUploadWizard] = useState(false);

  // Account picker is expanded until an account is chosen, then it collapses
  // to a compact strip so the account list doesn't crowd the categorizing view
  const [isAccountPickerOpen, setIsAccountPickerOpen] = useState(true);

  // Batch selection state
  const [selectedIds, setSelectedIds] = useState(new Set());

  // Plaid sync status: ledger account id -> PlaidItem (for "last synced" display)
  const [plaidItemsByAccountId, setPlaidItemsByAccountId] = useState({});

  // Category suggestions: merchant/payee name -> {id, name} of last-used category
  const [categorySuggestions, setCategorySuggestions] = useState({});

  // View mode state (synced from LineTableMaterial): 'active' | 'archived'
  const [viewMode, setViewMode] = useState('active');

  // Snackbar state for batch operations
  const [snackbar, setSnackbar] = useState({
    open: false,
    message: '',
    severity: 'info',
  });

  // Batch operations API
  const batchApi = useMemo(() => getBatchOperationsApi(teamSlug), [teamSlug]);

  // Transaction API (create/update)
  const transactionApi = useMemo(() => getTransactionApi(teamSlug), [teamSlug]);

  // Show snackbar helper
  const showSnackbar = useCallback((message, severity = 'info') => {
    setSnackbar({ open: true, message, severity });
  }, []);

  // Close snackbar
  const handleCloseSnackbar = () => {
    setSnackbar({ ...snackbar, open: false });
  };

  const loadAccounts = useCallback(async () => {
    try {
      const updatedAccounts = await batchApi.fetchFeedAccounts();
      setAccounts(updatedAccounts);
      const current = selectedAccountRef.current;
      if (current) {
        const updated = updatedAccounts.find(a => a.id === current.id);
        if (updated) setSelectedAccount(updated);
      }
    } catch (err) {
      console.error('Failed to refresh account balances:', err);
    }
  }, [batchApi]);

  // Monotonic id so a slow response for a previously selected account can't
  // overwrite the rows of the currently selected one
  const loadRequestRef = useRef(0);
  const selectedAccountRef = useRef(null);
  selectedAccountRef.current = selectedAccount;

  // Load Plaid sync status (which item feeds each account, and when it last synced)
  const loadPlaidStatus = useCallback(async () => {
    try {
      const [accountsData, itemsData] = await Promise.all([
        plaidClient.plaidAccountsList({ teamSlug }),
        plaidClient.plaidItemsList({ teamSlug }),
      ]);
      const itemsById = {};
      (itemsData.results || []).forEach((item) => {
        itemsById[item.id] = item;
      });
      const map = {};
      (accountsData.results || []).forEach((pa) => {
        if (pa.account != null && itemsById[pa.item]) {
          map[pa.account] = itemsById[pa.item];
        }
      });
      setPlaidItemsByAccountId(map);
    } catch (err) {
      console.error('Failed to load Plaid sync status:', err);
    }
  }, [plaidClient, teamSlug]);

  useEffect(() => {
    loadPlaidStatus();
  }, [loadPlaidStatus]);

  // Load category suggestions (most recent category per merchant)
  useEffect(() => {
    bankFeedClient
      .bankFeedCategorySuggestions({ teamSlug })
      .then((rows) => {
        const map = {};
        (rows || []).forEach((s) => {
          map[s.merchantName] = { id: s.categoryId, name: s.categoryName };
        });
        setCategorySuggestions(map);
      })
      .catch((err) => console.error('Failed to load category suggestions:', err));
  }, [bankFeedClient, teamSlug]);

  // Load lines when account is selected
  useEffect(() => {
    if (selectedAccount) {
      loadLines(selectedAccount);
    } else {
      setLines([]);
    }
  }, [selectedAccount]);

  const loadLines = async (account = selectedAccountRef.current) => {
    if (!account) return;
    const requestId = ++loadRequestRef.current;
    setLoading(true);
    setError(null);
    try {
      // Use the bank feed API client, following pagination if the server
      // returns more than one page
      const results = [];
      let data = await bankFeedClient.bankFeedFeedList({
        teamSlug: teamSlug,
        account: account.id,
      });
      results.push(...(data.results || []));
      while (data.next) {
        const nextPage = Number(new URL(data.next, window.location.origin).searchParams.get('page'));
        if (!nextPage) break;
        data = await bankFeedClient.bankFeedFeedList({
          teamSlug: teamSlug,
          account: account.id,
          page: nextPage,
        });
        results.push(...(data.results || []));
      }
      if (loadRequestRef.current === requestId) {
        setLines(results);
      }
    } catch (err) {
      console.error('Failed to load lines:', err);
      if (loadRequestRef.current === requestId) {
        setError(err.message || gettext('Failed to load lines'));
      }
    } finally {
      if (loadRequestRef.current === requestId) {
        setLoading(false);
      }
    }
  };

  const handleAccountSelect = (account) => {
    // Selection refers to rows of the previous account; don't let the batch
    // bar keep acting on rows that are no longer visible
    setSelectedIds(new Set());
    setSelectedAccount(account);
    setIsAccountPickerOpen(false);
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

        // The sync runs in a background task with no completion signal, so
        // reload a few times while it (probably) finishes instead of assuming
        // it's done after a fixed 2s.
        const accountId = selectedAccount.id;
        for (const delay of [2000, 4000, 6000]) {
          await new Promise((resolve) => setTimeout(resolve, delay));
          if (selectedAccountRef.current?.id !== accountId) break;
          await loadLines();
        }
        await loadPlaidStatus();
        setRefreshing(false);
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

      // Reload the bank feed and account balances
      await Promise.all([loadLines(), loadAccounts()]);
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
      // Use the new transaction API which creates BankTransaction + JournalEntry
      await transactionApi.createTransaction({
        date: lineData.date,
        category: lineData.category,
        inflow: lineData.inflow || '0',
        outflow: lineData.outflow || '0',
        payee: lineData.payee || '',
        description: lineData.description || '',
        account: selectedAccount.id,
      });

      await Promise.all([loadLines(), loadAccounts()]);
    } catch (err) {
      console.error('Failed to add line:', err);
      throw err;
    }
  };

  /**
   * Handle editing a transaction from the edit modal
   * Uses the transaction API to update the BankTransaction and associated JournalEntry
   */
  const handleEditTransaction = async (updatedData) => {
    try {
      const { id, date, category, inflow, outflow, payee, description } = updatedData;

      // Use the transaction API to update the transaction
      await transactionApi.updateTransaction(id, {
        date: date,
        category: category,
        inflow: inflow || '0',
        outflow: outflow || '0',
        payee: payee || '',
        description: description || '',
        account: selectedAccount.id,
      });

      await Promise.all([loadLines(), loadAccounts()]);
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
   * Bulk edit selected transactions via the unified batch_edit endpoint.
   * @param {Object} updates - Fields to update (category_id, account_id, payee, description, date)
   */
  const handleBulkEdit = async (updates) => {
    try {
      await batchApi.batchEdit([...selectedIds], updates);
      setSelectedIds(new Set());
      await Promise.all([loadLines(), loadAccounts()]);
      showSnackbar(gettext('Transactions updated successfully'), 'success');
    } catch (err) {
      console.error('Failed to bulk edit:', err);
      showSnackbar(err.message || gettext('Failed to update transactions'), 'error');
      throw err;
    }
  };

  /**
   * Batch archive selected transactions
   */
  const handleBatchArchive = async () => {
    try {
      await batchApi.batchArchive([...selectedIds]);
      setSelectedIds(new Set());
      await Promise.all([loadLines(), loadAccounts()]);
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
      await Promise.all([loadLines(), loadAccounts()]);
      showSnackbar(gettext('Transactions unarchived successfully'), 'success');
    } catch (err) {
      console.error('Failed to batch unarchive:', err);
      showSnackbar(err.message || gettext('Failed to unarchive transactions'), 'error');
    }
  };

  /**
   * Permanently delete selected archived transactions
   */
  const handleBatchDelete = async () => {
    try {
      await batchApi.batchDelete([...selectedIds]);
      setSelectedIds(new Set());
      await Promise.all([loadLines(), loadAccounts()]);
      showSnackbar(gettext('Transactions permanently deleted'), 'success');
    } catch (err) {
      console.error('Failed to batch delete:', err);
      showSnackbar(err.message || gettext('Failed to delete transactions'), 'error');
    }
  };

  /**
   * Batch duplicate selected transactions
   */
  const handleBatchDuplicate = async () => {
    try {
      await batchApi.batchDuplicate([...selectedIds]);
      setSelectedIds(new Set());
      await Promise.all([loadLines(), loadAccounts()]);
      showSnackbar(gettext('Transactions duplicated successfully'), 'success');
    } catch (err) {
      console.error('Failed to batch duplicate:', err);
      showSnackbar(err.message || gettext('Failed to duplicate transactions'), 'error');
    }
  };

  /**
   * Batch reconcile selected transactions
   */
  const handleBatchReconcile = async (adjustmentAmount = 0, reconciliationDate = null) => {
    try {
      await batchApi.batchReconcile([...selectedIds], adjustmentAmount, reconciliationDate);
      setSelectedIds(new Set());
      await Promise.all([loadLines(), loadAccounts()]);

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
      await batchApi.batchUnreconcile([...selectedIds]);
      setSelectedIds(new Set());
      await Promise.all([loadLines(), loadAccounts()]);

      showSnackbar(gettext('Transactions unreconciled successfully'), 'success');
    } catch (err) {
      console.error('Failed to batch unreconcile:', err);
      showSnackbar(err.message || gettext('Failed to unreconcile transactions'), 'error');
    }
  };

  /**
   * Handle selection change from table
   */
  const handleSelectionChange = (newSelectedIds) => {
    setSelectedIds(newSelectedIds);
  };

  /**
   * Human-friendly "last synced" label for the selected account's Plaid item
   */
  const formatLastSynced = (lastSyncedAt) => {
    if (!lastSyncedAt) return gettext('Never synced');
    const seconds = Math.floor((Date.now() - new Date(lastSyncedAt).getTime()) / 1000);
    if (seconds < 60) return gettext('Synced just now');
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${gettext('Synced')} ${minutes} ${gettext('min ago')}`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${gettext('Synced')} ${hours} ${gettext('hr ago')}`;
    const days = Math.floor(hours / 24);
    return `${gettext('Synced')} ${days} ${gettext('d ago')}`;
  };

  const selectedPlaidItem = selectedAccount ? plaidItemsByAccountId[selectedAccount.id] : null;

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
  const isReconciled = (r) => r.isReconciled ?? r.is_reconciled ?? false;

  const showArchiveButton = useMemo(() => {
    // Show archive only if any selected row is not archived and not reconciled
    return selectedRows.some(r => !isArchived(r) && !isReconciled(r));
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
          <button
            type="button"
            className="flex items-center gap-2 min-w-0"
            onClick={() => setIsAccountPickerOpen((open) => !open)}
            aria-expanded={isAccountPickerOpen}
            data-testid="account-picker-toggle"
          >
            <i className={`fa fa-chevron-${isAccountPickerOpen ? 'down' : 'right'} text-xs text-base-content/50 shrink-0`}></i>
            <h2 className="pg-subtitle">{gettext('Select Account')}</h2>
            {!isAccountPickerOpen && selectedAccount && (
              <span className="text-sm font-normal text-base-content/60 truncate">
                — {selectedAccount.name}
              </span>
            )}
          </button>
          <div className="flex gap-2 items-center">
            <TransferSuggestions
              batchApi={batchApi}
              showSnackbar={showSnackbar}
              onResolved={() => {
                if (selectedAccountRef.current) loadLines();
              }}
            />
            <a
              href={`/a/${teamSlug}/bankfeed/categorize/`}
              className="btn btn-primary btn-sm gap-1"
            >
              ⚡ {gettext('Categorize Mode')}
            </a>
          </div>
        </div>
        {isAccountPickerOpen && (
          accounts.length === 0 ? (
            <div className="alert alert-warning">
              <i className="fa fa-exclamation-triangle"></i>
              <span>
                {gettext('No accounts with bank feeds found. Please link a bank account to get started.')}
              </span>
              <PlaidLinkButton
                teamSlug={teamSlug}
                allAccounts={allAccounts}
                onSuccess={handlePlaidSuccess}
                plaidClient={plaidClient}
              />
            </div>
          ) : (
            <AccountGrid accounts={accounts}
               selectedAccount={selectedAccount}
               handleAccountSelect={handleAccountSelect}  />
          )
        )}
      </section>

      {/* Lines Table */}
      {selectedAccount && (
        <section className="app-card">
          <div className="flex justify-between items-center mb-2">
            <h2 className="pg-subtitle">
              {gettext('Lines for')} {selectedAccount.name}
            </h2>
            {selectedPlaidItem && (
              <span className="text-xs text-base-content/60" title={selectedPlaidItem.institutionName}>
                {refreshing
                  ? gettext('Syncing…')
                  : formatLastSynced(selectedPlaidItem.lastSyncedAt)}
              </span>
            )}
          </div>
          <div className="flex flex-wrap gap-x-6 gap-y-1 mb-4 text-sm">
            <span className="text-base-content/60">
              {gettext('Categorized balance')}:{' '}
              <span className="font-semibold text-base-content">
                {formatCurrency(selectedAccount.categorized_balance ?? selectedAccount.balance)}
              </span>
            </span>
            <span className="text-base-content/60">
              {gettext('Reconciled balance')}:{' '}
              <span className="font-semibold text-base-content">
                {formatCurrency(selectedAccount.reconciled_balance ?? 0)}
              </span>
              {selectedAccount.latest_reconciled_date && (
                <span className="text-base-content/50 ml-2">
                  {gettext('as of')} {new Date(selectedAccount.latest_reconciled_date).toLocaleDateString()}
                </span>
              )}
            </span>
          </div>
          {error && (
            <div className="alert alert-error mb-4">
              <i className="fa fa-exclamation-circle"></i>
              <span>{error}</span>
            </div>
          )}
          {loading && (
            <div className="flex justify-center items-center py-4">
              <span className="loading loading-spinner loading-lg"></span>
            </div>
          )}
          <LineTableMaterial
            lines={lines}
            selectedAccount={selectedAccount}
            allAccounts={allAccounts}
            allPayees={allPayees}
            categorySuggestions={categorySuggestions}
            teamSlug={teamSlug}
            onAdd={handleAddLine}
            onDelete={handleDeleteLine}
            onEditTransaction={handleEditTransaction}
            selectedIds={selectedIds}
            onSelectionChange={handleSelectionChange}
            onFilterModeChange={setViewMode}
            hidden={loading}
            onUploadClick={() => setShowUploadWizard(true)}
            onRefresh={handleRefresh}
            refreshing={refreshing}
            uploadDisabled={loading}
            plaidClient={plaidClient}
            onLinkSuccess={handlePlaidSuccess}
          />
        </section>
      )}

      {/* CSV Upload Wizard Modal */}
      {showUploadWizard && selectedAccount && (
        <CSVUploadWizard
          selectedAccount={selectedAccount}
          allAccounts={allAccounts}
          allAccountGroups={allAccountGroups}
          uploadApi={uploadApi}
          onComplete={(result) => {
            setShowUploadWizard(false);
            // Reload lines to show newly imported transactions
            loadLines();
            if (result) {
              const created = result.created_count ?? result.createdCount ?? 0;
              const skipped = result.skipped_count ?? result.skippedCount ?? 0;
              const parts = [`${created} ${gettext('transactions imported')}`];
              if (skipped > 0) {
                parts.push(`${skipped} ${gettext('skipped')}`);
              }
              showSnackbar(parts.join(', '), 'success');
            }
          }}
          onCancel={() => setShowUploadWizard(false)}
        />
      )}

      {/* Batch Action Bar */}
      <BatchActionBar
        selectedCount={selectedIds.size}
        selectedRows={selectedRows}
        allAccounts={allAccounts}
        allPayees={allPayees}
        bankFeedAccounts={accounts}
        onBulkEdit={handleBulkEdit}
        onArchive={handleBatchArchive}
        onUnarchive={handleBatchUnarchive}
        onDelete={handleBatchDelete}
        onDuplicate={handleBatchDuplicate}
        onReconcile={handleBatchReconcile}
        onUnreconcile={handleBatchUnreconcile}
        onClearSelection={() => setSelectedIds(new Set())}
        showArchive={showArchiveButton}
        showUnarchive={showUnarchiveButton}
        viewMode={viewMode}
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
