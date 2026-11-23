import { JournalApi } from 'api-client';

import { apiDate, apiJson, getApiConfiguration } from '../api';
import { bookFromBase } from '../common/book';

/**
 * The Transactions page's endpoints (`apps/journal/views.py::TransactionViewSet`),
 * over the generated api-client. Each answers the server's JSON as sent
 * (snake_case), which is what the table and the edit modal read.
 *
 * Every write takes a list of ids, including a list of one. Editing a selection
 * later is then a caller change, not a second set of endpoints that could
 * disagree with these about what an edit means.
 */

/** The `f_<column>` filters, as the generated client's `fPayee`, `fDebitAccount`, ... arrays. */
const COLUMN_PARAMS = {
  date: 'fDate',
  payee: 'fPayee',
  description: 'fDescription',
  debit_account: 'fDebitAccount',
  credit_account: 'fCreditAccount',
  amount: 'fAmount',
  source: 'fSource',
  status: 'fStatus',
};

/**
 * The list/facets query for a filter state: `{search, startDate, endDate, columnFilters, sort}`,
 * where `columnFilters` is `{column: [{value, label}]}`. Empty values are left out.
 */
export function transactionQuery({ search, startDate, endDate, columnFilters = {}, sort = null }) {
  const query = {};
  if (search) query.search = search;
  if (startDate) query.startDate = startDate;
  if (endDate) query.endDate = endDate;
  Object.entries(columnFilters).forEach(([key, entries]) => {
    const param = COLUMN_PARAMS[key];
    if (param && entries.length) query[param] = entries.map((entry) => entry.value);
  });
  if (sort) {
    query.sort = sort.key;
    query.dir = sort.dir;
  }
  return query;
}

/** A partial edit as the generated `PatchedTransactionEditRequest` takes it: only the keys given. */
function editRequest(ids, updates) {
  const request = { ids };
  if ('date' in updates) request.date = apiDate(updates.date);
  if ('payee' in updates) request.payee = updates.payee;
  if ('description' in updates) request.description = updates.description;
  if ('account_id' in updates) request.accountId = updates.account_id;
  if ('category_id' in updates) request.categoryId = updates.category_id;
  if ('splits' in updates) request.splits = updates.splits;
  if ('remove_split' in updates) request.removeSplit = updates.remove_split;
  if ('inflow' in updates) request.inflow = updates.inflow;
  if ('outflow' in updates) request.outflow = updates.outflow;
  return request;
}

export function getTransactionsApi(bookBase) {
  const { params } = bookFromBase(bookBase);
  // The generated paths are absolute, so the page's own origin is the base.
  const client = () => new JournalApi(getApiConfiguration(window.location.origin));

  return {
    /** One page of rows for a `transactionQuery` (1-based `page`): `{count, next, results}`. */
    list: (query, page = 1) => apiJson(client().transactionsListRaw({ ...params, ...query, page })),

    /** The distinct values of one column, for its filter menu. */
    facets: (query, column, q) =>
      apiJson(client().transactionsFacetsRaw({ ...params, ...query, column, q: q || undefined })),

    /** The edit modal's account and payee pickers: `{accounts, payees}`. */
    pickers: () => apiJson(client().transactionsPickersRaw(params)),

    /** One transaction, with its legs and what may be changed about it. */
    fetchDetail: (id) => apiJson(client().transactionsRetrieveRaw({ ...params, id: Number(id) })),

    /** Apply one partial edit. Omitted fields are left alone. */
    saveEdits: (ids, updates) =>
      apiJson(client().transactionsEditRaw({ ...params, patchedTransactionEditRequest: editRequest(ids, updates) })),

    deleteTransactions: (ids) => apiJson(client().transactionsBatchDeleteRaw({ ...params, transactionIds: { ids } })),

    setStatus: (ids, status) =>
      apiJson(client().transactionsBatchStatusRaw({ ...params, transactionStatusRequest: { ids, status } })),
  };
}

export default getTransactionsApi;
