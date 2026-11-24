/* globals gettext */

import React, { useEffect, useMemo, useRef, useState } from 'react';

import AmountInput from '../../common/AmountInput';
import Combobox from '../../common/Combobox';
import DateField from '../../common/DateField';
import Icon from '../../common/Icon';
import Modal from '../../common/Modal';
import Spinner from '../../common/Spinner';
import { goalOverspendHint } from '../../common/accountKind';
import { parseAmount, round2 } from '../../common/amount';
import { buildCategoryOptions } from '../../common/categoryOptions';
import { formatDateForInput } from '../utils';
import RecurrenceFields, { emptyRecurrence, recurrencePayload, recurrenceProblem } from './RecurrenceFields';
import SplitEditor, { MIN_LEGS } from './SplitEditor';
import TransactionHistory from './TransactionHistory';
import useCreateAccount from './useCreateAccount';

/**
 * Adding or editing one transaction: an **account** (where the money sat), a
 * **category** -- or several, when it is split -- and the amount, date, payee and
 * description. Nothing here says debit or credit.
 *
 * `source` adapts one API's row: `source.read(transaction)` gives the starting
 * values and what is locked (`{ values, locked, canSplit, historyId, ... }`), and
 * `source.payload(form, transaction, read)` gives what `onSave(payload, mode)`
 * receives -- null when there is nothing to save. See `feedTransaction` (the feed
 * API) and `transactions/ledgerTransaction` (the transactions API).
 *
 * `transaction` null adds a new one. `accounts`, when given, offers an Account
 * picker (preset to `defaultAccountId` when adding). `onDelete`/`onSetStatus`
 * add Delete and Void/Restore where `read` allows them.
 */

/** Stable keys for leg rows, so React never re-mounts a field mid-edit. */
let legKeySeq = 0;
const nextLegKey = () => {
  legKeySeq += 1;
  return `leg-${legKeySeq}`;
};

/** A leg's amount as the input shows it: signed, two decimals, no symbol. */
const formatLegAmount = (value) => {
  const parsed = parseAmount(value);
  return parsed === null ? '' : parsed.toFixed(2);
};

const signedTotal = (inflow, outflow) => round2((parseAmount(outflow) ?? 0) - (parseAmount(inflow) ?? 0));

/** The first thing wrong with a split's legs, or null. */
const firstSplitProblem = (legs, isBalanced) => {
  if (legs.length < MIN_LEGS) return gettext('A split needs at least two categories.');
  if (legs.some((leg) => !leg.category)) return gettext('Every split needs a category.');
  if (legs.some((leg) => parseAmount(leg.amount) === null)) return gettext('Every split needs an amount.');
  if (legs.some((leg) => parseAmount(leg.amount) === 0)) return gettext('A split amount cannot be zero.');
  if (!isBalanced) return gettext('The splits must add up to the transaction total.');
  return null;
};

/**
 * Stable empty defaults. A `= {}` default is a new object every render, and the
 * opening effect depends on `categorySuggestions`: a fresh object re-ran it on
 * every render, undoing each keystroke.
 */
const NO_SUGGESTIONS = {};
const NO_PAYEES = [];
const NO_LOCKS = {};

