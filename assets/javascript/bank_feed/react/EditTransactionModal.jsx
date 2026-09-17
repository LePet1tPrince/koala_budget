import React, { useState, useEffect, useMemo } from 'react';
import Combobox from '../../common/Combobox';
import DateField from '../../common/DateField';
import Modal from '../../common/Modal';
import { buildCategoryOptions } from '../../common/categoryOptions';
import { formatDateForInput } from '../utils';
import TransactionHistory from './TransactionHistory';

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
  allPayees = [],
  categorySuggestions = {},
  teamSlug,
  onSave,
  mode: modeProp,
}) => {
  // Determine mode - create if no transaction, edit otherwise
  const mode = modeProp || (transaction ? 'edit' : 'create');
  const isCreateMode = mode === 'create';

  // Form state
  const [date, setDate] = useState('');
  const [category, setCategory] = useState(null);
  const [inflow, setInflow] = useState('');
  const [outflow, setOutflow] = useState('');
  const [payee, setPayee] = useState('');
  const [description, setDescription] = useState('');
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  // Whether the current category came from a merchant-history suggestion
  const [categorySuggested, setCategorySuggested] = useState(false);
  // Active tab: 0 = Details, 1 = History
  const [activeTab, setActiveTab] = useState(0);

  // Create options array for category Autocomplete (grouped by account type)
  const categoryOptions = useMemo(() => {
    return buildCategoryOptions(allAccounts);
  }, [allAccounts]);

  // Payee names for the free-text autocomplete
  const payeeOptions = useMemo(() => allPayees.map((p) => p.name), [allPayees]);

  // Initialize form when transaction changes or modal opens
  useEffect(() => {
    if (!open) return;

    setActiveTab(0);

    if (isCreateMode) {
      // Create mode - set defaults
      setDate(formatDateForInput(new Date()));
      setCategory(null);
      setInflow('');
      setOutflow('');
      setPayee('');
      setDescription('');
      setErrors({});
      setCategorySuggested(false);
    } else if (transaction) {
      // Edit mode - populate from transaction
      setDate(formatDateForInput(transaction.postedDate));

      let categoryOption = transaction.category
        ? categoryOptions.find(opt => opt.id === transaction.category.id)
        : null;
      let suggested = false;
      if (!categoryOption && transaction.payee && categorySuggestions[transaction.payee]) {
        // Uncategorized: pre-fill with how this merchant was last categorized
        const suggestion = categorySuggestions[transaction.payee];
        categoryOption = categoryOptions.find(opt => opt.id === suggestion.id) || null;
        suggested = Boolean(categoryOption);
      }
      setCategory(categoryOption);
      setCategorySuggested(suggested);

      setInflow(transaction.inflow && parseFloat(transaction.inflow) > 0 ? transaction.inflow : '');
      setOutflow(transaction.outflow && parseFloat(transaction.outflow) > 0 ? transaction.outflow : '');
      setPayee(transaction.payee || '');
      setDescription(transaction.description || '');
      setErrors({});
    }
  }, [open, transaction, categoryOptions, categorySuggestions, isCreateMode]);

  // Check if transaction is read-only (Plaid transactions without journal entry).
  // Rows come from the generated API client (camelCase), but tolerate snake_case
  // for callers passing raw API data.
  const journalEntryId = transaction?.journalEntryId ?? transaction?.journal_entry_id;
  const isReadOnly = useMemo(() => {
    if (isCreateMode || !transaction) return false;
    return transaction.source === 'plaid' && !journalEntryId;
  }, [transaction, isCreateMode, journalEntryId]);

  // Determine which fields can be edited
  const canEditDate = isCreateMode || (!isReadOnly && transaction?.source !== 'plaid');
  const canEditAmounts = isCreateMode || (!isReadOnly && transaction?.source !== 'plaid' && !transaction?.is_reconciled);
  const canEditCategory = isCreateMode || !isReadOnly;
  const canEditPayee = true; // Always editable
  const canEditDescription = true; // Always editable

  // Validate form
  const validate = () => {
    const newErrors = {};

    if (!date) {
      newErrors.date = gettext('Date is required');
    }

    // Category is optional — a blank category leaves the transaction uncategorized.

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
          journal_entry_id: journalEntryId,
          date: canEditDate ? date : transaction.postedDate,
          category: canEditCategory ? (category ? { id: category.id, name: category.name, account_number: category.accountNumber } : null) : transaction.category,
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

  // The History tab is only meaningful for an existing, categorized transaction.
  const showHistoryTab = !isCreateMode && Boolean(journalEntryId);

  const onHistoryTab = activeTab === 1 && showHistoryTab;

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="sm"
      testId="edit-transaction-modal"
      title={title}
      actions={
        <>
          <button type="button" className="btn btn-sm" onClick={onClose} disabled={saving} data-testid="modal-cancel-btn">
            {onHistoryTab ? gettext('Close') : gettext('Cancel')}
          </button>
          {!onHistoryTab && (
            <button
              type="button"
              className="btn btn-sm btn-primary"
              onClick={handleSave}
              disabled={saving}
              data-testid="modal-save-btn"
            >
              {saveButtonText}
            </button>
          )}
        </>
      }
    >
      {showHistoryTab && (
        <div role="tablist" className="tabs tabs-border mb-4">
          <button
            type="button"
            role="tab"
            className={`tab ${activeTab === 0 ? 'tab-active' : ''}`}
            aria-selected={activeTab === 0}
            onClick={() => setActiveTab(0)}
            data-testid="tab-details"
          >
            {gettext('Details')}
          </button>
          <button
            type="button"
            role="tab"
            className={`tab ${activeTab === 1 ? 'tab-active' : ''}`}
            aria-selected={activeTab === 1}
            onClick={() => setActiveTab(1)}
            data-testid="tab-history"
          >
            {gettext('History')}
          </button>
        </div>
      )}

      {onHistoryTab ? (
        <TransactionHistory teamSlug={teamSlug} journalEntryId={journalEntryId} />
      ) : (
        <div className="flex flex-col gap-4">
          <DateField
            label={gettext('Date')}
            value={date}
            onChange={setDate}
            testId="transaction-date"
            className={!canEditDate ? 'pointer-events-none opacity-60' : ''}
          />
          {(errors.date || (!canEditDate && !isCreateMode)) && (
            <p className={`-mt-3 text-xs ${errors.date ? 'text-error' : 'text-base-content/70'}`}>
              {errors.date || gettext('Date cannot be edited for this transaction type')}
            </p>
          )}

          <Combobox
            label={gettext('Category (optional)')}
            value={category}
            onChange={(newValue) => {
              setCategory(newValue);
              setCategorySuggested(false);
            }}
            options={categoryOptions}
            getGroup={(option) => option.groupLabel}
            disabled={!canEditCategory}
            error={errors.category}
            helperText={
              (categorySuggested && gettext('Suggested from how this payee was last categorized'))
              || (!canEditCategory && !isCreateMode && gettext('Category cannot be edited for this transaction'))
              || ''
            }
            testId="transaction-category"
          />

          <div className="flex gap-4">
            <label className="form-control w-full">
              <span className="label-text mb-1 block text-sm text-base-content/70">{gettext('Inflow')}</span>
              <label className={`input input-bordered flex w-full items-center gap-1 ${errors.amount ? 'input-error' : ''}`}>
                <span className="text-base-content/70">$</span>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  className="w-full"
                  value={inflow}
                  onChange={handleInflowChange}
                  disabled={!canEditAmounts}
                  data-testid="transaction-inflow"
                />
              </label>
              {!canEditAmounts && !isCreateMode && (
                <span className="mt-1 block text-xs text-base-content/70">
                  {transaction?.is_reconciled
                    ? gettext('Amount locked — transaction is reconciled')
                    : gettext('Amount cannot be edited')}
                </span>
              )}
            </label>

            <label className="form-control w-full">
              <span className="label-text mb-1 block text-sm text-base-content/70">{gettext('Outflow')}</span>
              <label className={`input input-bordered flex w-full items-center gap-1 ${errors.amount ? 'input-error' : ''}`}>
                <span className="text-base-content/70">$</span>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  className="w-full"
                  value={outflow}
                  onChange={handleOutflowChange}
                  disabled={!canEditAmounts}
                  data-testid="transaction-outflow"
                />
              </label>
            </label>
          </div>
          {errors.amount && <p className="-mt-2 text-xs text-error">{errors.amount}</p>}

          <Combobox
            freeText
            label={gettext('Payee')}
            value={payee}
            onChange={setPayee}
            options={payeeOptions}
            testId="transaction-payee"
          />

          <label className="form-control w-full">
            <span className="label-text mb-1 block text-sm text-base-content/70">{gettext('Description')}</span>
            <textarea
              className="textarea textarea-bordered w-full"
              rows={2}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              data-testid="transaction-description"
            />
          </label>

          {errors.submit && <p className="text-sm text-error">{errors.submit}</p>}
        </div>
      )}
    </Modal>
  );
};

export default EditTransactionModal;
