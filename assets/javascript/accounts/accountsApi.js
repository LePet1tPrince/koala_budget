/* globals gettext */

import { AccountsApi, ResponseError } from 'api-client';

import { getApiConfiguration } from '../api';

/**
 * The accounts app's generated API client (`apps/accounts/api.py`). Every call
 * takes the book's slugs: `api.accountsBoardRetrieve({ ...book.params })`.
 * The generated paths are absolute, so the page's own origin is the base.
 */
export function getAccountsApi() {
  return new AccountsApi(getApiConfiguration(window.location.origin));
}

/**
 * The first message in a DRF error body: `{"detail": "..."}`, `{"field": ["..."]}`,
 * `{"non_field_errors": [...]}`, or the same nested under a list field.
 */
function firstMessage(payload) {
  if (typeof payload === 'string') return payload;
  if (Array.isArray(payload)) {
    for (const item of payload) {
      const found = firstMessage(item);
      if (found) return found;
    }
    return null;
  }
  if (payload && typeof payload === 'object') {
    for (const value of Object.values(payload)) {
      const found = firstMessage(value);
      if (found) return found;
    }
  }
  return null;
}

/** What to tell the user about a failed api-client call: the server's own reason when it gave one. */
export async function apiErrorMessage(error) {
  if (error instanceof ResponseError) {
    const payload = await error.response.json().catch(() => null);
    const message = firstMessage(payload);
    if (message) return message;
  }
  return gettext('Something went wrong. Please try again.');
}

/** Run an api-client call; a failure is rethrown as an `Error` whose message is `apiErrorMessage`. */
export async function callApi(request) {
  try {
    return await request();
  } catch (error) {
    throw new Error(await apiErrorMessage(error));
  }
}

/**
 * Book page URLs the accounts frontend links to, built from `book-base` (the
 * Django URLconf: `apps/accounts/urls.py`, `apps/budget/urls.py`).
 */
export function accountsUrls(base) {
  return {
    account: (id) => `${base}accounts/accounts/${id}/`,
    group: (id) => `${base}accounts/account-groups/${id}/`,
    accountCreatePage: `${base}accounts/accounts/new/`,
    newGoal: `${base}budget/goals/new/`,
  };
}
