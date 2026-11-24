/* globals gettext */

import { amountForPayload, parseAmount } from '../common/amount';

/**
 * `TransactionModal`'s adapter for a journal entry (`TransactionDetailSerializer`),
 * saved through the transactions API's partial edit: only what changed is sent,
 * so the server leaves every other field alone.
 */
export const ledgerTransaction = {
  read(row) {
    const can = row.capabilities || {};
    return {
      values: {
        accountId: row.account?.id ?? null,
        date: row.date || '',
        payee: row.payee_name ?? '',
        description: row.description ?? '',
        categoryId: row.category?.id ?? null,
        inflow: parseAmount(row.inflow) ? row.inflow : '',
        outflow: parseAmount(row.outflow) ? row.outflow : '',
        legs: row.is_split ? row.splits.map((leg) => ({ categoryId: leg.category_id, amount: leg.amount })) : null,
      },
      locked: {
        // A transaction in the book's closed period is read-only; the server says
        // why (`period_lock.lock_reason`) and its capabilities are all false.
        all: row.locked_reason || null,
        date: can.can_edit_date ? null : gettext('Your bank sets the date on this transaction'),
        amount: can.can_edit_amount
          ? null
          : gettext('Unreconcile this transaction, or edit it in your bank feed, to change the amount'),
        account: can.can_edit_account ? null : gettext('Unreconcile this transaction to move it'),
        category: can.can_edit_category ? null : gettext('Category cannot be edited for this transaction'),
      },
      canSplit: Boolean(can.can_split),
      canDelete: Boolean(can.can_delete),
      canVoid: Boolean(can.can_void),
      canUnvoid: Boolean(can.can_unvoid),
      historyId: row.id,
      warning: row.has_normal_account_side
        ? null
        : gettext(
            "This transaction doesn't move money through one of your accounts, so the Account and Category below are a best guess.",
          ),
    };
  },

  /** The changed fields, or null when nothing changed. */
  payload(form, row, tx) {
    const was = tx.values;
    const updates = {};
    if (form.date && form.date !== was.date) updates.date = form.date;
    if (form.payee !== was.payee) updates.payee = form.payee;
    if (form.description !== was.description) updates.description = form.description;
    if (form.account && form.account.id !== was.accountId) updates.account_id = form.account.id;

    if (form.splits) {
      updates.splits = form.splits;
    } else {
      if (form.removedSplit) updates.remove_split = true;
      if (form.category && (form.removedSplit || form.category.id !== was.categoryId)) {
        updates.category_id = form.category.id;
      }
    }

    if (!tx.locked.amount) {
      const inflow = amountForPayload(form.inflow, '0.00');
      const outflow = amountForPayload(form.outflow, '0.00');
      if (inflow !== row.inflow) updates.inflow = inflow;
      if (outflow !== row.outflow) updates.outflow = outflow;
    }

    return Object.keys(updates).length ? updates : null;
  },
};
