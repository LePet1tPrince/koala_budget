/**
 * Utility functions for bank-feed React components
 */

/**
 * Helper function to get CSRF token from cookies or DOM
 * @returns {string} CSRF token
 */
export function getCsrfToken() {
  // Try to get from cookie first
  const cookieMatch = document.cookie.match(/csrftoken=([^;]+)/);
  if (cookieMatch) {
    return cookieMatch[1];
  }
  // Fallback to hidden input
  const csrfInput = document.querySelector('[name=csrfmiddlewaretoken]');
  return csrfInput ? csrfInput.value : '';
}

/**
 * Format date for display
 * @param {string|Date} dateString - Date to format
 * @returns {string} Formatted date string
 */
export function formatDate(dateString) {
  return new Date(dateString).toLocaleDateString();
}

/**
 * Format date for input field (YYYY-MM-DD)
 * @param {string|Date} dateVal - Date to format
 * @returns {string} Date in YYYY-MM-DD format
 */
export function formatDateForInput(dateVal) {
  if (!dateVal) return '';
  const date = dateVal instanceof Date ? dateVal : new Date(dateVal);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

/**
 * Make an authenticated API request
 * @param {string} url - API endpoint URL
 * @param {Object} options - Fetch options
 * @returns {Promise<Response>} Fetch response
 */
export async function apiRequest(url, options = {}) {
  const defaultOptions = {
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCsrfToken(),
      ...options.headers,
    },
  };

  return fetch(url, { ...defaultOptions, ...options });
}

/**
 * Handle API errors consistently
 * @param {Response} response - Fetch response
 * @param {string} defaultMessage - Default error message
 * @throws {Error} Throws error with appropriate message
 */
export async function handleApiError(response, defaultMessage = 'API request failed') {
  if (!response.ok) {
    let errorMessage = defaultMessage;
    try {
      const errorData = await response.json();
      if (errorData.error) {
        errorMessage = errorData.error;
      } else if (errorData.detail) {
        errorMessage = errorData.detail;
      }
    } catch (e) {
      // If we can't parse the error response, use the default message
    }
    throw new Error(errorMessage);
  }
}

/**
 * Bank Feed API Client
 * Provides typed methods for interacting with the bank-feed API endpoints.
 * This follows the same pattern as the generated api-client.
 */
export class BankFeedApiClient {
  /**
   * Create a new BankFeedApiClient
   * @param {string} teamSlug - The team slug for API URLs
   */
  constructor(teamSlug) {
    this.teamSlug = teamSlug;
    this.baseUrl = `/a/${teamSlug}/bank-feed/api`;
  }

  /**
   * List bank transactions with optional filters
   * @param {Object} params - Query parameters
   * @param {number} [params.account] - Filter by account ID
   * @param {string} [params.source] - Filter by source (plaid, csv, manual)
   * @param {string} [params.dateFrom] - Filter by date from (YYYY-MM-DD)
   * @param {string} [params.dateTo] - Filter by date to (YYYY-MM-DD)
   * @param {boolean} [params.isCategorized] - Filter by categorization status
   * @param {boolean} [params.pending] - Filter by pending status
   * @returns {Promise<Object>} Paginated transaction list
   */
  async listTransactions(params = {}) {
    const queryParams = new URLSearchParams();

    if (params.account) queryParams.append('account', params.account);
    if (params.source) queryParams.append('source', params.source);
    if (params.dateFrom) queryParams.append('date_from', params.dateFrom);
    if (params.dateTo) queryParams.append('date_to', params.dateTo);
    if (params.isCategorized !== undefined) queryParams.append('is_categorized', params.isCategorized);
    if (params.pending !== undefined) queryParams.append('pending', params.pending);

    const url = `${this.baseUrl}/transactions/?${queryParams.toString()}`;
    const response = await apiRequest(url);
    await handleApiError(response, 'Failed to list transactions');
    return response.json();
  }

  /**
   * Get a single bank transaction by ID
   * @param {number} id - Transaction ID
   * @returns {Promise<Object>} Transaction data
   */
  async getTransaction(id) {
    const response = await apiRequest(`${this.baseUrl}/transactions/${id}/`);
    await handleApiError(response, 'Failed to get transaction');
    return response.json();
  }

  /**
   * Categorize one or more bank transactions
   * @param {Array<{id: number}>} rows - Array of transaction objects with id field
   * @param {number} categoryAccountId - ID of the category account
   * @returns {Promise<void>}
   */
  async categorizeTransactions(rows, categoryAccountId) {
    const response = await apiRequest(`${this.baseUrl}/transactions/categorize/`, {
      method: 'POST',
      body: JSON.stringify({
        rows: rows,
        category_account_id: categoryAccountId,
      }),
    });
    await handleApiError(response, 'Failed to categorize transactions');
    // 204 No Content response
  }
}

/**
 * Create a BankFeedApiClient instance
 * @param {string} teamSlug - The team slug
 * @returns {BankFeedApiClient} API client instance
 */
export function getBankFeedApiClient(teamSlug) {
  return new BankFeedApiClient(teamSlug);
}
