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

/* globals gettext */

/**
 * EditTransactionModal - Modal dialog for editing bank feed transactions
 * Supports editing: date, category, inflow/outflow, payee, and description
 */
const EditTransactionModal = ({
  open,
  onClose,
  transaction,
  allAccounts,
  onSave,
}) => {
  // Form state
  const [date, setDate] = useState(null);
  const [category, setCategory] = useState(null);
  const [inflow, setInflow] = useState('');
  const [outflow, setOutflow] = useState('');
  const [payee, setPayee] = useState('');
  const [description, setDescription] = useState('');
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);

  // Create options array for category Autocomplete (grouped by account number first letter)
  const categoryOptions = useMemo(() => {
    return allAccounts.map((account) => ({
      id: account.id,
      label: `${account.account_number} - ${account.name}`,
      accountNumber: account.account_number,
      name: account.name,
      firstLetter: String(account.account_number).charAt(0).toUpperCase(),
    })).sort((a, b) => -b.firstLetter.localeCompare(a.firstLetter));
  }, [allAccounts]);

  // Initialize form when transaction changes
  useEffect(() => {
    if (transaction) {
      // Parse date - handle both Date objects and strings
      const transactionDate = transaction.postedDate instanceof Date
        ? transaction.postedDate
        : transaction.postedDate ? new Date(transaction.postedDate) : null;
      setDate(transactionDate);

      // Find matching category option
      const categoryOption = transaction.category
        ? categoryOptions.find(opt => opt.id === transaction.category.id)
        : null;
      setCategory(categoryOption);

      // Parse amounts
      setInflow(transaction.inflow && parseFloat(transaction.inflow) > 0 ? transaction.inflow : '');
      setOutflow(transaction.outflow && parseFloat(transaction.outflow) > 0 ? transaction.outflow : '');

      // Set text fields
      setPayee(transaction.payee || '');
      setDescription(transaction.description || '');

      // Clear errors
      setErrors({});
    }
  }, [transaction, categoryOptions]);

  // Check if transaction is read-only (Plaid transactions without journal entry)
  const isReadOnly = useMemo(() => {
    if (!transaction) return false;
    // Plaid transactions that are not yet categorized (no journal_entry_id) can only have limited edits
    return transaction.source === 'plaid' && !transaction.journal_entry_id;
  }, [transaction]);

  // Determine which fields can be edited
  const canEditDate = !isReadOnly && transaction?.source === 'ledger';
  const canEditAmounts = !isReadOnly && transaction?.source === 'ledger';
  const canEditCategory = !isReadOnly;
  const canEditPayee = true; // Always editable
  const canEditDescription = true; // Always editable

  // Validate form
  const validate = () => {
    const newErrors = {};

    // Only validate date/category/amounts for editable transactions
    if (canEditDate && !date) {
      newErrors.date = gettext('Date is required');
    }

    if (canEditCategory && !category) {
      newErrors.category = gettext('Category is required');
    }

    if (canEditAmounts) {
      const hasInflow = inflow && parseFloat(inflow) > 0;
      const hasOutflow = outflow && parseFloat(outflow) > 0;

      if (!hasInflow && !hasOutflow) {
        newErrors.amount = gettext('Either inflow or outflow is required');
      }
      if (hasInflow && hasOutflow) {
        newErrors.amount = gettext('Cannot have both inflow and outflow');
      }
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  // Handle save
  const handleSave = async () => {
    if (!validate()) return;

    setSaving(true);
    try {
      const updatedData = {
        id: transaction.id,
        source: transaction.source,
        journal_entry_id: transaction.journal_entry_id,
        // Include editable fields
        date: canEditDate ? date : transaction.postedDate,
        category: canEditCategory && category ? { id: category.id, name: category.name, account_number: category.accountNumber } : transaction.category,
        inflow: canEditAmounts ? (inflow || '0') : transaction.inflow,
        outflow: canEditAmounts ? (outflow || '0') : transaction.outflow,
        payee: payee,
        description: description,
      };

      await onSave(updatedData);
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

  if (!transaction) return null;

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{gettext('Edit Transaction')}</DialogTitle>
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
                  helperText: errors.date || (!canEditDate ? gettext('Date cannot be edited for this transaction type') : ''),
                },
              }}
            />
          </LocalizationProvider>

          {/* Category */}
          <Autocomplete
            value={category}
            onChange={(_event, newValue) => setCategory(newValue)}
            options={categoryOptions}
            groupBy={(option) => option.firstLetter}
            getOptionLabel={(option) => option.label}
            isOptionEqualToValue={(option, value) => option.id === value.id}
            disabled={!canEditCategory}
            renderInput={(params) => (
              <TextField
                {...params}
                label={gettext('Category')}
                size="small"
                error={!!errors.category}
                helperText={errors.category || (!canEditCategory ? gettext('Category cannot be edited for this transaction') : '')}
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
              helperText={!canEditAmounts ? gettext('Amount cannot be edited') : ''}
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
          {saving ? gettext('Saving...') : gettext('Save')}
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export default EditTransactionModal;
