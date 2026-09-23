import {BankFeedApi, PlaidApi, JournalApi} from "api-client";
import {getApiConfiguration, getApiHeaders} from "../api";
import {formatDateForInput} from "./utils";

export function getBankFeedApiClient(serverBaseUrl) {
  return new BankFeedApi(getApiConfiguration(serverBaseUrl));
}

export function getPlaidApiClient(serverBaseUrl) {
  return new PlaidApi(getApiConfiguration(serverBaseUrl));
}

export function getJournalApiClient(serverBaseUrl) {
  return new JournalApi(getApiConfiguration(serverBaseUrl));
}

/**
 * Upload API helpers for CSV/Excel file uploads.
 * These use fetch with FormData since the generated api-client
 * doesn't handle multipart/form-data well.
 */
export function getUploadApiHelpers(teamSlug) {
  const headers = getApiHeaders();

  return {
    /**
     * A sample bank statement, for users who want to try the import before they
     * have a statement of their own. Downloading it creates nothing -- the file
     * goes through this same wizard, so the rows the user ends up with are ones
     * they chose to import.
     */
    sampleCsvUrl: `/a/${teamSlug}/bankfeed/api/feed/sample_csv/`,

    /**
     * Parse an uploaded file and return headers + sample rows
     */
    uploadParse: async (file) => {
      const formData = new FormData();
      formData.append('file', file);

      const response = await fetch(`/a/${teamSlug}/bankfeed/api/feed/upload_parse/`, {
        method: 'POST',
        body: formData,
        credentials: 'include',
        headers: {
          'X-CSRFToken': headers['X-CSRFToken'],
        },
      });

      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.error || 'Failed to parse file');
      }

      return response.json();
    },

    /**
     * Preview parsed transactions with column mapping
     */
    uploadPreview: async (file, accountId, columnMapping, categoryMappings = [], dateFormat = null) => {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('account_id', accountId);
      formData.append('column_mapping', JSON.stringify(columnMapping));
      formData.append('category_mappings', JSON.stringify(categoryMappings));
      if (dateFormat) formData.append('date_format', dateFormat);

      const response = await fetch(`/a/${teamSlug}/bankfeed/api/feed/upload_preview/`, {
        method: 'POST',
        body: formData,
        credentials: 'include',
        headers: {
          'X-CSRFToken': headers['X-CSRFToken'],
        },
      });

      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.error || 'Failed to preview transactions');
      }

      return response.json();
    },

    /**
     * Check every row's date cell against a chosen date format.
     * Returns { total_rows, invalid_count, invalid_samples, suggested_format, error }.
     */
    uploadValidateDates: async (file, dateColumn, dateFormat, hasHeaders = true) => {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('date_column', dateColumn);
      formData.append('date_format', dateFormat);
      formData.append('has_headers', hasHeaders ? 'true' : 'false');

      const response = await fetch(`/a/${teamSlug}/bankfeed/api/feed/upload_validate_dates/`, {
        method: 'POST',
        body: formData,
        credentials: 'include',
        headers: {
          'X-CSRFToken': headers['X-CSRFToken'],
        },
      });

      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.error || 'Failed to validate dates');
      }

      return response.json();
    },

    /**
     * Create a new account (for use during category mapping)
     */
    createAccount: async (name, accountGroupId) => {
      const response = await fetch(`/a/${teamSlug}/bankfeed/api/feed/create_account/`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': headers['X-CSRFToken'],
        },
        body: JSON.stringify({ name, account_group_id: accountGroupId }),
      });

      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.error || 'Failed to create account');
      }

      return response.json();
    },

    /**
     * Confirm and create transactions
     */
    uploadConfirm: async (accountId, transactions, skipDuplicates = true) => {
      const response = await fetch(`/a/${teamSlug}/bankfeed/api/feed/upload_confirm/`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': headers['X-CSRFToken'],
        },
        body: JSON.stringify({
          account_id: accountId,
          transactions: transactions,
          skip_duplicates: skipDuplicates,
        }),
      });

      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.error || 'Failed to import transactions');
      }

      return response.json();
    },
  };
}

