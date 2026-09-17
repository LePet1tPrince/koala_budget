import React, { useEffect, useMemo, useState } from 'react';
import Combobox from '../../common/Combobox';
import DateField from '../../common/DateField';
import Modal from '../../common/Modal';
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
  allPayees = [],
  bankFeedAccounts,
  onSave,
  hasReconciledRows = false,
}) => {
  const [date, setDate] = useState('');
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

  // Reset the form each time the dialog opens. MUI ran this from the enter
  // transition; a native <dialog> has no such hook, so it keys off `open`.
  useEffect(() => {
    if (!open) return;
    setDate('');
    setCategory(null);
    setAccount(null);
    setPayee('');
    setDescription('');
    setError(null);
    setSaving(false);
  }, [open]);

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
      // `DateField` already speaks ISO yyyy-MM-dd, which is what the API takes,
      // so there is no Date to normalize here any more.
      if (date) updates.date = date;
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
    <Modal
      open={open}
      onClose={onClose}
      size="sm"
      testId="bulk-edit-modal"
      title={`${gettext('Bulk Edit')} (${selectedCount} ${gettext('selected')})`}
      actions={
        <>
          <button type="button" className="btn btn-sm" onClick={onClose} disabled={saving}>
            {gettext('Cancel')}
          </button>
          <button
            type="button"
            className="btn btn-sm btn-primary"
            onClick={handleSave}
            disabled={saving || !hasChanges}
            data-testid="bulk-edit-apply"
          >
            {saving ? gettext('Saving...') : gettext('Apply')}
          </button>
        </>
      }
    >
      <p className="mb-4 text-sm text-base-content/70">
        {gettext('Only fields you fill in will be updated. Leave fields blank to keep existing values.')}
      </p>

      <div className="flex flex-col gap-4">
        <DateField label={gettext('Date')} value={date} onChange={setDate} allowClear testId="bulk-edit-date" />

        <Combobox
          label={gettext('Category')}
          value={category}
          onChange={setCategory}
          options={categoryOptions}
          getGroup={(option) => option.groupLabel}
          placeholder={gettext('Leave blank to keep existing')}
          testId="bulk-edit-category"
        />

        {/* Move to Account — hidden for reconciled transactions */}
        {!hasReconciledRows && (
          <Combobox
            label={gettext('Move to Account')}
            value={account}
            onChange={setAccount}
            options={accountOptions}
            placeholder={gettext('Leave blank to keep existing')}
            testId="bulk-edit-account"
          />
        )}

        <Combobox
          freeText
          label={gettext('Payee')}
          value={payee}
          onChange={setPayee}
          options={allPayees.map((pay) => pay.name)}
          placeholder={gettext('Leave blank to keep existing')}
          testId="bulk-edit-payee"
        />

        <label className="form-control w-full">
          <span className="label-text mb-1 block text-sm text-base-content/70">{gettext('Description')}</span>
          <textarea
            className="textarea textarea-bordered w-full"
            rows={2}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder={gettext('Leave blank to keep existing')}
            data-testid="bulk-edit-description"
          />
        </label>

        {error && <p className="text-sm text-error">{error}</p>}
      </div>
    </Modal>
  );
};

export default BulkEditModal;
