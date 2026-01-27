import {BankFeedApi, PlaidApi, JournalApi} from "api-client";
import {getApiConfiguration, getApiHeaders} from "../api";

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
    uploadPreview: async (file, accountId, columnMapping, categoryMappings = []) => {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('account_id', accountId);
      formData.append('column_mapping', JSON.stringify(columnMapping));
      formData.append('category_mappings', JSON.stringify(categoryMappings));

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
      // Format date as YYYY-MM-DD string
      const dateStr = data.date instanceof Date
        ? data.date.toISOString().split('T')[0]
        : data.date;

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
      // Format date as YYYY-MM-DD string
      const dateStr = data.date instanceof Date
        ? data.date.toISOString().split('T')[0]
        : data.date;

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

  const postJson = async (endpoint, body) => {
    const response = await fetch(`${baseUrl}/${endpoint}/`, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': headers['X-CSRFToken'],
      },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.error || 'Operation failed');
    }
    return response.status === 204 ? null : response.json();
  };

  return {
    batchCategorize: (ids, categoryId) => postJson('batch_categorize', { ids, category_id: categoryId }),
    batchMoveAccount: (ids, accountId) => postJson('batch_move_account', { ids, account_id: accountId }),
    batchSetPayee: (ids, payee) => postJson('batch_set_payee', { ids, payee }),
    batchSetDescription: (ids, description) => postJson('batch_set_description', { ids, description }),
    batchArchive: (ids) => postJson('batch_archive', { ids }),
    batchUnarchive: (ids) => postJson('batch_unarchive', { ids }),
    batchDuplicate: (ids) => postJson('batch_duplicate', { ids }),
    batchReconcile: (ids, adjustmentAmount = 0) => postJson('batch_reconcile', { ids, adjustment_amount: adjustmentAmount }),
    batchUnreconcile: (ids) => postJson('batch_unreconcile', { ids }),
  };
}