/**
 * Transaction API helpers for creating and updating transactions.
 * Uses fetch with JSON body.
 */
export function getTransactionApi(teamSlug) {
  const headers = getApiHeaders();
  const baseUrl = `/a/${teamSlug}/bankfeed/api/feed`;

  return {
    /**
     * Create a new manual transaction with associated journal entry
     */
    createTransaction: async (data) => {
      // Format date as YYYY-MM-DD string (timezone-safe; toISOString would
      // shift local-midnight dates to the previous day east of UTC)
      const dateStr = formatDateForInput(data.date);

      const response = await fetch(`${baseUrl}/`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': headers['X-CSRFToken'],
        },
        body: JSON.stringify({
          date: dateStr,
          category: data.category?.id || data.category,
          inflow: data.inflow || '0',
          outflow: data.outflow || '0',
          payee: data.payee || '',
          description: data.description || '',
          account: data.account,
          // Split legs, when the transaction is apportioned across categories.
          // Null (the common case) leaves the single-category path untouched.
          splits: data.splits ?? null,
          remove_split: data.remove_split ?? false,
        }),
      });

      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.error || 'Failed to create transaction');
      }

      return response.json();
    },

    /**
     * Update an existing transaction and its associated journal entry
     */
    updateTransaction: async (id, data) => {
      // Format date as YYYY-MM-DD string (timezone-safe)
      const dateStr = formatDateForInput(data.date);

      const response = await fetch(`${baseUrl}/${id}/`, {
        method: 'PUT',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': headers['X-CSRFToken'],
        },
        body: JSON.stringify({
          date: dateStr,
          category: data.category?.id || data.category,
          inflow: data.inflow || '0',
          outflow: data.outflow || '0',
          payee: data.payee || '',
          description: data.description || '',
          account: data.account,
          // Split legs, when the transaction is apportioned across categories.
          // Null (the common case) leaves the single-category path untouched.
          splits: data.splits ?? null,
          remove_split: data.remove_split ?? false,
        }),
      });

      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.error || 'Failed to update transaction');
      }

      return response.json();
    },
  };
}

/**
 * Batch operations API helpers for bulk transaction operations.
 * Uses fetch with JSON body for batch endpoints.
 */
export function getBatchOperationsApi(teamSlug) {
  const headers = getApiHeaders();
  const baseUrl = `/a/${teamSlug}/bankfeed/api/feed`;

  const fetchJson = async (endpoint, body, method = 'POST') => {
    const response = await fetch(`${baseUrl}/${endpoint}/`, {
      method,
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': headers['X-CSRFToken'],
      },
      // GET requests must not carry a body.
      ...(method === 'GET' ? {} : { body: JSON.stringify(body) }),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.error || 'Operation failed');
    }
    return response.status === 204 ? null : response.json();
  };

  return {
    /**
     * Bulk edit transactions. Only provided (non-null) fields are updated.
     * @param {number[]} ids - Transaction IDs
     * @param {Object} updates - Fields to update (category_id, account_id, payee, description, date)
     */
    batchEdit: (ids, updates) => fetchJson('batch_edit', { ids, ...updates }, 'PATCH'),
    batchArchive: (ids) => fetchJson('batch_archive', { ids }),
    batchUnarchive: (ids) => fetchJson('batch_unarchive', { ids }),
    batchDelete: (ids) => fetchJson('batch_delete', { ids }),
    batchDuplicate: (ids) => fetchJson('batch_duplicate', { ids }),
    batchUnreconcile: (ids) => fetchJson('batch_unreconcile', { ids }),

    // Transfer duplicate review: list suggested pairs, archive one leg, or dismiss.
    transferSuggestions: () => fetchJson('transfers', null, 'GET'),
    transferResolve: (archiveId, keepId) => fetchJson('transfers/resolve', { archive_id: archiveId, keep_id: keepId }),
    transferDismiss: (transactionA, transactionB) => fetchJson('transfers/dismiss', { transaction_a: transactionA, transaction_b: transactionB }),

    fetchFeedAccounts: () => fetchJson('feed_accounts', null, 'GET'),
  };
}
