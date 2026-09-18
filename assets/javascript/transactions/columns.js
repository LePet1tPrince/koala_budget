/* globals gettext */

import { formatCurrency } from '../utilities/currency';

/**
 * Source and status codes, with the label and badge colour the table shows.
 *
 * The API sends a label for these columns too (the model's own choice text),
 * but it is wordier than the badge column has room for -- "Manual Entry"
 * rather than "Manual". These labels win, so the badge in a row, the value in
 * that column's filter menu and the chip summarising the applied filter all
 * read the same.
 */
export const SOURCE_STYLES = {
  manual: { label: gettext('Manual'), className: 'badge-ghost' },
  import: { label: gettext('Import'), className: 'badge-soft badge-info' },
  bank_match: { label: gettext('Bank'), className: 'badge-soft badge-accent' },
  recurring: { label: gettext('Recurring'), className: 'badge-soft badge-secondary' },
};

export const STATUS_STYLES = {
  draft: { label: gettext('Draft'), className: 'badge-soft badge-warning' },
  posted: { label: gettext('Posted'), className: 'badge-soft badge-success' },
  void: { label: gettext('Void'), className: 'badge-soft badge-error' },
};

export const FALLBACK_BADGE = 'badge-ghost';

/** Prefer our own label for a coded value, falling back to the API's. */
const codeFormatter = (styles) => (value, label) => styles[value]?.label || label || value;

/**
 * The transactions table's columns, in display order.
 *
 * `key` is the wire name the API sorts and filters by (`?sort=amount`,
 * `?f_amount=5.00`), so this list and `COLUMNS` in `apps/journal/filters.py`
 * name the same columns. `formatValue` turns a raw facet value into what the
 * filter menu shows; the server already supplies a display label for columns
 * whose stored value is a code, which is why `source` and `status` take it
 * rather than formatting anything themselves.
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
  {
    key: 'source',
    label: gettext('Source'),
    formatValue: codeFormatter(SOURCE_STYLES),
    // The API matches `q` against the stored code, not the label we show, so
    // searching a handful of codes for "Bank" would come back empty. These
    // columns have four values; the list is the search.
    searchable: false,
  },
  {
    key: 'status',
    label: gettext('Status'),
    formatValue: codeFormatter(STATUS_STYLES),
    searchable: false,
  },
].map((column) => ({
  ascLabel: gettext('A → Z'),
  descLabel: gettext('Z → A'),
  formatValue: (value, label) => label || value,
  align: 'left',
  searchable: true,
  ...column,
}));
