import React, { useState, useMemo } from 'react';
import Modal from '../../common/Modal';
import Icon from '../../common/Icon';
import BulkEditModal from './BulkEditModal';

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
  onVoid,
  onRestore,
  onDelete,
  onDuplicate,
  onExport,
  onClearSelection,
  showVoid = true,
  showRestore = false,
  viewMode = 'active',
  getExportRows = null,
}) => {
  // In the voided view, only allow restore, export, and delete
  const isVoidedView = viewMode === 'voided';

  // Bulk edit modal state
  const [bulkEditOpen, setBulkEditOpen] = useState(false);

  // Delete dialog state
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  // Calculate inflow, outflow, and net from selected rows
  const { totalInflow, totalOutflow, net } = useMemo(() => {
    return selectedRows.reduce((acc, row) => {
      const inflow = parseFloat(row.inflow) || 0;
      const outflow = parseFloat(row.outflow) || 0;
      return {
        totalInflow: acc.totalInflow + inflow,
        totalOutflow: acc.totalOutflow + outflow,
        net: acc.net + inflow - outflow,
      };
    }, { totalInflow: 0, totalOutflow: 0, net: 0 });
  }, [selectedRows]);

  // Duplicate is withheld when any selected row is reconciled. The quick filters
  // don't guarantee a homogeneous selection, so this reads the selected rows
  // rather than the active filter.
  const anyReconciled = useMemo(() => {
    return selectedRows.some(r => r.isReconciled ?? r.is_reconciled ?? false);
  }, [selectedRows]);

  // Format currency
  const formatCurrency = (amount) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
    }).format(amount);
  };

  // Export to CSV. Rows selected on other pages (or by "select all matching")
  // are summaries, so the caller fetches them in full first.
  const handleExport = async () => {
    const rows = getExportRows ? await getExportRows() : selectedRows;
    const headers = ['Date', 'Description', 'Merchant', 'Inflow', 'Outflow', 'Category', 'Account'];
    const csvRows = [headers.join(',')];

    rows.forEach(row => {
      csvRows.push([
        row.postedDate,
        `"${(row.description || '').replace(/"/g, '""')}"`,
        `"${(row.merchantName || '').replace(/"/g, '""')}"`,
        row.inflow || '',
        row.outflow || '',
        `"${(row.category?.name || '').replace(/"/g, '""')}"`,
        `"${(row.account?.name || '').replace(/"/g, '""')}"`,
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
            <span className={`money font-bold ${money(net)}`}>{formatCurrency(net)}</span>
          </span>
        </div>

        <div className="mb-1 h-px w-full bg-base-300" aria-hidden="true" />

        {!isVoidedView && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setBulkEditOpen(true)}>
            <Icon name="edit" className="w-4 h-4 shrink-0" />
            {gettext('Bulk Edit')}
          </button>
        )}

        {showVoid && !isVoidedView && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={onVoid}>
            <Icon name="ban" className="w-4 h-4 shrink-0" />
            {gettext('Void')}
          </button>
        )}

        {showRestore && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={onRestore}>
            <Icon name="rotate-ccw" className="w-4 h-4 shrink-0" />
            {gettext('Restore')}
          </button>
        )}

        {isVoidedView && (
          <button type="button" className="btn btn-ghost btn-sm text-error" onClick={() => setDeleteDialogOpen(true)}>
            <Icon name="trash" className="w-4 h-4 shrink-0" />
            {gettext('Delete')}
          </button>
        )}

        {!isVoidedView && !anyReconciled && (
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
