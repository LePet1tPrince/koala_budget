import React, { useState, useMemo } from 'react';
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Paper,
  Slide,
  TextField,
  Typography,
} from '@mui/material';
import {
  Close as CloseIcon,
  Edit as EditIcon,
  Archive as ArchiveIcon,
  Unarchive as UnarchiveIcon,
  ContentCopy as ContentCopyIcon,
  FileDownload as FileDownloadIcon,
  CheckCircle as CheckCircleIcon,
  RemoveCircle as RemoveCircleIcon,
} from '@mui/icons-material';
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
  bankFeedAccounts,
  onBulkEdit,
  onArchive,
  onUnarchive,
  onDuplicate,
  onExport,
  onClearSelection,
  onReconcile,
  onUnreconcile,
  showArchive = true,
  showUnarchive = false,
  filterMode = 'to_review',
  selectedAccount = null,
}) => {
  // In archived view, only allow unarchive and export
  const isArchivedView = filterMode === 'archived';

  // Bulk edit modal state
  const [bulkEditOpen, setBulkEditOpen] = useState(false);

  // Reconcile dialog states
  const [reconcileDialogOpen, setReconcileDialogOpen] = useState(false);
  const [unreconcileDialogOpen, setUnreconcileDialogOpen] = useState(false);
  const [adjustmentAmount, setAdjustmentAmount] = useState('');

  // Calculate reconciling amount from selected rows
  const reconcilingAmount = useMemo(() => {
    return selectedRows.reduce((sum, row) => {
      const inflow = parseFloat(row.inflow) || 0;
      const outflow = parseFloat(row.outflow) || 0;
      return sum + inflow - outflow;
    }, 0);
  }, [selectedRows]);

  // Check if all selected rows are categorized (have a category)
  const allCategorized = useMemo(() => {
    return selectedRows.every(row => row.category);
  }, [selectedRows]);

  // Get reconciled balance from selected account
  const reconciledBalance = useMemo(() => {
    if (selectedAccount?.reconciled_balance !== undefined && selectedAccount?.reconciled_balance !== null) {
      return parseFloat(selectedAccount.reconciled_balance);
    }
    return 0;
  }, [selectedAccount]);

  // Calculate new reconciled balance after reconciling
  const newReconciledBalance = useMemo(() => {
    return reconciledBalance + reconcilingAmount + (parseFloat(adjustmentAmount) || 0);
  }, [reconciledBalance, reconcilingAmount, adjustmentAmount]);

  // Handle reconcile submit
  const handleReconcileSubmit = () => {
    if (onReconcile) {
      onReconcile(parseFloat(adjustmentAmount) || 0);
    }
    setReconcileDialogOpen(false);
    setAdjustmentAmount('');
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

  return (
    <>
      <Slide direction="up" in={selectedCount > 0}>
        <Paper
          elevation={6}
          sx={{
            position: 'fixed',
            bottom: 16,
            left: '50%',
            transform: 'translateX(-50%)',
            p: 2,
            display: 'flex',
            gap: 1,
            alignItems: 'center',
            zIndex: 1000,
            borderRadius: 2,
            maxWidth: '95vw',
            flexWrap: 'wrap',
            justifyContent: 'center',
          }}
        >
          <Typography variant="body2" sx={{ fontWeight: 'bold', mr: 1 }}>
            {selectedCount} {gettext('selected')}
          </Typography>

          {!isArchivedView && (
            <Button
              size="small"
              startIcon={<EditIcon />}
              onClick={() => setBulkEditOpen(true)}
            >
              {gettext('Bulk Edit')}
            </Button>
          )}

          {showArchive && !isArchivedView && (
            <Button
              size="small"
              startIcon={<ArchiveIcon />}
              onClick={onArchive}
            >
              {gettext('Archive')}
            </Button>
          )}

          {showUnarchive && (
            <Button
              size="small"
              startIcon={<UnarchiveIcon />}
              onClick={onUnarchive}
            >
              {gettext('Unarchive')}
            </Button>
          )}

          {!isArchivedView && filterMode === 'to_review' && (
            <Button
              size="small"
              startIcon={<CheckCircleIcon />}
              onClick={() => setReconcileDialogOpen(true)}
              disabled={!allCategorized}
              title={!allCategorized ? gettext('All selected transactions must be categorized') : ''}
            >
              {gettext('Reconcile')}
            </Button>
          )}

          {filterMode === 'reconciled' && (
            <Button
              size="small"
              startIcon={<RemoveCircleIcon />}
              onClick={() => setUnreconcileDialogOpen(true)}
            >
              {gettext('Unreconcile')}
            </Button>
          )}

          {!isArchivedView && (
            <Button
              size="small"
              startIcon={<ContentCopyIcon />}
              onClick={onDuplicate}
            >
              {gettext('Duplicate')}
            </Button>
          )}

          <Button
            size="small"
            startIcon={<FileDownloadIcon />}
            onClick={handleExport}
          >
            {gettext('Export')}
          </Button>

          <IconButton size="small" onClick={onClearSelection}>
            <CloseIcon />
          </IconButton>
        </Paper>
      </Slide>

      {/* Bulk Edit Modal */}
      <BulkEditModal
        open={bulkEditOpen}
        onClose={() => setBulkEditOpen(false)}
        selectedCount={selectedCount}
        allAccounts={allAccounts}
        bankFeedAccounts={bankFeedAccounts}
        onSave={onBulkEdit}
      />

      {/* Reconcile Dialog */}
      <Dialog
        open={reconcileDialogOpen}
        onClose={() => {
          setReconcileDialogOpen(false);
          setAdjustmentAmount('');
        }}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>{gettext('Reconcile Transactions')}</DialogTitle>
        <DialogContent>
          <Box sx={{ mt: 2 }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
              <Typography>{gettext('Starting reconciled balance:')}</Typography>
              <Typography sx={{ fontWeight: 'bold' }}>{formatCurrency(reconciledBalance)}</Typography>
            </Box>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
              <Typography>{gettext('Reconciling amount')} ({selectedCount} {gettext('items')}):</Typography>
              <Typography sx={{ fontWeight: 'bold', color: reconcilingAmount >= 0 ? 'success.main' : 'error.main' }}>
                {formatCurrency(reconcilingAmount)}
              </Typography>
            </Box>
            {adjustmentAmount && parseFloat(adjustmentAmount) !== 0 && (
              <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
                <Typography>{gettext('Adjustment:')}</Typography>
                <Typography sx={{ fontWeight: 'bold', color: parseFloat(adjustmentAmount) >= 0 ? 'success.main' : 'error.main' }}>
                  {formatCurrency(parseFloat(adjustmentAmount))}
                </Typography>
              </Box>
            )}
            <Box sx={{ borderTop: 1, borderColor: 'divider', pt: 1, mt: 1 }}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
                <Typography sx={{ fontWeight: 'bold' }}>{gettext('New reconciled balance:')}</Typography>
                <Typography sx={{ fontWeight: 'bold' }}>{formatCurrency(newReconciledBalance)}</Typography>
              </Box>
            </Box>
            <TextField
              margin="dense"
              label={gettext('Adjustment (optional)')}
              fullWidth
              type="number"
              value={adjustmentAmount}
              onChange={(e) => setAdjustmentAmount(e.target.value)}
              helperText={gettext('Creates a system adjustment if balance needs correction')}
              sx={{ mt: 3 }}
              inputProps={{ step: "0.01" }}
            />
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => {
            setReconcileDialogOpen(false);
            setAdjustmentAmount('');
          }}>
            {gettext('Cancel')}
          </Button>
          <Button onClick={handleReconcileSubmit} variant="contained" color="primary">
            {gettext('Reconcile')}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Unreconcile Dialog */}
      <Dialog
        open={unreconcileDialogOpen}
        onClose={() => setUnreconcileDialogOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>{gettext('Unreconcile Transactions')}</DialogTitle>
        <DialogContent>
          <Box sx={{ mt: 2 }}>
            <Typography>
              {gettext('Are you sure you want to unreconcile')} {selectedCount} {gettext('transaction(s)?')}
            </Typography>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 2 }}>
              <Typography>{gettext('Amount being unreconciled:')}</Typography>
              <Typography sx={{ fontWeight: 'bold', color: reconcilingAmount >= 0 ? 'success.main' : 'error.main' }}>
                {formatCurrency(reconcilingAmount)}
              </Typography>
            </Box>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 1 }}>
              <Typography>{gettext('New reconciled balance:')}</Typography>
              <Typography sx={{ fontWeight: 'bold' }}>
                {formatCurrency(reconciledBalance - reconcilingAmount)}
              </Typography>
            </Box>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setUnreconcileDialogOpen(false)}>{gettext('Cancel')}</Button>
          <Button onClick={handleUnreconcileSubmit} variant="contained" color="warning">
            {gettext('Unreconcile')}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
};

export default BatchActionBar;
