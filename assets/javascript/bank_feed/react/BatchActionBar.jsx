import React, { useState, useMemo } from 'react';
import DateField from '../../common/DateField';
import Modal from '../../common/Modal';
import Icon from '../../common/Icon';
import BulkEditModal from './BulkEditModal';
import { formatDateForInput } from '../utils';

/* globals gettext */

/**
 * BatchActionBar - Floating action bar for batch operations on selected transactions.
 * Appears at the bottom of the screen when rows are selected.
 */
const BatchActionBar = ({
  selectedCount,
  selectedRows,
  allAccounts,
  allPayees = [],
  bankFeedAccounts,
  onBulkEdit,
  onArchive,
  onUnarchive,
  onDelete,
  onDuplicate,
  onExport,
  onClearSelection,
  onReconcile,
  onUnreconcile,
  showArchive = true,
  showUnarchive = false,
  viewMode = 'active',
  selectedAccount = null,
}) => {
  // In archived view, only allow unarchive, export, and delete
  const isArchivedView = viewMode === 'archived';

  // Bulk edit modal state
  const [bulkEditOpen, setBulkEditOpen] = useState(false);

  // Delete dialog state
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  // Reconcile dialog states
  const [reconcileDialogOpen, setReconcileDialogOpen] = useState(false);
  const [unreconcileDialogOpen, setUnreconcileDialogOpen] = useState(false);
  const [trueBalance, setTrueBalance] = useState('');
  const [reconciliationDate, setReconciliationDate] = useState(new Date().toISOString().split('T')[0]);

  // Calculate inflow, outflow, and net from selected rows
  const { totalInflow, totalOutflow, reconcilingAmount } = useMemo(() => {
    return selectedRows.reduce((acc, row) => {
      const inflow = parseFloat(row.inflow) || 0;
      const outflow = parseFloat(row.outflow) || 0;
      return {
        totalInflow: acc.totalInflow + inflow,
        totalOutflow: acc.totalOutflow + outflow,
        reconcilingAmount: acc.reconcilingAmount + inflow - outflow,
      };
    }, { totalInflow: 0, totalOutflow: 0, reconcilingAmount: 0 });
  }, [selectedRows]);

  // Check if all selected rows are categorized (have a category)
  const allCategorized = useMemo(() => {
    return selectedRows.every(row => row.category);
  }, [selectedRows]);

  // Latest transaction date among selected rows (defaults the reconciliation date)
  const maxSelectedDate = useMemo(() => {
    const dates = selectedRows.map(row => formatDateForInput(row.postedDate)).filter(Boolean);
    if (dates.length === 0) return new Date().toISOString().split('T')[0];
    return dates.reduce((max, date) => (date > max ? date : max));
  }, [selectedRows]);

  // Check if any/all selected rows are reconciled. The quick filters no longer guarantee
  // a homogeneous selection, so reconcile/unreconcile availability is derived from the
  // actual selected rows rather than the active filter.
  const anyReconciled = useMemo(() => {
    return selectedRows.some(r => r.isReconciled ?? r.is_reconciled ?? false);
  }, [selectedRows]);

  const allReconciled = useMemo(() => {
    return selectedRows.length > 0 && selectedRows.every(r => r.isReconciled ?? r.is_reconciled ?? false);
  }, [selectedRows]);

  // Get reconciled balance from selected account
  const reconciledBalance = useMemo(() => {
    if (selectedAccount?.reconciled_balance !== undefined && selectedAccount?.reconciled_balance !== null) {
      return parseFloat(selectedAccount.reconciled_balance);
    }
    return 0;
  }, [selectedAccount]);

  // Computed adjustment = trueBalance - (reconciledBalance + reconcilingAmount)
  const computedAdjustment = useMemo(() => {
    if (trueBalance === '' || trueBalance === null) return 0;
    return Math.round((parseFloat(trueBalance) - (reconciledBalance + reconcilingAmount)) * 100) / 100;
  }, [trueBalance, reconciledBalance, reconcilingAmount]);

  // Calculate new reconciled balance after reconciling (or unreconciling)
  const newReconciledBalance = useMemo(() => {
    if (allReconciled) {
      return reconciledBalance - reconcilingAmount;
    }
    if (trueBalance !== '' && trueBalance !== null) {
      return parseFloat(trueBalance);
    }
    return reconciledBalance + reconcilingAmount;
  }, [reconciledBalance, reconcilingAmount, trueBalance, allReconciled]);

  // Handle reconcile submit
  const handleReconcileSubmit = () => {
    if (onReconcile) {
      onReconcile(computedAdjustment, reconciliationDate);
    }
    setReconcileDialogOpen(false);
    setTrueBalance('');
    setReconciliationDate(new Date().toISOString().split('T')[0]);
  };

  // Handle unreconcile submit
  const handleUnreconcileSubmit = () => {
    if (onUnreconcile) {
      onUnreconcile();
    }
    setUnreconcileDialogOpen(false);
  };

  // Format currency
  const formatCurrency = (amount) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
    }).format(amount);
  };

  // Export to CSV
  const handleExport = () => {
    const headers = ['Date', 'Description', 'Merchant', 'Inflow', 'Outflow', 'Category', 'Account'];
    const csvRows = [headers.join(',')];

    selectedRows.forEach(row => {
      csvRows.push([
        row.postedDate,
        `"${(row.description || '').replace(/"/g, '""')}"`,
        `"${(row.merchantName || '').replace(/"/g, '""')}"`,
        row.inflow || '',
        row.outflow || '',
        row.category?.name || '',
        row.account?.name || '',
      ].join(','));
    });

    const blob = new Blob([csvRows.join('\n')], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `bank_transactions_${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
    URL.revokeObjectURL(url);

    if (onExport) {
      onExport();
    }
  };

  if (selectedCount === 0) return null;

  const resetReconcileDialog = () => {
    setReconcileDialogOpen(false);
    setTrueBalance('');
    setReconciliationDate(new Date().toISOString().split('T')[0]);
  };

  const money = (amount) => (amount >= 0 ? 'text-success' : 'text-error');

  return (
    <>
      {/* The bar is fixed to the bottom of the viewport and rises into place, as
          MUI's Slide + Paper did. `animate-*` is only entrance motion, so it does
          not re-run as the selection changes. */}
      <div
        className="app-surface fixed bottom-4 left-1/2 z-[1000] flex max-w-[95vw] -translate-x-1/2 flex-wrap
                   items-center justify-center gap-2 rounded-box p-4 shadow-lg"
        data-testid="batch-action-bar"
      >
        {/* Selection summary strip */}
        <div className="mb-1 flex w-full flex-wrap items-center justify-center gap-4 text-xs">
          <span className="font-bold">
            {selectedCount} {gettext('selected')}
          </span>

          <span className="h-4 w-px bg-base-300" aria-hidden="true" />

          <span className="flex items-center gap-1">
            <span className="text-base-content/70">{gettext('In:')}</span>
            <span className="money font-bold text-success">{formatCurrency(totalInflow)}</span>
          </span>
          <span className="flex items-center gap-1">
            <span className="text-base-content/70">{gettext('Out:')}</span>
            <span className="money font-bold text-error">{formatCurrency(totalOutflow)}</span>
          </span>
          <span className="flex items-center gap-1">
            <span className="text-base-content/70">{gettext('Net:')}</span>
            <span className={`money font-bold ${money(reconcilingAmount)}`}>{formatCurrency(reconcilingAmount)}</span>
          </span>

          {!isArchivedView && selectedAccount && (
            <>
              <span className="h-4 w-px bg-base-300" aria-hidden="true" />
              <span className="flex items-center gap-1">
                <span className="text-base-content/70">{gettext('Reconciled:')}</span>
                <span className="money font-bold">{formatCurrency(reconciledBalance)}</span>
              </span>
              <span className="text-base-content/70" aria-hidden="true">
                →
              </span>
              <span className="money font-bold">{formatCurrency(newReconciledBalance)}</span>
            </>
          )}
        </div>

        <div className="mb-1 h-px w-full bg-base-300" aria-hidden="true" />

        {!isArchivedView && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setBulkEditOpen(true)}>
            <Icon name="edit" className="w-4 h-4 shrink-0" />
            {gettext('Bulk Edit')}
          </button>
        )}

        {showArchive && !isArchivedView && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={onArchive}>
            <Icon name="archive" className="w-4 h-4 shrink-0" />
            {gettext('Archive')}
          </button>
        )}

        {showUnarchive && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={onUnarchive}>
            <Icon name="unarchive" className="w-4 h-4 shrink-0" />
            {gettext('Unarchive')}
          </button>
        )}

        {isArchivedView && (
          <button type="button" className="btn btn-ghost btn-sm text-error" onClick={() => setDeleteDialogOpen(true)}>
            <Icon name="trash" className="w-4 h-4 shrink-0" />
            {gettext('Delete')}
          </button>
        )}

        {!isArchivedView && !anyReconciled && (
          // The tooltip has to sit on a wrapper: a disabled button fires no
          // pointer events, so a tip on the button itself never shows.
          <span
            className={!allCategorized ? 'tooltip' : undefined}
            data-tip={!allCategorized ? gettext('Categorize all transactions to reconcile') : undefined}
          >
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              disabled={!allCategorized}
              onClick={() => {
                setReconciliationDate(maxSelectedDate);
                setReconcileDialogOpen(true);
              }}
            >
              <Icon name="check-circle" className="w-4 h-4 shrink-0" />
              {gettext('Reconcile')}
            </button>
          </span>
        )}

        {allReconciled && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setUnreconcileDialogOpen(true)}>
            <Icon name="minus-circle" className="w-4 h-4 shrink-0" />
            {gettext('Unreconcile')}
          </button>
        )}

        {!isArchivedView && !anyReconciled && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={onDuplicate}>
            <Icon name="copy" className="w-4 h-4 shrink-0" />
            {gettext('Duplicate')}
          </button>
        )}

        <button type="button" className="btn btn-ghost btn-sm" onClick={handleExport}>
          <Icon name="download" className="w-4 h-4 shrink-0" />
          {gettext('Export')}
        </button>

        <button
          type="button"
          className="btn btn-ghost btn-sm btn-square"
          onClick={onClearSelection}
          aria-label={gettext('Clear selection')}
        >
          <Icon name="x" className="w-4 h-4 shrink-0" />
        </button>
      </div>

      {/* Bulk Edit Modal */}
      <BulkEditModal
        open={bulkEditOpen}
        onClose={() => setBulkEditOpen(false)}
        selectedCount={selectedCount}
        allAccounts={allAccounts}
        allPayees={allPayees}
        bankFeedAccounts={bankFeedAccounts}
        onSave={onBulkEdit}
        hasReconciledRows={anyReconciled}
      />

      {/* Reconcile Dialog */}
      <Modal
        open={reconcileDialogOpen}
        onClose={resetReconcileDialog}
        size="sm"
        title={gettext('Reconcile Transactions')}
        testId="reconcile-dialog"
        actions={
          <>
            <button type="button" className="btn btn-sm" onClick={resetReconcileDialog}>
              {gettext('Cancel')}
            </button>
            <button type="button" className="btn btn-sm btn-primary" onClick={handleReconcileSubmit}>
              {gettext('Reconcile')}
            </button>
          </>
        }
      >
        <div className="space-y-2 text-sm">
          <div className="flex justify-between">
            <span>{gettext('Starting reconciled balance:')}</span>
            <span className="money font-bold">{formatCurrency(reconciledBalance)}</span>
          </div>
          <div className="flex justify-between">
            <span>
              {gettext('Reconciling amount')} ({selectedCount} {gettext('items')}):
            </span>
            <span className={`money font-bold ${money(reconcilingAmount)}`}>{formatCurrency(reconcilingAmount)}</span>
          </div>
          {trueBalance !== '' && computedAdjustment !== 0 && (
            <div className="flex justify-between">
              <span>{gettext('Adjustment:')}</span>
              <span className={`money font-bold ${money(computedAdjustment)}`}>
                {formatCurrency(computedAdjustment)}
              </span>
            </div>
          )}
          <div className="flex justify-between border-t border-base-300 pt-2">
            <span className="font-bold">{gettext('New reconciled balance:')}</span>
            <span className="money font-bold">{formatCurrency(newReconciledBalance)}</span>
          </div>

          <div className="pt-4">
            <DateField
              label={gettext('Reconciliation Date')}
              value={reconciliationDate}
              onChange={setReconciliationDate}
              testId="reconciliation-date"
            />
          </div>

          <label className="form-control w-full pt-2">
            <span className="label-text mb-1 block text-sm text-base-content/70">
              {gettext('True Balance (optional)')}
            </span>
            <input
              type="number"
              step="0.01"
              className="input input-bordered w-full"
              value={trueBalance}
              onChange={(e) => setTrueBalance(e.target.value)}
              data-testid="true-balance"
            />
            <span className="mt-1 block text-xs text-base-content/70">
              {gettext('Enter your actual bank balance — an adjustment will be created automatically if needed')}
            </span>
          </label>
        </div>
      </Modal>

      {/* Unreconcile Dialog */}
      <Modal
        open={unreconcileDialogOpen}
        onClose={() => setUnreconcileDialogOpen(false)}
        size="sm"
        title={gettext('Unreconcile Transactions')}
        testId="unreconcile-dialog"
        actions={
          <>
            <button type="button" className="btn btn-sm" onClick={() => setUnreconcileDialogOpen(false)}>
              {gettext('Cancel')}
            </button>
            <button type="button" className="btn btn-sm btn-warning" onClick={handleUnreconcileSubmit}>
              {gettext('Unreconcile')}
            </button>
          </>
        }
      >
        <div className="space-y-2 text-sm">
          <p>
            {gettext('Are you sure you want to unreconcile')} {selectedCount} {gettext('transaction(s)?')}
          </p>
          <div className="flex justify-between pt-2">
            <span>{gettext('Amount being unreconciled:')}</span>
            <span className={`money font-bold ${money(reconcilingAmount)}`}>{formatCurrency(reconcilingAmount)}</span>
          </div>
          <div className="flex justify-between">
            <span>{gettext('New reconciled balance:')}</span>
            <span className="money font-bold">{formatCurrency(reconciledBalance - reconcilingAmount)}</span>
          </div>
        </div>
      </Modal>

      {/* Permanent Delete Confirmation Dialog */}
      <Modal
        open={deleteDialogOpen}
        onClose={() => setDeleteDialogOpen(false)}
        size="sm"
        testId="delete-dialog"
        title={
          <span className="flex items-center gap-2 text-error">
            <Icon name="trash" className="w-5 h-5 shrink-0" />
            {gettext('Permanently Delete Transactions')}
          </span>
        }
        actions={
          <>
            <button type="button" className="btn btn-sm" onClick={() => setDeleteDialogOpen(false)}>
              {gettext('Cancel')}
            </button>
            <button
              type="button"
              className="btn btn-sm btn-error"
              onClick={() => {
                if (onDelete) onDelete();
                setDeleteDialogOpen(false);
              }}
            >
              <Icon name="trash" className="w-4 h-4 shrink-0" />
              {gettext('Delete Forever')}
            </button>
          </>
        }
      >
        <div className="space-y-3 text-sm">
          <p className="font-bold">{gettext('This action cannot be undone.')}</p>
          <p>
            {gettext('You are about to permanently delete')} <strong>{selectedCount}</strong>{' '}
            {gettext('transaction(s) and any associated accounting records.')}
          </p>
          <p className="text-error">{gettext('Once deleted, this data cannot be recovered.')}</p>
        </div>
      </Modal>
    </>
  );
};

export default BatchActionBar;
