import React, { useEffect, useMemo, useState } from 'react';

import Combobox from '../common/Combobox';
import DateField from '../common/DateField';
import Icon from '../common/Icon';
import Modal from '../common/Modal';
import Spinner from '../common/Spinner';
import { parseAmount, round2 } from '../common/amount';
import { buildCategoryOptions } from '../common/categoryOptions';
import SplitEditor, { MIN_LEGS } from '../bank_feed/react/SplitEditor';
import TransactionHistory from '../bank_feed/react/TransactionHistory';

/* globals gettext, interpolate */

/**
 * Editing a transaction from the Transactions page.
 *
 * The page presents a double-entry ledger as something closer to a bank
 * register, and this modal is where that has to hold up under editing. Nothing
 * here says debit or credit: a transaction is an **account** (where the money
 * sat) and a **category** — or several of them, when it is split.
 *
 * `transactions` is an array from the outset, even though only single-row
 * editing is wired up today. Every field reads its starting value through
 * `shared()`, which returns `MIXED` when the selection disagrees, and a field
 * still holding `MIXED` at save time is left out of the payload. In single-row
 * mode every field is trivially shared, so one code path serves both and batch
 * editing becomes a caller change rather than a second modal that could drift
 * out of step with this one.
 */

/** A field whose value differs across the selection: shown blank, sent as nothing. */
export const MIXED = Symbol('mixed');

/** Stable keys for leg rows, so React never re-mounts a field mid-edit. */
let legKeySeq = 0;
const nextLegKey = () => {
  legKeySeq += 1;
  return `tx-leg-${legKeySeq}`;
};

const formatLegAmount = (value) => {
  const parsed = parseAmount(value);
  return parsed === null ? '' : parsed.toFixed(2);
};

/** The value every transaction agrees on, or MIXED. */
const shared = (transactions, read) => {
  if (transactions.length === 0) return '';
  const first = read(transactions[0]);
  const same = transactions.every((tx) => JSON.stringify(read(tx)) === JSON.stringify(first));
  return same ? first : MIXED;
};

/** MIXED and null both render as an empty control. */
const orBlank = (value, fallback = '') => (value === MIXED || value == null ? fallback : value);

