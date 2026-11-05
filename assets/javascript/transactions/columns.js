/* globals gettext */

import { formatCurrency } from '../utilities/currency';

/**
 * Status codes, with the label and badge colour the table shows. Status isn't a
 * column (nearly every row is Posted): a draft or void row carries its badge
 * beside the description.
 */
export const STATUS_STYLES = {
  draft: { label: gettext('Draft'), className: 'badge-soft badge-warning' },
  posted: { label: gettext('Posted'), className: 'badge-soft badge-success' },
  void: { label: gettext('Void'), className: 'badge-soft badge-error' },
};

export const FALLBACK_BADGE = 'badge-ghost';

/**
 * The transactions table's columns, in display order.
 *
 * `key` is the wire name the API sorts and filters by (`?sort=amount`,
 * `?f_amount=5.00`), so this list and `COLUMNS` in `apps/journal/filters.py`
 * name the same columns. `formatValue` turns a raw facet value into what the
 * filter menu shows; the server already supplies a display label for columns
 * whose stored value is a code.
 *
 * The sort labels are per column because "ascending" is a poor description of
 * what it does to a date or an amount.
 */
export const TRANSACTION_COLUMNS = [
  {
    // The API answers this column with a year -> month -> day tree whose
    // labels arrive display-ready, so there is no `formatValue` to apply.
    key: 'date',
    label: gettext('Date'),
    ascLabel: gettext('Oldest first'),
    descLabel: gettext('Newest first'),
  },
  {
    key: 'payee',
    label: gettext('Payee'),
  },
  {
    key: 'description',
    label: gettext('Description'),
  },
  {
    // Likewise a tree: account type -> account group -> account.
    key: 'debit_account',
    label: gettext('Debit Account'),
  },
  {
    key: 'credit_account',
    label: gettext('Credit Account'),
  },
  {
    key: 'amount',
    label: gettext('Amount'),
    align: 'right',
    formatValue: (value) => formatCurrency(value),
    ascLabel: gettext('Smallest first'),
    descLabel: gettext('Largest first'),
  },
].map((column) => ({
  ascLabel: gettext('A → Z'),
  descLabel: gettext('Z → A'),
  formatValue: (value, label) => label || value,
  align: 'left',
  searchable: true,
  ...column,
}));
