import React, { useState, useMemo } from 'react';
import {
  Autocomplete,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  TextField,
  Typography,
} from '@mui/material';
import { DatePicker } from '@mui/x-date-pickers/DatePicker';
import { LocalizationProvider } from '@mui/x-date-pickers/LocalizationProvider';
import { AdapterDateFns } from '@mui/x-date-pickers/AdapterDateFns';
import { buildCategoryOptions } from '../../common/categoryOptions';

/* globals gettext */

/**
 * BulkEditModal - Modal for bulk editing selected bank feed transactions.
 * All fields are optional. Only fields with values are sent to the API.
 * Fields left blank are not updated.
 *
 * Props:
 * - open: boolean
 * - onClose: function
 * - selectedCount: number - count of selected transactions
 * - allAccounts: array - all accounts for category dropdown
 * - bankFeedAccounts: array - accounts with has_feed for move dropdown
 * - onSave: function({ category_id, account_id, payee, description, date }) - called with non-null fields
 */
const BulkEditModal = ({
  open,
  onClose,
  selectedCount,
  allAccounts,
  bankFeedAccounts,
  onSave,
}) => {
  const [date, setDate] = useState(null);
  const [category, setCategory] = useState(null);
  const [account, setAccount] = useState(null);
  const [payee, setPayee] = useState('');
  const [description, setDescription] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  // Category options grouped by account type
  const categoryOptions = useMemo(() => {
    return buildCategoryOptions(allAccounts);
  }, [allAccounts]);

  // Account options (bank feed accounts for "move")
  const accountOptions = useMemo(() => {
    return (bankFeedAccounts || []).map((acc) => ({
      id: acc.id,
      label: acc.name,
      name: acc.name,
    }));
  }, [bankFeedAccounts]);

  // Reset form when dialog opens
  const handleEnter = () => {
    setDate(null);
    setCategory(null);
    setAccount(null);
    setPayee('');
    setDescription('');
    setError(null);
    setSaving(false);
  };

  // Check if anything has been filled in
  const hasChanges = date || category || account || payee.trim() || description.trim();

  const handleSave = async () => {
    if (!hasChanges) return;

    setSaving(true);
    setError(null);
    try {
      const updates = {};
      if (category) updates.category_id = category.id;
      if (account) updates.account_id = account.id;
      if (payee.trim()) updates.payee = payee.trim();
      if (description.trim()) updates.description = description.trim();
      if (date) {
        // Format date as YYYY-MM-DD
        const d = date instanceof Date ? date : new Date(date);
        updates.date = d.toISOString().split('T')[0];
      }
      await onSave(updates);
      onClose();
    } catch (err) {
      console.error('Bulk edit failed:', err);
      setError(err.message || gettext('Failed to update transactions'));
    } finally {
      setSaving(false);
    }
  };

  if (!open) return null;

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="sm"
      fullWidth
      TransitionProps={{ onEnter: handleEnter }}
    >
      <DialogTitle>{gettext('Bulk Edit')} ({selectedCount} {gettext('selected')})</DialogTitle>
      <DialogContent>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          {gettext('Only fields you fill in will be updated. Leave fields blank to keep existing values.')}
        </Typography>

        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, mt: 1 }}>
          {/* Date */}
          <LocalizationProvider dateAdapter={AdapterDateFns}>
            <DatePicker
              label={gettext('Date')}
              value={date}
              onChange={(newValue) => setDate(newValue)}
              slotProps={{
                textField: {
                  fullWidth: true,
                  size: 'small',
                  placeholder: gettext('Leave blank to keep existing'),
                },
                field: { clearable: true },
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
            isOptionEqualToValue={(option, value) => option.id === value?.id}
            renderInput={(params) => (
              <TextField
                {...params}
                label={gettext('Category')}
                size="small"
                placeholder={gettext('Leave blank to keep existing')}
              />
            )}
          />

          {/* Move to Account */}
          <Autocomplete
            value={account}
            onChange={(_event, newValue) => setAccount(newValue)}
            options={accountOptions}
            getOptionLabel={(option) => option.label}
            isOptionEqualToValue={(option, value) => option.id === value?.id}
            renderInput={(params) => (
              <TextField
                {...params}
                label={gettext('Move to Account')}
                size="small"
                placeholder={gettext('Leave blank to keep existing')}
              />
            )}
          />

          {/* Payee */}
          <TextField
            label={gettext('Payee')}
            value={payee}
            onChange={(e) => setPayee(e.target.value)}
            fullWidth
            size="small"
            placeholder={gettext('Leave blank to keep existing')}
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
            placeholder={gettext('Leave blank to keep existing')}
          />

          {/* Error */}
          {error && (
            <Box sx={{ color: 'error.main', fontSize: '0.875rem' }}>
              {error}
            </Box>
          )}
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={saving}>
          {gettext('Cancel')}
        </Button>
        <Button
          onClick={handleSave}
          variant="contained"
          disabled={saving || !hasChanges}
        >
          {saving ? gettext('Saving...') : gettext('Apply')}
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export default BulkEditModal;
