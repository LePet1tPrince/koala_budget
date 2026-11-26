import { BankFeedApi, BudgetApi, PlaidApi, JournalApi } from 'api-client';
import { apiDate, apiJson, getApiConfiguration } from '../api';
import { bookFromBase } from '../common/book';

/**
 * The bank feed's API helpers, over the generated api-client (`apps/bank_feed/views.py`).
 *
 * Every helper answers the server's JSON as sent (snake_case, decimal strings) --
 * what the feed's components read -- via `api.js::apiJson`, and fails with its
 * `Error` (`message` is the server's reason; `status` and `payload` for callers
 * that branch on a refusal, e.g. a 409 carrying a fresh transfer proposal).
 * Requests go through the generated request models, which take camelCase keys.
 */

export function getBankFeedApiClient(serverBaseUrl) {
  return new BankFeedApi(getApiConfiguration(serverBaseUrl));
}

export function getPlaidApiClient(serverBaseUrl) {
  return new PlaidApi(getApiConfiguration(serverBaseUrl));
}

export function getJournalApiClient(serverBaseUrl) {
  return new JournalApi(getApiConfiguration(serverBaseUrl));
}

// The generated paths are absolute, so the page's own origin is the base.
const feedClient = () => getBankFeedApiClient(window.location.origin);

/** The feed accounts and the pickers the Inbox and Categorize mode open on. */
export function getFeedPageApi(bookBase) {
  const { params } = bookFromBase(bookBase);
  return {
    /** `{accounts, payees, account_groups}`: categories (goal accounts with what is left), payees, groups. */
    pickers: () => apiJson(feedClient().bankFeedPickersRaw(params)),
    /** Feed accounts with up-to-date balances and review counts. */
    feedAccounts: () => apiJson(feedClient().bankFeedFeedAccountsRaw(params)),
    /** Every uncategorized row in `scope` ({accounts, startDate, endDate}), walking every page. */
    uncategorized: async (scope) => {
      let rows = [];
      for (let page = 1; ; page += 1) {
        const data = await apiJson(
          feedClient().bankFeedFeedListRaw({
            ...params,
            uncategorized: true,
            account: scope.accounts.length ? scope.accounts.join(',') : undefined,
            startDate: apiDate(scope.startDate),
            endDate: apiDate(scope.endDate),
            page,
          }),
        );
        rows = rows.concat(data.results || []);
        if (!data.next) return rows;
      }
    },
    /**
     * Categorize Mode's queue for `scope`: `{groups: [{key, ids, suggestions, confident}]}`, the
     * uncategorized rows grouped by account, direction and merchant (`services/categorize_queue.py`).
     */
    categorizeQueue: (scope) =>
      apiJson(
        feedClient().bankFeedCategorizeQueueRaw({
          ...params,
          account: scope.accounts.length ? scope.accounts.join(',') : undefined,
          startDate: apiDate(scope.startDate),
          endDate: apiDate(scope.endDate),
        }),
      ),
    /** The categories used on transactions similar to each of `ids`. */
    similarCategories: (ids) => apiJson(feedClient().bankFeedSimilarCategoriesRaw({ ...params, ids: ids.join(',') })),
    /** Put these feed rows (BankTransaction ids) back to uncategorized: Categorize Mode's Undo. */
    uncategorize: (ids) => apiJson(feedClient().bankFeedUncategorizeRaw({ ...params, batchIds: { ids } })),
    /** The budget page's figures for `month` (`YYYY-MM`): each category's budgeted, actual and available. */
    budgetMonth: (month) =>
      apiJson(new BudgetApi(getApiConfiguration(window.location.origin)).budgetMonthRetrieveRaw({ ...params, month })),
    /** File these feed rows (BankTransaction ids) under one category. */
    categorize: (ids, categoryId) =>
      apiJson(
        feedClient().bankFeedTransactionsCategorizeRaw({
          ...params,
          categorizeTransactionsRequest: { rows: ids.map((id) => ({ id })), categoryId },
        }),
      ),
  };
}

/** The CSV/Excel upload wizard's endpoints, and creating a category from a picker. */
export function getUploadApiHelpers(bookBase) {
  const { params } = bookFromBase(bookBase);

  return {
    /**
     * A sample bank statement, for users who want to try the import before they
     * have a statement of their own. Downloading it creates nothing -- the file
     * goes through this same wizard, so the rows the user ends up with are ones
     * they chose to import. A link (a file download), not a fetch.
     */
    sampleCsvUrl: `${bookBase}bankfeed/api/feed/sample_csv/`,

    /** Parse an uploaded file and return headers + sample rows. */
    uploadParse: (file) => apiJson(feedClient().bankFeedUploadParseRaw({ ...params, file })),

    /** Preview parsed transactions with column mapping. */
    uploadPreview: (file, accountId, columnMapping, categoryMappings = [], dateFormat = null) =>
      apiJson(
        feedClient().bankFeedUploadPreviewRaw({
          ...params,
          file,
          accountId,
          columnMapping: JSON.stringify(columnMapping),
          categoryMappings: JSON.stringify(categoryMappings),
          dateFormat: dateFormat || undefined,
        }),
      ),

    /**
     * Check every row's date cell against a chosen date format.
     * Returns { total_rows, invalid_count, invalid_samples, suggested_format, error }.
     */
    uploadValidateDates: (file, dateColumn, dateFormat, hasHeaders = true) =>
      apiJson(feedClient().bankFeedUploadValidateDatesRaw({ ...params, file, dateColumn, dateFormat, hasHeaders })),

    /** The book's account groups (not budget buckets), for the create-account form. */
    getAccountGroups: () => apiJson(feedClient().bankFeedAccountGroupsRaw(params)),

    /** Create a new account (a category picker's "Create …"). */
    createAccount: (name, accountGroupId) =>
      apiJson(
        feedClient().bankFeedCreateAccountRaw({
          ...params,
          createFeedAccountRequest: { name, accountGroupId: Number(accountGroupId) },
        }),
      ),

    /** Confirm and create transactions. */
    uploadConfirm: (accountId, transactions, skipDuplicates = true) =>
      apiJson(
        feedClient().bankFeedUploadConfirmRaw({
          ...params,
          uploadConfirmRequest: {
            accountId,
            skipDuplicates,
            transactions: transactions.map((tx) => ({
              date: apiDate(tx.date),
              description: tx.description,
              payee: tx.payee,
              amount: tx.amount,
              categoryId: tx.category_id,
              skip: tx.skip,
            })),
          },
        }),
      ),
  };
}

