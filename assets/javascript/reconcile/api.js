import Cookies from 'js-cookie';

/**
 * The reconciliation endpoints (`apps/reconciliation/views.py`).
 *
 * Same shape as the other hand-written page APIs (`portability/api.js`): a
 * response without an `error` field never reached the view. Amounts go over
 * the wire as strings in STATEMENT sign; the server does every calculation
 * that is written down, the page only previews.
 */
const headers = () => ({
  Accept: 'application/json',
  'Content-Type': 'application/json',
  'X-CSRFToken': Cookies.get('csrftoken'),
});

const read = async (response) => {
  if (response.status === 204) return null;
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const reason = payload.error || `The server answered ${response.status} ${response.statusText}.`.trim();
    throw Object.assign(new Error(reason), { payload, status: response.status });
  }
  return payload;
};

const send = async (method, url, body) =>
  read(await fetch(url, { method, headers: headers(), body: body ? JSON.stringify(body) : undefined }));

export const getReconcileApi = (base) => ({
  start: (body) => send('POST', base, body),
  get: (id, includeLater = false) => send('GET', `${base}${id}/${includeLater ? '?include_later=1' : ''}`),
  update: (id, body) => send('PATCH', `${base}${id}/`, body),
  discard: (id) => send('DELETE', `${base}${id}/`),
  tick: (id, lineIds, ticked) => send('POST', `${base}${id}/tick/`, { line_ids: lineIds, ticked }),
  tickThrough: (id, date) => send('POST', `${base}${id}/tick_through/`, { date }),
  untickAll: (id) => send('POST', `${base}${id}/untick_all/`, {}),
  finish: (id, body) => send('POST', `${base}${id}/finish/`, body),
  undo: (id) => send('POST', `${base}${id}/undo/`, {}),
  history: (accountId) => send('GET', `${base}?account=${encodeURIComponent(accountId)}`),
});
