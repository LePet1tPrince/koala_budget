import React, { useState, useEffect, useMemo, useRef } from 'react';
import Combobox from '../../common/Combobox';
import DateField from '../../common/DateField';
import Modal from '../../common/Modal';
import { buildCategoryOptions } from '../../common/categoryOptions';
import { goalOverspendHint } from '../../common/accountKind';
import { parseAmount, round2 } from '../../common/amount';
import { formatDateForInput } from '../utils';
import SplitEditor, { MIN_LEGS } from './SplitEditor';
import TransactionHistory from './TransactionHistory';

/* globals gettext */

/** Stable client-side keys for leg rows, so React never re-mounts a field mid-edit. */
let legKeySeq = 0;
const nextLegKey = () => {
  legKeySeq += 1;
  return `leg-${legKeySeq}`;
};

/** A leg's amount as the input should show it: signed, two decimals, no symbol. */
const formatLegAmount = (value) => {
  const parsed = parseAmount(value);
  return parsed === null ? '' : parsed.toFixed(2);
};

/**
 * Read a field from a row in whichever shape the caller has.
 *
 * Rows from the generated API client are camelCase; categorize mode and the
 * CSV wizard hand over raw API data, which is snake_case. This modal already
 * did that dance for `journal_entry_id` one field at a time — doing it in one
 * place is what stops the next field from silently reading `undefined`, which
 * is exactly what `is_reconciled` had been doing for every camelCase caller,
 * leaving the amount fields editable on a reconciled transaction until the
 * server refused the save.
 */
const field = (row, camel, snake) => row?.[camel] ?? row?.[snake];

/**
 * Stable empty defaults for the optional props.
 *
 * A `= {}` default is a *new* object on every render, and `categorySuggestions`
 * is in the init effect's dependency array — so a caller that omitted the prop
 * got: effect runs -> setSplits -> render -> fresh `{}` -> effect runs again,
 * forever. Measured at ~39,000 DOM mutations a second, with the symptom that
 * the modal renders correctly and then ignores every keystroke, because each
 * one is undone by the next render. Module-level constants keep the identity
 * stable across renders and cost nothing.
 */
