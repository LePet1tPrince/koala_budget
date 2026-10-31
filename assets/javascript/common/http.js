import Cookies from 'js-cookie';

/**
 * Shared plumbing for the hand-written page APIs (`ynab_import`, `portability`,
 * `reconcile`, `onboarding`, `monthly_review`): the CSRF header, JSON in and
 * out, and one reading of an error.
 *
 * A failed response without an `error` field is one that never reached the
 * view -- a crash that returned Django's HTML page, a proxy timeout, a 413.
 * "Something went wrong" tells the user nothing they can act on, so the
 * thrown Error says what the server actually answered, plus the server's own
 * `detail` when it sent one. The Error carries `payload` and `status` for
 * callers that branch on them (a 409, a refusal's list of rows).
 */
export const jsonHeaders = (extra) => ({
  // Accept matters: some endpoints answer a plain form post with a redirect
  // (the no-JS fallback) and JSON only when asked for it.
  Accept: 'application/json',
  'X-CSRFToken': Cookies.get('csrftoken'),
  ...extra,
});

export const readJson = async (response) => {
  if (response.status === 204) return null;
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const reason = payload.error || `The server answered ${response.status} ${response.statusText}.`.trim();
    const detail = payload.detail ? ` (${payload.detail})` : '';
    throw Object.assign(new Error(`${reason}${detail}`), { payload, status: response.status });
  }
  return payload;
};

export const sendJson = async (method, url, body) =>
  readJson(
    await fetch(url, {
      method,
      headers: jsonHeaders({ 'Content-Type': 'application/json' }),
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  );

export const getJson = (url) => sendJson('GET', url);

export const postJson = (url, body) => sendJson('POST', url, body || {});

/** POST a `FormData` (file uploads); the browser sets the multipart Content-Type. */
export const postForm = async (url, form) =>
  readJson(await fetch(url, { method: 'POST', headers: jsonHeaders(), body: form }));
