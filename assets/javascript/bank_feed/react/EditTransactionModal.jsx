import React, { useState, useEffect, useMemo } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  Autocomplete,
  Box,
  InputAdornment,
} from '@mui/material';
import { DatePicker } from '@mui/x-date-pickers/DatePicker';
import { LocalizationProvider } from '@mui/x-date-pickers/LocalizationProvider';
import { AdapterDateFns } from '@mui/x-date-pickers/AdapterDateFns';
import { buildCategoryOptions } from '../../common/categoryOptions';

/* globals gettext */

/**
 * EditTransactionModal - Modal dialog for creating/editing bank feed transactions
 * Supports editing: date, category, inflow/outflow, payee, and description
 *
 * Props:
 * - open: boolean - whether the modal is open
 * - onClose: function - called when modal should close
 * - transaction: object|null - the transaction to edit, or null for create mode
 * - allAccounts: array - list of accounts for category selection
 * - onSave: function - called with updated/new transaction data
 * - mode: 'create' | 'edit' - defaults to 'edit' if transaction exists, 'create' otherwise
 */
const EditTransactionModal = ({
  open,
  onClose,
  transaction,
  allAccounts,
  onSave,
  mode: modeProp,
}) => {
  // Determine mode - create if no transaction, edit otherwise
  const mode = modeProp || (transaction ? 'edit' : 'create');
  const isCreateMode = mode === 'create';

  // Form state
  const [date, setDate] = useState(null);
  const [category, setCategory] = useState(null);
  const [inflow, setInflow] = useState('');
  const [outflow, setOutflow] = useState('');
  const [payee, setPayee] = useState('');
  const [description, setDescription] = useState('');
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);

  // Create options array for category Autocomplete (grouped by account type)
  const categoryOptions = useMemo(() => {
    return buildCategoryOptions(allAccounts);
  }, [allAccounts]);

  // Initialize form when transaction changes or modal opens
  useEffect(() => {
    if (!open) return;

    if (isCreateMode) {
      // Create mode - set defaults
      setDate(new Date());
      setCategory(null);
      setInflow('');
      setOutflow('');
      setPayee('');
      setDescription('');
      setErrors({});
    } else if (transaction) {
      // Edit mode - populate from transaction
      const transactionDate = transaction.postedDate instanceof Date
        ? transaction.postedDate
        : transaction.postedDate ? new Date(transaction.postedDate) : null;
      setDate(transactionDate);

      const categoryOption = transaction.category
        ? categoryOptions.find(opt => opt.id === transaction.category.id)
        : null;
      setCategory(categoryOption);

      setInflow(transaction.inflow && parseFloat(transaction.inflow) > 0 ? transaction.inflow : '');
      setOutflow(transaction.outflow && parseFloat(transaction.outflow) > 0 ? transaction.outflow : '');
      setPayee(transaction.payee || '');
      setDescription(transaction.description || '');
      setErrors({});
    }
  }, [open, transaction, categoryOptions, isCreateMode]);

  // Check if transaction is read-only (Plaid transactions without journal entry)
  const isReadOnly = useMemo(() => {
    if (isCreateMode || !transaction) return false;
    return transaction.source === 'plaid' && !transaction.journal_entry_id;
  }, [transaction, isCreateMode]);

  // Determine which fields can be edited
  const canEditDate = isCreateMode || (!isReadOnly && transaction?.source === 'ledger');
  const canEditAmounts = isCreateMode || (!isReadOnly && transaction?.source === 'ledger');
  const canEditCategory = isCreateMode || !isReadOnly;
  const canEditPayee = true; // Always editable
  const canEditDescription = true; // Always editable

  // Validate form
  const validate = () => {
    const newErrors = {};

    if (!date) {
      newErrors.date = gettext('Date is required');
    }

    if (!category) {
      newErrors.category = gettext('Category is required');
    }

    const hasInflow = inflow && parseFloat(inflow) > 0;
    const hasOutflow = outflow && parseFloat(outflow) > 0;

    if (!hasInflow && !hasOutflow) {
      newErrors.amount = gettext('Either inflow or outflow is required');
    }
    if (hasInflow && hasOutflow) {
      newErrors.amount = gettext('Cannot have both inflow and outflow');
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  // Handle save
  const handleSave = async () => {
    if (!validate()) return;

    setSaving(true);
    try {
      if (isCreateMode) {
        // Create mode - send new transaction data
        const newData = {
          source: 'manual',
          date: date,
          category: category ? { id: category.id, name: category.name, account_number: category.accountNumber } : null,
          inflow: inflow || '0',
          outflow: outflow || '0',
          payee: payee,
          description: description,
        };
        await onSave(newData, 'create');
      } else {
        // Edit mode - send updated transaction data
        const updatedData = {
          id: transaction.id,
          source: transaction.source,
          journal_entry_id: transaction.journal_entry_id,
          date: canEditDate ? date : transaction.postedDate,
          category: canEditCategory && category ? { id: category.id, name: category.name, account_number: category.accountNumber } : transaction.category,
          inflow: canEditAmounts ? (inflow || '0') : transaction.inflow,
          outflow: canEditAmounts ? (outflow || '0') : transaction.outflow,
          payee: payee,
          description: description,
        };
        await onSave(updatedData, 'edit');
      }
      onClose();
    } catch (error) {
      console.error('Failed to save transaction:', error);
      setErrors({ submit: error.message || gettext('Failed to save transaction') });
    } finally {
      setSaving(false);
    }
  };

  // Handle inflow change (clear outflow if inflow has value)
  const handleInflowChange = (e) => {
    const value = e.target.value;
    setInflow(value);
    if (value && parseFloat(value) > 0) {
      setOutflow('');
    }
  };

  // Handle outflow change (clear inflow if outflow has value)
  const handleOutflowChange = (e) => {
    const value = e.target.value;
    setOutflow(value);
    if (value && parseFloat(value) > 0) {
      setInflow('');
    }
  };

  // Don't render if not open (but we handle create mode now)
  if (!open) return null;

  const title = isCreateMode ? gettext('Add Transaction') : gettext('Edit Transaction');
  const saveButtonText = isCreateMode
    ? (saving ? gettext('Adding...') : gettext('Add'))
    : (saving ? gettext('Saving...') : gettext('Save'));

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, mt: 1 }}>
          {/* Date */}
          <LocalizationProvider dateAdapter={AdapterDateFns}>
            <DatePicker
              label={gettext('Date')}
              value={date}
              onChange={(newValue) => setDate(newValue)}
              disabled={!canEditDate}
              slotProps={{
                textField: {
                  fullWidth: true,
                  size: 'small',
                  error: !!errors.date,
                  helperText: errors.date || (!canEditDate && !isCreateMode ? gettext('Date cannot be edited for this transaction type') : ''),
                },
              }}
            />
          </LocalizationProvider>

          {/* Category */}
          <Autocomplete
            value={category}
            onChange={(_event, newValue) => setCategory(newValue)}
            options={categoryOptions}
            groupBy={(option) => option.groupLabel}
            getOptionLabel={(option) => option.label}
            isOptionEqualToValue={(option, value) => option.id === value.id}
            disabled={!canEditCategory}
            renderInput={(params) => (
              <TextField
                {...params}
                label={gettext('Category')}
                size="small"
                error={!!errors.category}
                helperText={errors.category || (!canEditCategory && !isCreateMode ? gettext('Category cannot be edited for this transaction') : '')}
              />
            )}
          />

          {/* Inflow and Outflow */}
          <Box sx={{ display: 'flex', gap: 2 }}>
            <TextField
              label={gettext('Inflow')}
              type="number"
              value={inflow}
              onChange={handleInflowChange}
              disabled={!canEditAmounts}
              fullWidth
              size="small"
              inputProps={{ step: '0.01', min: '0' }}
              InputProps={{
                startAdornment: <InputAdornment position="start">$</InputAdornment>,
              }}
              error={!!errors.amount}
              helperText={!canEditAmounts && !isCreateMode ? gettext('Amount cannot be edited') : ''}
            />
            <TextField
              label={gettext('Outflow')}
              type="number"
              value={outflow}
              onChange={handleOutflowChange}
              disabled={!canEditAmounts}
              fullWidth
              size="small"
              inputProps={{ step: '0.01', min: '0' }}
              InputProps={{
                startAdornment: <InputAdornment position="start">$</InputAdornment>,
              }}
              error={!!errors.amount}
            />
          </Box>
          {errors.amount && (
            <Box sx={{ color: 'error.main', fontSize: '0.75rem', mt: -1 }}>
              {errors.amount}
            </Box>
          )}

          {/* Payee */}
          <TextField
            label={gettext('Payee')}
            value={payee}
            onChange={(e) => setPayee(e.target.value)}
            fullWidth
            size="small"
          />

          {/* Description */}
          <TextField
            label={gettext('Description')}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            fullWidth
            size="small"
            multiline
            rows={2}
          />

          {/* Submit error */}
          {errors.submit && (
            <Box sx={{ color: 'error.main', fontSize: '0.875rem' }}>
              {errors.submit}
            </Box>
          )}
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={saving}>
          {gettext('Cancel')}
        </Button>
        <Button onClick={handleSave} variant="contained" disabled={saving}>
          {saveButtonText}
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export default EditTransactionModal;