/** A manual transaction's body as the generated `ManualTransaction` model takes it. */
function manualTransaction(data) {
  return {
    date: apiDate(data.date),
    category: data.category?.id || data.category || null,
    inflow: data.inflow || '0',
    outflow: data.outflow || '0',
    payee: data.payee || '',
    description: data.description || '',
    account: data.account,
    // Split legs, when the transaction is apportioned across categories.
    // Null (the common case) leaves the single-category path untouched.
    splits: data.splits ?? null,
    removeSplit: data.remove_split ?? false,
  };
}

/** Creating and updating manual feed transactions. */
export function getTransactionApi(bookBase) {
  const { params } = bookFromBase(bookBase);

  return {
    /** Create a new manual transaction with associated journal entry. */
    createTransaction: (data) =>
      apiJson(
        feedClient().bankFeedFeedCreateRaw({
          ...params,
          // How the transaction repeats ("Make recurring"), or null for a one-off.
          manualTransaction: { ...manualTransaction(data), recurrence: recurrence(data.recurrence) },
        }),
      ),

    /** Update an existing transaction and its associated journal entry. */
    updateTransaction: (id, data) =>
      apiJson(feedClient().bankFeedFeedUpdateRaw({ ...params, id, manualTransaction: manualTransaction(data) })),
  };
}

function recurrence(value) {
  if (!value) return null;
  return {
    frequency: value.frequency,
    interval: value.interval,
    weekday: value.weekday ?? null,
    dayOfMonth: value.day_of_month ?? null,
    endDate: apiDate(value.end_date),
  };
}

/** The keys of a `batch_edit` update the caller set (null included: it means "clear"). */
function batchEditRequest(ids, updates) {
  const request = { ids };
  if ('category_id' in updates) request.categoryId = updates.category_id;
  if ('account_id' in updates) request.accountId = updates.account_id;
  if ('payee' in updates) request.payee = updates.payee;
  if ('description' in updates) request.description = updates.description;
  if ('date' in updates) request.date = apiDate(updates.date) ?? null;
  return request;
}

/** Batch operations on feed rows, transfer matching, and the feed accounts' balances. */
export function getBatchOperationsApi(bookBase) {
  const { params } = bookFromBase(bookBase);
  const batch = (method, ids) => apiJson(feedClient()[method]({ ...params, batchIds: { ids } }));

  return {
    /**
     * Bulk edit transactions. Only provided fields are updated.
     * @param {number[]} ids - Transaction IDs
     * @param {Object} updates - Fields to update (category_id, account_id, payee, description, date)
     */
    batchEdit: (ids, updates) =>
      apiJson(
        feedClient().bankFeedBatchEditRaw({ ...params, patchedBatchEditRequest: batchEditRequest(ids, updates) }),
      ),
    batchVoid: (ids) => batch('bankFeedBatchVoidRaw', ids),
    batchRestore: (ids) => batch('bankFeedBatchRestoreRaw', ids),
    batchDelete: (ids) => batch('bankFeedBatchDeleteRaw', ids),
    batchDuplicate: (ids) => batch('bankFeedBatchDuplicateRaw', ids),

    // Transfer matching: list suggested pairs (each with the server's proposal),
    // match one (the server picks the leg to archive; `expectedArchiveId` is the
    // one the user was shown, refused with 409 if it no longer holds), or dismiss.
    transferSuggestions: () => apiJson(feedClient().bankFeedTransferSuggestionsRaw(params)),
    transferMatch: (transactionA, transactionB, expectedArchiveId) =>
      apiJson(
        feedClient().bankFeedTransferMatchRaw({
          ...params,
          transferMatchRequest: { transactionA, transactionB, expectedArchiveId },
        }),
      ),
    transferDismiss: (transactionA, transactionB) =>
      apiJson(
        feedClient().bankFeedTransferDismissRaw({ ...params, transferDismissRequest: { transactionA, transactionB } }),
      ),

    fetchFeedAccounts: () => apiJson(feedClient().bankFeedFeedAccountsRaw(params)),
  };
}
