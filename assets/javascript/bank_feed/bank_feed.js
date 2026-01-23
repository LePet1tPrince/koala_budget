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