const TransactionEditModal = ({
  open,
  transactions = [],
  allAccounts = [],
  allPayees = [],
  book,
  onSave,
  onDelete,
  onSetStatus,
  onClose,
}) => {
  const isBatch = transactions.length > 1;
  const one = transactions.length === 1 ? transactions[0] : null;

  const [date, setDate] = useState('');
  const [payee, setPayee] = useState('');
  const [description, setDescription] = useState('');
  const [account, setAccount] = useState(null);
  const [category, setCategory] = useState(null);
  const [inflow, setInflow] = useState('');
  const [outflow, setOutflow] = useState('');
  const [splits, setSplits] = useState(null);
  const [removedSplit, setRemovedSplit] = useState(false);
  const [activeTab, setActiveTab] = useState(0);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);

  // What the whole selection allows: the strictest answer wins, because a save
  // applies to every row and one locked row would refuse the batch.
  const can = useMemo(() => {
    const keys = [
      'can_edit_date',
      'can_edit_amount',
      'can_edit_account',
      'can_edit_category',
      'can_split',
      'can_delete',
      'can_void',
      'can_unvoid',
    ];
    return Object.fromEntries(
      keys.map((key) => [key, transactions.length > 0 && transactions.every((tx) => tx.capabilities?.[key])])
    );
  }, [transactions]);

  // Categories: anything. The account side is only ever somewhere money sits, so
  // an expense account would be a nonsense choice there.
  const categoryOptions = useMemo(() => buildCategoryOptions(allAccounts), [allAccounts]);
  const accountOptions = useMemo(
    () => buildCategoryOptions(allAccounts, { filterTypes: ['asset', 'liability'] }),
    [allAccounts]
  );
  const payeeOptions = useMemo(() => allPayees.map((p) => p.name), [allPayees]);

  useEffect(() => {
    if (!open || transactions.length === 0) return;

    setActiveTab(0);
    setErrors({});
    setConfirmingDelete(false);
    setRemovedSplit(false);

    setDate(orBlank(shared(transactions, (tx) => tx.date)));
    setPayee(orBlank(shared(transactions, (tx) => tx.payee_name)));
    setDescription(orBlank(shared(transactions, (tx) => tx.description)));

    const sharedAccount = shared(transactions, (tx) => tx.account?.id ?? null);
    setAccount(sharedAccount === MIXED ? null : accountOptions.find((o) => o.id === sharedAccount) || null);

    const sharedCategory = shared(transactions, (tx) => tx.category?.id ?? null);
    setCategory(sharedCategory === MIXED ? null : categoryOptions.find((o) => o.id === sharedCategory) || null);

    // Amounts and legs are per-transaction, so they only appear for a single row.
    if (one) {
      setInflow(parseAmount(one.inflow) ? one.inflow : '');
      setOutflow(parseAmount(one.outflow) ? one.outflow : '');
      setSplits(
        one.is_split
          ? one.splits.map((leg) => ({
              key: nextLegKey(),
              category: categoryOptions.find((o) => o.id === leg.category_id) || null,
              amount: formatLegAmount(leg.amount),
            }))
          : null
      );
    } else {
      setInflow('');
      setOutflow('');
      setSplits(null);
    }
  }, [open, transactions, categoryOptions, accountOptions, one]);

  // --- splits ----------------------------------------------------------

  const isSplit = splits !== null;

  // Signed total, positive for an outflow — the same convention the server and
  // the Bank Feed use, so a leg means the same thing on both sides.
  const total = useMemo(() => round2((parseAmount(outflow) ?? 0) - (parseAmount(inflow) ?? 0)), [inflow, outflow]);
  const legSum = useMemo(
    () => round2((splits ?? []).reduce((acc, leg) => acc + (parseAmount(leg.amount) ?? 0), 0)),
    [splits]
  );
  const remaining = round2(total - legSum);
  // Compared with a cent tolerance, never `===`: 0.1 + 0.2 !== 0.3 in floating point.
  const isBalanced = Math.abs(remaining) < 0.005;

  const updateLeg = (index, patch) =>
    setSplits((current) => current.map((leg, i) => (i === index ? { ...leg, ...patch } : leg)));
  const addLeg = () => setSplits((current) => [...current, { key: nextLegKey(), category: null, amount: '' }]);
  const removeLeg = (index) => setSplits((current) => current.filter((_, i) => i !== index));

  const startSplit = () => {
    // The first leg carries the whole total, so Remaining opens at $0.00 and goes
    // negative as the second is typed — which reads as "you have over-assigned".
    // Two blank legs would greet the user with the full amount outstanding before
    // they had done anything wrong.
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
    setSplits(null);
    setRemovedSplit(true);
  };

  const assignRemainder = () => {
    const blank = splits.findIndex((leg) => parseAmount(leg.amount) === null);
    const target = blank === -1 ? splits.length - 1 : blank;
    const current = blank === -1 ? (parseAmount(splits[target].amount) ?? 0) : 0;
    updateLeg(target, { amount: round2(current + remaining).toFixed(2) });
  };

  /** The first thing wrong with the legs, or null. Same rules as the Bank Feed. */
  const splitProblem = () => {
    if (!isSplit) return null;
    if (splits.length < MIN_LEGS) return gettext('A split needs at least two categories.');
    if (splits.some((leg) => !leg.category)) return gettext('Every split needs a category.');
    if (splits.some((leg) => parseAmount(leg.amount) === null)) return gettext('Every split needs an amount.');
    if (splits.some((leg) => parseAmount(leg.amount) === 0)) return gettext('A split amount cannot be zero.');
    if (!isBalanced) return gettext('The splits must add up to the transaction total.');
    return null;
  };

  // --- save ------------------------------------------------------------

  const validate = () => {
    const found = {};

    if (!isBatch && !date) found.date = gettext('Date is required');

    if (!isBatch && can.can_edit_amount) {
      const hasInflow = (parseAmount(inflow) ?? 0) > 0;
      const hasOutflow = (parseAmount(outflow) ?? 0) > 0;
      if (!hasInflow && !hasOutflow) found.amount = gettext('Either money in or money out is required');
      if (hasInflow && hasOutflow) found.amount = gettext('A transaction is money in or money out, not both');
    }

    const problem = splitProblem();
    if (problem) found.splits = problem;

    setErrors(found);
    return Object.keys(found).length === 0;
  };

  /**
   * Only what actually changed.
   *
   * A field left as its starting value is omitted, so the server leaves it alone
   * — which is what makes a batch edit safe: it never quietly rewrites forty
   * descriptions because the modal happened to show one of them.
   */
  const buildUpdates = () => {
    const updates = {};
    const changed = (current, read) => {
      const before = shared(transactions, read);
      return before !== MIXED && current !== before;
    };

    if (date && changed(date, (tx) => tx.date)) updates.date = date;
    if (changed(payee, (tx) => tx.payee_name ?? '')) updates.payee = payee;
    if (changed(description, (tx) => tx.description ?? '')) updates.description = description;
    if (account && changed(account.id, (tx) => tx.account?.id ?? null)) updates.account_id = account.id;

    if (isSplit) {
      updates.splits = splits.map((leg) => ({
        category: leg.category.id,
        amount: parseAmount(leg.amount).toFixed(2),
      }));
    } else {
      if (removedSplit) updates.remove_split = true;
      if (category && (removedSplit || changed(category.id, (tx) => tx.category?.id ?? null))) {
        updates.category_id = category.id;
      }
    }

    if (!isBatch && can.can_edit_amount) {
      if (changed(inflow || '0.00', (tx) => tx.inflow)) updates.inflow = inflow || '0';
      if (changed(outflow || '0.00', (tx) => tx.outflow)) updates.outflow = outflow || '0';
    }

    return updates;
  };

  const run = async (work) => {
    setBusy(true);
    try {
      await work();
      onClose();
    } catch (error) {
      setErrors({ submit: error.message });
    } finally {
      setBusy(false);
    }
  };

  const handleSave = async () => {
    if (!validate()) return;
    const updates = buildUpdates();
    if (Object.keys(updates).length === 0) {
      onClose();
      return;
    }
    const ids = transactions.map((tx) => tx.id);
    await run(() => onSave(ids, updates));
  };

  const handleDelete = () => run(() => onDelete(transactions.map((tx) => tx.id)));

  const handleStatus = (statusValue) => {
    const ids = transactions.map((tx) => tx.id);
    return run(() => onSetStatus(ids, statusValue));
  };

  // --- render ----------------------------------------------------------

  if (!open || transactions.length === 0) return null;

  const showHistory = Boolean(one);
  const onHistoryTab = activeTab === 1 && showHistory;
  const title = isBatch
    ? interpolate(gettext('Edit %s transactions'), [transactions.length])
    : gettext('Edit transaction');

  const setInflowOnly = (value) => {
    setInflow(value);
    if (value) setOutflow('');
  };
  const setOutflowOnly = (value) => {
    setOutflow(value);
    if (value) setInflow('');
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="md"
      testId="transaction-edit-modal"
      title={title}
      actions={
        <div className="flex w-full items-center gap-2">
          {!onHistoryTab && (
            <div className="mr-auto flex items-center gap-1">
              {can.can_delete &&
                (confirmingDelete ? (
                  <>
                    <span className="text-sm text-base-content/70">{gettext('Delete?')}</span>
                    <button
                      type="button"
                      className="btn btn-error btn-sm"
                      onClick={handleDelete}
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
              {!confirmingDelete && (can.can_void || can.can_unvoid) && (
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => handleStatus(can.can_unvoid ? 'posted' : 'void')}
                  disabled={busy}
                  data-testid="modal-void-btn"
                  title={
                    can.can_unvoid
                      ? gettext('Bring this transaction back into your balances')
                      : gettext('Keep this transaction on record but leave it out of every balance')
                  }
                >
                  {can.can_unvoid ? gettext('Restore') : gettext('Void')}
                </button>
              )}
            </div>
          )}
          <button
            type="button"
            className="btn btn-sm"
            onClick={onClose}
            disabled={busy}
            data-testid="modal-cancel-btn"
          >
            {onHistoryTab ? gettext('Close') : gettext('Cancel')}
          </button>
          {!onHistoryTab && (
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={handleSave}
              disabled={busy}
              data-testid="modal-save-btn"
            >
              {busy ? <Spinner size="xs" /> : null}
              {gettext('Save')}
            </button>
          )}
        </div>
      }
    >
      {showHistory && (
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
        <TransactionHistory book={book} journalEntryId={one.id} />
      ) : (
        <div className="flex flex-col gap-4">
          {isBatch && (
            <p className="text-sm text-base-content/70" data-testid="batch-hint">
              {gettext('Only the fields you change will be updated. Fields that differ are shown blank.')}
            </p>
          )}

          {one && !one.has_normal_account_side && (
            <div className="alert alert-warning text-sm" data-testid="unusual-shape-warning">
              {gettext(
                "This transaction doesn't move money through one of your accounts, so the Account and Category below are a best guess."
              )}
            </div>
          )}

          {!isBatch && (
            <>
              <DateField
                label={gettext('Date')}
                value={date}
                onChange={setDate}
                testId="transaction-date"
                disabled={!can.can_edit_date}
              />
              {(errors.date || !can.can_edit_date) && (
                <p className={`-mt-3 text-xs ${errors.date ? 'text-error' : 'text-base-content/70'}`}>
                  {errors.date || gettext('Your bank sets the date on this transaction')}
                </p>
              )}
            </>
          )}

          <Combobox
            label={gettext('Payee')}
            value={payee}
            onChange={setPayee}
            options={payeeOptions}
            freeText
            placeholder={isBatch ? gettext('Leave blank to keep each one') : ''}
            testId="transaction-payee"
          />

          <Combobox
            label={gettext('Account')}
            value={account}
            onChange={setAccount}
            options={accountOptions}
            getGroup={(option) => option.groupLabel}
            disabled={!can.can_edit_account}
            placeholder={isBatch ? gettext('Leave blank to keep each one') : gettext('Choose an account')}
            helperText={can.can_edit_account ? '' : gettext('Unreconcile this transaction to move it')}
            testId="transaction-account"
          />

          {isSplit ? (
            <SplitEditor
              legs={splits}
              categoryOptions={categoryOptions}
              total={total}
              legSum={legSum}
              remaining={remaining}
              isBalanced={isBalanced}
              disabled={!can.can_edit_category}
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
                onChange={setCategory}
                options={categoryOptions}
                getGroup={(option) => option.groupLabel}
                disabled={!can.can_edit_category}
                placeholder={isBatch ? gettext('Leave blank to keep each one') : gettext('Choose a category')}
                testId="transaction-category"
              />
              {!isBatch && can.can_split && (
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
          {errors.splits && (
            <p className="-mt-2 text-xs text-error" data-testid="split-error">
              {errors.splits}
            </p>
          )}

          <label className="form-control w-full">
            <span className="label-text mb-1 block text-sm text-base-content/70">{gettext('Memo')}</span>
            <input
              type="text"
              className="input input-bordered w-full"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={isBatch ? gettext('Leave blank to keep each one') : ''}
              data-testid="transaction-description"
            />
          </label>

          {!isBatch && (
            <>
              <div className="grid grid-cols-2 gap-4">
                <label className="form-control w-full">
                  <span className="label-text mb-1 block text-sm text-base-content/70">{gettext('Money out')}</span>
                  <input
                    type="text"
                    inputMode="decimal"
                    className="input input-bordered w-full text-right font-mono"
                    value={outflow}
                    onChange={(e) => setOutflowOnly(e.target.value)}
                    disabled={!can.can_edit_amount}
                    data-testid="transaction-outflow"
                  />
                </label>
                <label className="form-control w-full">
                  <span className="label-text mb-1 block text-sm text-base-content/70">{gettext('Money in')}</span>
                  <input
                    type="text"
                    inputMode="decimal"
                    className="input input-bordered w-full text-right font-mono"
                    value={inflow}
                    onChange={(e) => setInflowOnly(e.target.value)}
                    disabled={!can.can_edit_amount}
                    data-testid="transaction-inflow"
                  />
                </label>
              </div>
              {(errors.amount || !can.can_edit_amount) && (
                <p className={`-mt-3 text-xs ${errors.amount ? 'text-error' : 'text-base-content/70'}`}>
                  {errors.amount || gettext('Unreconcile this transaction, or edit it in your bank feed, to change the amount')}
                </p>
              )}
            </>
          )}

          {errors.submit && (
            <p className="text-sm text-error" data-testid="modal-error">
              {errors.submit}
            </p>
          )}
        </div>
      )}
    </Modal>
  );
};

export default TransactionEditModal;
