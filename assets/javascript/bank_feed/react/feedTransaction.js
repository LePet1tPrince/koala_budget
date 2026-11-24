/* globals gettext */

import { amountForPayload, parseAmount } from '../../common/amount';
import { formatDateForInput } from '../utils';

/**
 * `TransactionModal`'s adapter for a bank feed row (`BankFeedRowSerializer`),
 * saved through the feed API: whole-row create and update.
 *
 * Rows from the generated client are camelCase; Categorize Mode and the CSV
 * wizard hand over raw API data, which is snake_case. `field` reads either, so a
 * new field can never silently read `undefined` for one kind of caller.
 */
const field = (row, camel, snake) => row?.[camel] ?? row?.[snake];

const categoryRef = (option) =>
  option ? { id: option.id, name: option.name, account_number: option.accountNumber } : null;

export const feedTransaction = {
  read(row) {
    const legs = field(row, 'splits', 'split_legs') ?? [];
    const journalEntryId = field(row, 'journalEntryId', 'journal_entry_id');
    const fromBank = row.source === 'plaid';
    // A Plaid row nobody has categorized yet is the bank's record, not the user's.
    const readOnly = fromBank && !journalEntryId;
    const reconciled = Boolean(field(row, 'isReconciled', 'is_reconciled'));
    let amountLock = null;
    if (reconciled) amountLock = gettext('Amount locked — transaction is reconciled');
    else if (fromBank) amountLock = gettext('Amount cannot be edited');

    return {
      values: {
        accountId: null,
        date: formatDateForInput(field(row, 'postedDate', 'posted_date')),
        payee: row.payee || '',
        description: row.description || '',
        categoryId: row.category?.id ?? null,
        inflow: (parseAmount(row.inflow) ?? 0) > 0 ? row.inflow : '',
        outflow: (parseAmount(row.outflow) ?? 0) > 0 ? row.outflow : '',
        legs: legs.length
          ? legs.map((leg) => ({ categoryId: leg.categoryId ?? leg.category_id, amount: leg.amount }))
          : null,
      },
      locked: {
        date: fromBank ? gettext('Your bank sets the date on this transaction') : null,
        amount: amountLock,
        category: readOnly ? gettext('Category cannot be edited for this transaction') : null,
      },
      canSplit: !readOnly,
      historyId: journalEntryId,
      recurringId: field(row, 'recurringId', 'recurring_id'),
    };
  },

  /** The feed API's whole-row body; a locked field goes back exactly as it came. */
  payload(form, row, tx) {
    const category = form.splits ? null : categoryRef(form.category);
    if (!row) {
      return {
        source: 'manual',
        account: form.account?.id ?? null,
        date: form.date,
        category,
        splits: form.splits,
        inflow: amountForPayload(form.inflow),
        outflow: amountForPayload(form.outflow),
        payee: form.payee,
        description: form.description,
        recurrence: form.recurrence,
      };
    }
    const { locked } = tx;
    return {
      id: row.id,
      source: row.source,
      journal_entry_id: tx.historyId,
      date: locked.date ? field(row, 'postedDate', 'posted_date') : form.date,
      category: !form.splits && locked.category ? row.category : category,
      splits: form.splits,
      // Collapsing a split is destructive, so the server requires it to be asked
      // for rather than inferred from a payload with no legs.
      remove_split: form.removedSplit && !form.splits,
      inflow: locked.amount ? row.inflow : amountForPayload(form.inflow),
      outflow: locked.amount ? row.outflow : amountForPayload(form.outflow),
      payee: form.payee,
      description: form.description,
    };
  },
};