const TransactionModal = ({
  open,
  onClose,
  transaction,
  source,
  allAccounts,
  allPayees = NO_PAYEES,
  book,
  onSave,
  onDelete,
  onSetStatus,
  onAccountCreated,
  accounts,
  defaultAccountId = null,
  categorySuggestions = NO_SUGGESTIONS,
  startSplit: startSplitOnOpen = false,
  allowRecurring = false,
}) => {
  const isCreate = !transaction;
  const tx = useMemo(() => (transaction ? source.read(transaction) : null), [transaction, source]);
  const locked = tx?.locked ?? NO_LOCKS;
  const frozen = Boolean(locked.all);
  const isLocked = (key) => frozen || Boolean(locked[key]);
  // Per-field reasons give way to the one banner when the whole row is locked.
  const lockNote = (key) => (!frozen && locked[key]) || '';

  const [account, setAccount] = useState(null);
  const [date, setDate] = useState('');
  const [category, setCategory] = useState(null);
  const [categorySuggested, setCategorySuggested] = useState(false);
  const [inflow, setInflow] = useState('');
  const [outflow, setOutflow] = useState('');
  const [payee, setPayee] = useState('');
  const [description, setDescription] = useState('');
  // Split legs ({ key, category, amount: raw string }), or null for one category.
  const [splits, setSplits] = useState(null);
  // Set once a split is removed, so the save asks the server to collapse it.
  const [removedSplit, setRemovedSplit] = useState(false);
  const [isRecurring, setIsRecurring] = useState(false);
  const [recurrence, setRecurrence] = useState(emptyRecurrence);
  const [activeTab, setActiveTab] = useState(0);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);

  // Categories and accounts the row already uses stay on offer even when hidden
  // or system, so opening it never blanks a field.
  const categoryOptions = useMemo(() => {
    const ids = new Set([tx?.values.categoryId, ...(tx?.values.legs ?? []).map((leg) => leg.categoryId)]);
    return buildCategoryOptions(allAccounts, { keep: (allAccounts || []).filter((a) => ids.has(a.id)) });
  }, [allAccounts, tx]);
  // Only somewhere money sits; named plainly, since every one is a "Transfer".
  const accountOptions = useMemo(() => {
    if (!accounts?.length) return null;
    const keep = accounts.filter((a) => a.id === (tx?.values.accountId ?? defaultAccountId));
    return buildCategoryOptions(accounts, { filterTypes: ['asset', 'liability'], keep }).map((option) => ({
      ...option,
      label: option.name,
    }));
  }, [accounts, tx, defaultAccountId]);
  const payeeOptions = useMemo(() => allPayees.map((p) => p.name), [allPayees]);
  // Read by the opening effect without being its triggers: a caller adding a
  // just-created account to `allAccounts` must not reset the form.
  const optionsRef = useRef({ categoryOptions, accountOptions });
  optionsRef.current = { categoryOptions, accountOptions };

  // "Create account" in the Category picker: the new account is selected at once.
  const accountCreator = useCreateAccount(book, (created) => {
    const [option] = buildCategoryOptions([created]);
    if (option) {
      setCategory(option);
      setCategorySuggested(false);
    }
    onAccountCreated?.(created);
  });
  // Accounts created here, until the caller's `allAccounts` carries them.
  const pickerOptions = useMemo(() => {
    const known = new Set(categoryOptions.map((o) => o.id));
    const extra = buildCategoryOptions(accountCreator.created).filter((o) => !known.has(o.id));
    return extra.length ? [...categoryOptions, ...extra] : categoryOptions;
  }, [categoryOptions, accountCreator.created]);

  useEffect(() => {
    if (!open) return;
    const options = optionsRef.current;
    const find = (list, id) => (id == null ? null : (list || []).find((o) => o.id === id) || null);
    const values = tx?.values ?? {
      accountId: defaultAccountId,
      date: formatDateForInput(new Date()),
      payee: '',
      description: '',
      categoryId: null,
      inflow: '',
      outflow: '',
      legs: null,
    };

    setActiveTab(0);
    setErrors({});
    setConfirmingDelete(false);
    setRemovedSplit(false);
    setIsRecurring(false);
    setRecurrence(emptyRecurrence());
    setAccount(find(options.accountOptions, values.accountId));
    setDate(values.date);
    setPayee(values.payee);
    setDescription(values.description);
    setInflow(values.inflow);
    setOutflow(values.outflow);

    // Uncategorized: pre-fill with how this payee was last categorized.
    let picked = find(options.categoryOptions, values.categoryId);
    const suggestion = !picked && !values.legs && categorySuggestions[values.payee];
    if (suggestion) picked = find(options.categoryOptions, suggestion.id);
    setCategory(picked);
    setCategorySuggested(Boolean(suggestion && picked));

    if (values.legs) {
      setSplits(
        values.legs.map((leg) => ({
          key: nextLegKey(),
          category: find(options.categoryOptions, leg.categoryId),
          amount: formatLegAmount(leg.amount),
        })),
      );
    } else if (tx && startSplitOnOpen) {
      // Opened from Categorize Mode's Split button, where splitting is the reason
      // the modal is on screen. Seeded as `startSplit` below seeds it.
      const opening = signedTotal(values.inflow, values.outflow);
      setSplits([
        { key: nextLegKey(), category: null, amount: opening ? opening.toFixed(2) : '' },
        { key: nextLegKey(), category: null, amount: '' },
      ]);
    } else {
      setSplits(null);
    }
  }, [open, tx, categorySuggestions, startSplitOnOpen, defaultAccountId]);

  // --- splits ----------------------------------------------------------

  const isSplit = splits !== null;
  // Signed, positive for an outflow -- the server's convention, so a leg means
  // the same thing on both sides.
  const total = useMemo(() => signedTotal(inflow, outflow), [inflow, outflow]);
  const legSum = useMemo(
    () => round2((splits ?? []).reduce((acc, leg) => acc + (parseAmount(leg.amount) ?? 0), 0)),
    [splits],
  );
  const remaining = round2(total - legSum);
  // A cent tolerance, never `===`: 0.1 + 0.2 !== 0.3 in floating point.
  const isBalanced = Math.abs(remaining) < 0.005;

  const updateLeg = (index, patch) =>
    setSplits((current) => current.map((leg, i) => (i === index ? { ...leg, ...patch } : leg)));
  const addLeg = () => setSplits((current) => [...current, { key: nextLegKey(), category: null, amount: '' }]);
  const removeLeg = (index) => setSplits((current) => current.filter((_, i) => i !== index));

  const startSplit = () => {
    // The first leg carries the whole total, so Remaining opens at $0.00 and goes
    // negative as the second is typed -- "you have over-assigned" -- rather than
    // greeting the user with the full amount outstanding.
    setSplits([
      { key: nextLegKey(), category, amount: total ? total.toFixed(2) : '' },
      { key: nextLegKey(), category: null, amount: '' },
    ]);
    setRemovedSplit(false);
  };

  const removeSplit = () => {
    // Collapse onto the largest leg: the likeliest category the user meant.
    const largest = [...splits]
      .filter((leg) => leg.category)
      .sort((a, b) => Math.abs(parseAmount(b.amount) ?? 0) - Math.abs(parseAmount(a.amount) ?? 0))[0];
    setCategory(largest ? largest.category : null);
    setCategorySuggested(false);
    setSplits(null);
    setRemovedSplit(true);
  };

  const assignRemainder = () => {
    const blank = splits.findIndex((leg) => parseAmount(leg.amount) === null);
    const target = blank === -1 ? splits.length - 1 : blank;
    const current = blank === -1 ? (parseAmount(splits[target].amount) ?? 0) : 0;
    updateLeg(target, { amount: round2(current + remaining).toFixed(2) });
  };

  // Shown live under the legs, and it disables Save.
  const splitProblem = isSplit ? firstSplitProblem(splits, isBalanced) : null;

  // "Car will go to −$1,500 — that's fine, it's carried". A goal's `left` already
  // counts this transaction when it is on that goal, so only the change counts.
  const goalHint = useMemo(() => {
    if (!category?.account) return null;
    const already = tx?.values.categoryId === category.id ? signedTotal(tx.values.inflow, tx.values.outflow) : 0;
    return goalOverspendHint(category.account, total - already);
  }, [category, total, tx]);

  // --- save ------------------------------------------------------------

  const offersRecurring = isCreate && allowRecurring;

  const validate = () => {
    const found = {};
    if (isCreate && accountOptions && !account) found.account = gettext('Choose the account this transaction is in');
    if (!date) found.date = gettext('Date is required');
    if (!isLocked('amount')) {
      const hasInflow = (parseAmount(inflow) ?? 0) > 0;
      const hasOutflow = (parseAmount(outflow) ?? 0) > 0;
      if (!hasInflow && !hasOutflow) found.amount = gettext('Either money in or money out is required');
      if (hasInflow && hasOutflow) found.amount = gettext('A transaction is money in or money out, not both');
    }
    const scheduleProblem = offersRecurring && isRecurring ? recurrenceProblem(recurrence, date) : null;
    if (scheduleProblem) found.recurrence = scheduleProblem;
    setErrors(found);
    return Object.keys(found).length === 0;
  };

  const run = async (work) => {
    setBusy(true);
    try {
      await work();
      onClose();
    } catch (error) {
      setErrors({ submit: error.message || gettext('Failed to save transaction') });
    } finally {
      setBusy(false);
    }
  };

  const handleSave = async () => {
    if (!validate()) return;
    const form = {
      account,
      date,
      category,
      payee,
      description,
      inflow,
      outflow,
      removedSplit,
      // Amounts go over the wire as strings, so no float reaches the server's Decimal.
      splits: isSplit
        ? splits.map((leg) => ({ category: leg.category.id, amount: parseAmount(leg.amount).toFixed(2) }))
        : null,
      recurrence: offersRecurring && isRecurring ? recurrencePayload(recurrence, date) : null,
    };
    const payload = source.payload(form, transaction, tx);
    if (payload === null) {
      onClose();
      return;
    }
    await run(() => onSave(payload, isCreate ? 'create' : 'edit'));
  };

  // A transaction is money in or money out: typing one clears the other.
  const setInflowOnly = (value) => {
    setInflow(value);
    if ((parseAmount(value) ?? 0) > 0) setOutflow('');
  };
  const setOutflowOnly = (value) => {
    setOutflow(value);
    if ((parseAmount(value) ?? 0) > 0) setInflow('');
  };

  // --- render ----------------------------------------------------------

  if (!open) return null;

  const showHistory = Boolean(tx?.historyId);
  const onHistoryTab = activeTab === 1 && showHistory;
  const canSplit = tx ? tx.canSplit : true;
  const canDelete = Boolean(onDelete && tx?.canDelete);
  const canVoid = Boolean(onSetStatus && (tx?.canVoid || tx?.canUnvoid));
  const accountPreset = isCreate && Boolean(accountOptions?.some((o) => o.id === defaultAccountId));

  const tab = (index, label, testId) => (
    <button
      type="button"
      role="tab"
      className={`tab ${activeTab === index ? 'tab-active' : ''}`}
      aria-selected={activeTab === index}
      onClick={() => setActiveTab(index)}
      data-testid={testId}
    >
      {label}
    </button>
  );

  return (
    <Modal
      open={open}
      onClose={onClose}
      // The leg table needs the width; a single category does not.
      size={isSplit ? 'lg' : 'md'}
      testId="edit-transaction-modal"
      // With the account preset, the date is the first thing left to fill in.
      initialFocus={accountPreset ? '[data-testid="transaction-date"]' : undefined}
      title={isCreate ? gettext('Add transaction') : gettext('Edit transaction')}
      actions={
        <div className="flex w-full items-center gap-2">
          {!onHistoryTab && (
            <div className="mr-auto flex items-center gap-1">
              {canDelete &&
                (confirmingDelete ? (
                  <>
                    <span className="text-sm text-base-content/70">{gettext('Delete?')}</span>
                    <button
                      type="button"
                      className="btn btn-error btn-sm"
                      onClick={() => run(onDelete)}
                      disabled={busy}
                      data-testid="modal-delete-confirm"
                    >
                      {gettext('Yes, delete')}
                    </button>
                    <button type="button" className="btn btn-ghost btn-sm" onClick={() => setConfirmingDelete(false)}>
                      {gettext('Keep')}
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm text-error"
                    onClick={() => setConfirmingDelete(true)}
                    disabled={busy}
                    data-testid="modal-delete-btn"
                  >
                    <Icon name="trash" className="h-4 w-4" />
                    {gettext('Delete')}
                  </button>
                ))}
              {!confirmingDelete && canVoid && (
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => run(() => onSetStatus(tx.canUnvoid ? 'posted' : 'void'))}
                  disabled={busy}
                  data-testid="modal-void-btn"
                  title={
                    tx.canUnvoid
                      ? gettext('Bring this transaction back into your balances')
                      : gettext('Keep this transaction on record but leave it out of every balance')
                  }
                >
                  {tx.canUnvoid ? gettext('Restore') : gettext('Void')}
                </button>
              )}
            </div>
          )}
          <button type="button" className="btn btn-sm" onClick={onClose} disabled={busy} data-testid="modal-cancel-btn">
            {onHistoryTab ? gettext('Close') : gettext('Cancel')}
          </button>
          {!onHistoryTab && (
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={handleSave}
              // An unbalanced split cannot be saved. The server enforces this too,
              // but the reason under the legs explains itself sooner than a 400 does.
              disabled={busy || frozen || Boolean(splitProblem)}
              title={splitProblem || ''}
              data-testid="modal-save-btn"
            >
              {busy && <Spinner size="xs" />}
              {isCreate ? gettext('Add') : gettext('Save')}
            </button>
          )}
        </div>
      }
    >
      {showHistory && (
        <div role="tablist" className="tabs tabs-border mb-4">
          {tab(0, gettext('Details'), 'tab-details')}
          {tab(1, gettext('History'), 'tab-history')}
        </div>
      )}

      {onHistoryTab ? (
        <TransactionHistory book={book} journalEntryId={tx.historyId} />
      ) : (
        <div className="flex flex-col gap-4">
          {frozen && (
            <div className="alert alert-info text-sm" role="status" data-testid="period-locked-notice">
              <Icon name="lock" className="h-4 w-4 shrink-0" />
              <span>{locked.all}</span>
            </div>
          )}

          {tx?.warning && (
            <div className="alert alert-warning text-sm" data-testid="unusual-shape-warning">
              {tx.warning}
            </div>
          )}

          {accountOptions && (
            <Combobox
              label={gettext('Account')}
              value={account}
              onChange={setAccount}
              options={accountOptions}
              disabled={isLocked('account')}
              placeholder={gettext('Choose an account')}
              error={errors.account}
              helperText={lockNote('account')}
              testId="transaction-account"
            />
          )}

          <DateField
            // With "Make recurring" ticked this date is the schedule's first occurrence.
            label={offersRecurring && isRecurring ? gettext('Start date') : gettext('Date')}
            value={date}
            onChange={setDate}
            testId="transaction-date"
            disabled={isLocked('date')}
          />
          {(errors.date || lockNote('date')) && (
            <p className={`-mt-3 text-xs ${errors.date ? 'text-error' : 'text-base-content/70'}`}>
              {errors.date || lockNote('date')}
            </p>
          )}

          {offersRecurring && (
            <div className="-mt-1 flex flex-col gap-2">
              <label className="flex cursor-pointer items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="checkbox checkbox-sm"
                  checked={isRecurring}
                  onChange={(e) => setIsRecurring(e.target.checked)}
                  data-testid="make-recurring"
                />
                {gettext('Make recurring')}
              </label>
              {isRecurring && (
                <RecurrenceFields
                  recurrence={recurrence}
                  date={date}
                  onChange={setRecurrence}
                  error={errors.recurrence}
                />
              )}
            </div>
          )}

          <Combobox
            freeText
            label={gettext('Payee')}
            value={payee}
            onChange={setPayee}
            options={payeeOptions}
            disabled={frozen}
            testId="transaction-payee"
          />

          {isSplit ? (
            <SplitEditor
              legs={splits}
              categoryOptions={pickerOptions}
              total={total}
              legSum={legSum}
              remaining={remaining}
              isBalanced={isBalanced}
              disabled={isLocked('category')}
              onChangeLeg={updateLeg}
              onAddLeg={addLeg}
              onRemoveLeg={removeLeg}
              onAssignRemainder={assignRemainder}
              onRemoveSplit={removeSplit}
            />
          ) : (
            <div className="flex flex-col gap-1">
              <Combobox
                label={gettext('Category')}
                value={category}
                onChange={(option) => {
                  setCategory(option);
                  setCategorySuggested(false);
                }}
                options={pickerOptions}
                getGroup={(option) => option.groupLabel}
                disabled={isLocked('category')}
                onCreate={accountCreator.available ? accountCreator.open : null}
                placeholder={gettext('Choose a category')}
                helperText={
                  (categorySuggested && gettext('Suggested from how this payee was last categorized')) ||
                  lockNote('category') ||
                  goalHint ||
                  ''
                }
                testId="transaction-category"
              />
              {canSplit && !isLocked('category') && (
                <div>
                  <button
                    type="button"
                    className="link link-primary text-xs"
                    onClick={startSplit}
                    data-testid="start-split-btn"
                  >
                    {gettext('Split across categories')}
                  </button>
                </div>
              )}
            </div>
          )}
          {splitProblem && (
            <p className="-mt-2 text-xs text-error" data-testid="split-error">
              {splitProblem}
            </p>
          )}

          <div className="grid grid-cols-2 gap-4">
            <label className="form-control w-full">
              <span className="label-text mb-1 block text-sm text-base-content/70">{gettext('Money out')}</span>
              <AmountInput
                className={`input input-bordered w-full text-right font-mono ${errors.amount ? 'input-error' : ''}`}
                value={outflow}
                onValueChange={setOutflowOnly}
                disabled={isLocked('amount')}
                data-testid="transaction-outflow"
              />
            </label>
            <label className="form-control w-full">
              <span className="label-text mb-1 block text-sm text-base-content/70">{gettext('Money in')}</span>
              <AmountInput
                className={`input input-bordered w-full text-right font-mono ${errors.amount ? 'input-error' : ''}`}
                value={inflow}
                onValueChange={setInflowOnly}
                disabled={isLocked('amount')}
                data-testid="transaction-inflow"
              />
            </label>
          </div>
          {(errors.amount || lockNote('amount')) && (
            <p className={`-mt-3 text-xs ${errors.amount ? 'text-error' : 'text-base-content/70'}`}>
              {errors.amount || lockNote('amount')}
            </p>
          )}

          <label className="form-control w-full">
            <span className="label-text mb-1 block text-sm text-base-content/70">{gettext('Description')}</span>
            <input
              type="text"
              className="input input-bordered w-full"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              disabled={frozen}
              data-testid="transaction-description"
            />
          </label>

          {tx?.recurringId && book?.base && (
            <p className="text-xs text-base-content/70" data-testid="recurring-note">
              {gettext('Part of a recurring transaction. Editing this one leaves the others as they are.')}{' '}
              <a className="link link-primary" href={`${book.base}bankfeed/recurring/`}>
                {gettext('Manage recurring transactions')}
              </a>
            </p>
          )}

          {errors.submit && (
            <p className="text-sm text-error" data-testid="modal-error">
              {errors.submit}
            </p>
          )}
        </div>
      )}
      {/* Its own <dialog>: the top layer stacks it above this one */}
      {accountCreator.modal}
    </Modal>
  );
};

export default TransactionModal;
