import { sendJson } from '../common/http';

/**
 * The reconciliation endpoints (`apps/reconciliation/views.py`).
 *
 * Amounts go over the wire as strings in STATEMENT sign; the server does every
 * calculation that is written down, the page only previews.
 */
export const getReconcileApi = (base) => ({
  start: (body) => sendJson('POST', base, body),
  get: (id, includeLater = false) => sendJson('GET', `${base}${id}/${includeLater ? '?include_later=1' : ''}`),
  update: (id, body) => sendJson('PATCH', `${base}${id}/`, body),
  discard: (id) => sendJson('DELETE', `${base}${id}/`),
  tick: (id, lineIds, ticked) => sendJson('POST', `${base}${id}/tick/`, { line_ids: lineIds, ticked }),
  tickThrough: (id, date) => sendJson('POST', `${base}${id}/tick_through/`, { date }),
  untickAll: (id) => sendJson('POST', `${base}${id}/untick_all/`, {}),
  finish: (id, body) => sendJson('POST', `${base}${id}/finish/`, body),
  undo: (id) => sendJson('POST', `${base}${id}/undo/`, {}),
  history: (accountId) => sendJson('GET', `${base}?account=${encodeURIComponent(accountId)}`),
});
