/**
 * What the Inbox table is looking at, and how that becomes a request and a URL.
 *
 * The table is a window onto one server-side queryset (`apps/bank_feed/services/
 * feed_query.py`): the client holds only the page on screen, so every filter,
 * the sort and the page are request parameters. They are also the URL's query
 * string, so a reload or the Back button lands on the same page of the same view.
 */

export const PAGE_SIZE_OPTIONS = [10, 25, 50, 100, 200];
export const DEFAULT_PAGE_SIZE = 25;
export const NO_QUICK_FILTERS = { toReview: false, reconciled: false, uncategorized: false, transfers: false };
export const DEFAULT_SORT = { key: 'postedDate', dir: 'desc' };

/** The table's column keys -> the server's `sort` values. */
const SORT_KEYS = {
  postedDate: 'date',
  account: 'account',
  payee: 'payee',
  category: 'category',
  inflow: 'inflow',
  outflow: 'outflow',
  description: 'description',
};
const COLUMN_FOR_SORT = Object.fromEntries(Object.entries(SORT_KEYS).map(([column, key]) => [key, column]));

export const DEFAULT_QUERY = {
  accounts: [], // empty = every account on a feed
  view: 'active',
  quickFilters: NO_QUICK_FILTERS,
  startDate: '',
  endDate: '',
  sort: DEFAULT_SORT,
  page: 0, // zero-based on the client; the server's `page` is one-based
  pageSize: DEFAULT_PAGE_SIZE,
};

const isDefaultSort = (sort) => !sort || (sort.key === DEFAULT_SORT.key && sort.dir === DEFAULT_SORT.dir);

/** A YYYY-MM-DD string as the generated client sends dates (UTC midnight -> the same day). */
const asDate = (value) => (value ? new Date(`${value}T00:00:00Z`) : undefined);

/**
 * The generated client's request params for `query`, without the book's slugs
 * or the page. Shared by the list, `selection/` and `locate/`, which must all
 * describe the same rows in the same order.
 */
export function filterParams(query) {
  const params = { view: query.view, pageSize: query.pageSize };
  if (query.accounts.length) params.account = query.accounts.join(',');
  if (query.view !== 'voided') {
    if (query.quickFilters.toReview) params.toReview = true;
    if (query.quickFilters.reconciled) params.reconciled = true;
    if (query.quickFilters.uncategorized) params.uncategorized = true;
    if (query.quickFilters.transfers) params.transfers = true;
  }
  if (query.startDate) params.startDate = asDate(query.startDate);
  if (query.endDate) params.endDate = asDate(query.endDate);
  if (!isDefaultSort(query.sort)) {
    params.sort = SORT_KEYS[query.sort.key];
    params.dir = query.sort.dir;
  }
  return params;
}

/** A key that changes exactly when the set of rows (not the page) changes. */
export function rowSetKey(query) {
  const { page, pageSize, sort, ...rest } = query;
  return JSON.stringify(rest);
}

const intList = (raw) =>
  (raw || '')
    .split(',')
    .map((part) => Number(part))
    .filter((n) => Number.isInteger(n) && n > 0);

/** Read the table's state from the page URL; anything missing or malformed is the default. */
export function queryFromUrl(search = window.location.search) {
  const params = new URLSearchParams(search);
  const query = { ...DEFAULT_QUERY, quickFilters: { ...NO_QUICK_FILTERS } };
  query.accounts = intList(params.get('account'));
  if (params.get('view') === 'voided') query.view = 'voided';
  Object.keys(NO_QUICK_FILTERS).forEach((key) => {
    query.quickFilters[key] = params.get(key) === '1';
  });
  if (query.quickFilters.toReview && query.quickFilters.reconciled) query.quickFilters.reconciled = false;
  const dateOk = (v) => /^\d{4}-\d{2}-\d{2}$/.test(v || '');
  if (dateOk(params.get('start'))) query.startDate = params.get('start');
  if (dateOk(params.get('end'))) query.endDate = params.get('end');
  const sortColumn = COLUMN_FOR_SORT[params.get('sort')];
  if (sortColumn) query.sort = { key: sortColumn, dir: params.get('dir') === 'desc' ? 'desc' : 'asc' };
  const size = Number(params.get('page_size'));
  if (PAGE_SIZE_OPTIONS.includes(size)) query.pageSize = size;
  const page = Number(params.get('page'));
  if (Number.isInteger(page) && page > 1) query.page = page - 1;
  return query;
}

/** Mirror `query` into the address bar without adding a history entry per click. */
export function writeQueryToUrl(query) {
  const params = new URLSearchParams();
  if (query.accounts.length) params.set('account', query.accounts.join(','));
  if (query.view === 'voided') params.set('view', 'voided');
  Object.entries(query.quickFilters).forEach(([key, on]) => {
    if (on && query.view !== 'voided') params.set(key, '1');
  });
  if (query.startDate) params.set('start', query.startDate);
  if (query.endDate) params.set('end', query.endDate);
  if (!isDefaultSort(query.sort)) {
    params.set('sort', SORT_KEYS[query.sort.key]);
    params.set('dir', query.sort.dir);
  }
  if (query.pageSize !== DEFAULT_PAGE_SIZE) params.set('page_size', String(query.pageSize));
  if (query.page > 0) params.set('page', String(query.page + 1));
  const qs = params.toString();
  const url = `${window.location.pathname}${qs ? `?${qs}` : ''}${window.location.hash}`;
  if (url !== `${window.location.pathname}${window.location.search}${window.location.hash}`) {
    window.history.replaceState(window.history.state, '', url);
  }
}

/**
 * A selection summary (from `selection/`, snake_case) in the shape the table's
 * own rows have, so the batch bar reads one shape whichever way a row was selected.
 */
export function summaryAsRow(summary) {
  return {
    id: String(summary.id),
    importedTransactionId: summary.id,
    account: summary.account,
    inflow: summary.inflow,
    outflow: summary.outflow,
    isVoid: summary.is_void,
    isReconciled: summary.is_reconciled,
    isTransferMirror: summary.is_transfer_mirror,
    isSplit: summary.is_split,
    journalEntryId: summary.journal_entry_id,
    category: summary.category,
    reconciledStatementDate: summary.reconciled_statement_date,
    summaryOnly: true,
  };
}
