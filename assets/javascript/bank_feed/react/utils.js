
/**
 * Utility functions for journal React components
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
 * Capitalize first letter of string
 * @param {string} val - String to capitalize
 * @returns {string} Capitalized string
 */
export function ProperCase(val) {
    return String(val).charAt(0).toUpperCase() + String(val).slice(1);
}