const NO_SUGGESTIONS = {};
const NO_PAYEES = [];

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
  allPayees = NO_PAYEES,
  categorySuggestions = NO_SUGGESTIONS,
  teamSlug,
  onSave,
  mode: modeProp,
  startSplit: startSplitOnOpen = false,
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
  // Split legs, or null when this transaction has a single category.
  // Each leg: { key, category, amount } -- `amount` is the raw typed string.
  const [splits, setSplits] = useState(null);
  // True once the user has removed a split, so the save asks the server to
  // collapse it rather than being refused for omitting the legs.
  const [removedSplit, setRemovedSplit] = useState(false);

  // Create options array for category Autocomplete (grouped by account type)
  const categoryOptions = useMemo(() => {
    return buildCategoryOptions(allAccounts, { keep: transaction?.category ? [transaction.category] : [] });
  }, [allAccounts, transaction]);

  // Payee names for the free-text autocomplete
  const payeeOptions = useMemo(() => allPayees.map((p) => p.name), [allPayees]);

  // Initialize form when transaction changes or modal opens
  useEffect(() => {
    if (!open) return;

    setActiveTab(0);

    setSplits(null);
    setRemovedSplit(false);

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
      setDate(formatDateForInput(field(transaction, 'postedDate', 'posted_date')));

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

      // Rows arrive from the generated client in camelCase, but some callers
      // pass raw API data -- tolerate both, as the journalEntryId read below does.
      const rowSplits = transaction.splits ?? transaction.split_legs ?? [];
      if (rowSplits.length > 0) {
        setSplits(
          rowSplits.map((leg) => {
            const categoryId = leg.categoryId ?? leg.category_id;
            return {
              key: nextLegKey(),
              category: categoryOptions.find((opt) => opt.id === categoryId) || null,
              amount: formatLegAmount(leg.amount),
            };
          }),
        );
      } else if (startSplitOnOpen) {
        // Opened from categorize mode's Split button, where splitting is the
        // whole reason the modal is on screen -- so it starts in split mode
        // rather than behind another click. Seeded the same way `startSplit()`
        // below does: the first leg carries the total, so Remaining opens at
        // $0.00 rather than at the full amount outstanding.
        const openingTotal = round2(
          (parseAmount(transaction.outflow) ?? 0) - (parseAmount(transaction.inflow) ?? 0),
        );
        setSplits([
          { key: nextLegKey(), category: null, amount: openingTotal ? openingTotal.toFixed(2) : '' },
          { key: nextLegKey(), category: null, amount: '' },
        ]);
      }
    }
  }, [open, transaction, categoryOptions, categorySuggestions, isCreateMode, startSplitOnOpen]);

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
  const isReconciled = Boolean(field(transaction, 'isReconciled', 'is_reconciled'));
  const canEditAmounts = isCreateMode || (!isReadOnly && transaction?.source !== 'plaid' && !isReconciled);
  const canEditCategory = isCreateMode || !isReadOnly;
  const canEditPayee = true; // Always editable
  const canEditDescription = true; // Always editable

  // --- splits ----------------------------------------------------------

  const isSplit = splits !== null;

  // Signed transaction total, positive for an outflow -- the same convention
  // the server uses, so the legs mean the same thing on both sides.
  const total = useMemo(
    () => round2((parseAmount(outflow) ?? 0) - (parseAmount(inflow) ?? 0)),
    [inflow, outflow],
  );

  // "Car will go to −$1,500 — that's fine, it's carried". The goal's `left`
  // already includes this transaction's own spend when it is already on the
  // goal, so only the change counts.
  const goalHint = useMemo(() => {
    if (!category?.account) return null;
    let spend = total;
    if (!isCreateMode && transaction?.category?.id === category.id) {
      spend -= round2((parseAmount(transaction.outflow) ?? 0) - (parseAmount(transaction.inflow) ?? 0));
    }
    return goalOverspendHint(category.account, spend);
  }, [category, total, isCreateMode, transaction]);

  const legSum = useMemo(
    () => round2((splits ?? []).reduce((acc, leg) => acc + (parseAmount(leg.amount) ?? 0), 0)),
    [splits],
  );

  const remaining = round2(total - legSum);
  // Compared with a cent tolerance, never `===`: 0.1 + 0.2 !== 0.3 in floating point.
  const isBalanced = Math.abs(remaining) < 0.005;

  const updateLeg = (index, patch) =>
    setSplits((current) => current.map((leg, i) => (i === index ? { ...leg, ...patch } : leg)));

  const addLeg = () => setSplits((current) => [...current, { key: nextLegKey(), category: null, amount: '' }]);

  const removeLeg = (index) => setSplits((current) => current.filter((_, i) => i !== index));

  const startSplit = () => {
    // The first leg carries the whole total, so Remaining starts at $0.00 and
    // goes negative as the second is typed -- which reads as "you have
    // over-assigned". Two blank legs would instead greet the user with the full
    // amount outstanding before they had done anything wrong.
    setSplits([
      { key: nextLegKey(), category, amount: total ? total.toFixed(2) : '' },
      { key: nextLegKey(), category: null, amount: '' },
    ]);
    setRemovedSplit(false);
  };

  const removeSplit = () => {
    // Collapse onto the largest leg by absolute amount: of the categories the
    // user chose, that is the likeliest one they meant the transaction to be.
    const largest = [...splits]
      .filter((leg) => leg.category)
      .sort((a, b) => Math.abs(parseAmount(b.amount) ?? 0) - Math.abs(parseAmount(a.amount) ?? 0))[0];
    setCategory(largest ? largest.category : null);
    setCategorySuggested(false);
    setSplits(null);
    // Only meaningful for a transaction that *was* split on the server; harmless
    // when the user split and unsplit without saving.
    setRemovedSplit(true);
  };

  const assignRemainder = () => {
    const blank = splits.findIndex((leg) => parseAmount(leg.amount) === null);
    const target = blank === -1 ? splits.length - 1 : blank;
    const current = blank === -1 ? (parseAmount(splits[target].amount) ?? 0) : 0;
    updateLeg(target, { amount: round2(current + remaining).toFixed(2) });
  };

  /** The first thing wrong with the legs, or null. */
  const splitProblem = () => {
    if (!isSplit) return null;
    if (splits.length < MIN_LEGS) return gettext('A split needs at least two categories.');
    if (splits.some((leg) => !leg.category)) return gettext('Every split needs a category.');
    const bad = splits.findIndex((leg) => parseAmount(leg.amount) === null);
    if (bad !== -1) return gettext('Every split needs an amount.');
    if (splits.some((leg) => parseAmount(leg.amount) === 0)) return gettext('A split amount cannot be zero.');
    if (!isBalanced) return gettext('The splits must add up to the transaction total.');
    return null;
  };

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

    const problem = splitProblem();
    if (problem) {
      newErrors.splits = problem;
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  // Handle save
  const handleSave = async () => {
    if (!validate()) return;

    setSaving(true);
    try {
      // Amounts go over the wire as strings, so no float ever reaches the
      // server's Decimal. `splits` and `category` are mutually exclusive.
      const splitPayload = isSplit
        ? splits.map((leg) => ({ category: leg.category.id, amount: parseAmount(leg.amount).toFixed(2) }))
        : null;

      if (isCreateMode) {
        // Create mode - send new transaction data
        const newData = {
          source: 'manual',
          date: date,
          category: isSplit
            ? null
            : category
              ? { id: category.id, name: category.name, account_number: category.accountNumber }
              : null,
          splits: splitPayload,
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
          date: canEditDate ? date : field(transaction, 'postedDate', 'posted_date'),
          category: isSplit
            ? null
            : canEditCategory ? (category ? { id: category.id, name: category.name, account_number: category.accountNumber } : null) : transaction.category,
          splits: splitPayload,
          // Collapsing a split is destructive, so the server requires it to be
          // asked for rather than inferred from a payload with no legs.
          remove_split: removedSplit && !isSplit,
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
      // The leg table needs the width; a single category does not.
      size={isSplit ? 'lg' : 'sm'}
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
              // An unbalanced split cannot be saved. The server enforces this too,
              // but a disabled button explains itself sooner than a 400 does.
              disabled={saving || Boolean(splitProblem())}
              title={splitProblem() || ''}
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

          {isSplit ? (
            <SplitEditor
              legs={splits}
              categoryOptions={categoryOptions}
              total={total}
              legSum={legSum}
              remaining={remaining}
              isBalanced={isBalanced}
              disabled={!canEditCategory}
              onChangeLeg={updateLeg}
              onAddLeg={addLeg}
              onRemoveLeg={removeLeg}
              onAssignRemainder={assignRemainder}
              onRemoveSplit={removeSplit}
            />
          ) : (
            <>
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
                  || goalHint
                  || ''
                }
                testId="transaction-category"
              />
              {canEditCategory && (
                <div className="-mt-2">
                  <button
                    type="button"
                    className="btn btn-ghost btn-xs"
                    onClick={startSplit}
                    data-testid="start-split-btn"
                  >
                    {gettext('Split this transaction')}
                  </button>
                </div>
              )}
            </>
          )}
          {errors.splits && (
            <p className="-mt-2 text-xs text-error" data-testid="split-error">
              {errors.splits}
            </p>
          )}

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
                  {isReconciled
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
