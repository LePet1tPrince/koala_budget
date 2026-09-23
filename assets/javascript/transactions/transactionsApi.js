/* globals gettext */

import { getApiHeaders } from '../api';

/**
 * The Transactions page's write endpoints.
 *
 * Hand-rolled rather than generated, matching `getBatchOperationsApi` in
 * `bank_feed/bank_feed.js` -- the generated client is regenerated from the
 * OpenAPI schema and these land alongside it, so a hand-written module keeps the
 * two from having to be kept in step by hand.
 *
 * Every write takes a list of ids, including a list of one. Editing a selection
 * later is then a caller change, not a second set of endpoints that could
 * disagree with these about what an edit means.
 */
export function getTransactionsApi(teamSlug) {
  const baseUrl = `/a/${teamSlug}/journal/api/transactions`;

  const request = async (path, { method = 'POST', body = null } = {}) => {
    const response = await fetch(`${baseUrl}/${path}`, {
      method,
      credentials: 'include',
      headers: {
        Accept: 'application/json',
        ...(body ? { 'Content-Type': 'application/json' } : {}),
        // Read per call rather than captured at construction: the token is
        // rotated on login, and this module outlives a page's first render.
        'X-CSRFToken': getApiHeaders()['X-CSRFToken'],
      },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });

    if (!response.ok) {
      // The server refuses with `{error}`; a field-level rejection comes back as
      // `{field: [messages]}`, so fall back to the first message rather than
      // showing the user "[object Object]".
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || firstMessage(payload) || gettext('Something went wrong. Please try again.'));
    }
    return response.status === 204 ? null : response.json();
  };

  return {
    /** One transaction, with its legs and what may be changed about it. */
    fetchDetail: (id) => request(`${id}/`, { method: 'GET' }),

    /** Apply one partial edit. Omitted fields are left alone. */
    saveEdits: (ids, updates) => request('edit/', { method: 'PATCH', body: { ids, ...updates } }),

    deleteTransactions: (ids) => request('batch_delete/', { body: { ids } }),

    setStatus: (ids, status) => request('batch_status/', { body: { ids, status } }),
  };
}

function firstMessage(payload) {
  const value = Object.values(payload || {})[0];
  if (Array.isArray(value)) return value[0];
  return typeof value === 'string' ? value : null;
}

export default getTransactionsApi;
