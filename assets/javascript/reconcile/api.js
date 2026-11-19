import { ReconciliationApi } from 'api-client';

import { apiDate, apiJson, getApiConfiguration } from '../api';

/**
 * The reconciliation endpoints (`apps/reconciliation/views.py`), over the
 * generated api-client. `book` is `common/book.js`'s; each call answers the
 * server's JSON as sent (snake_case), which is what the workspace reads.
 *
 * Amounts go over the wire as strings in STATEMENT sign; the server does every
 * calculation that is written down, the page only previews.
 */
export const getReconcileApi = (book) => {
  const { params } = book;
  // The generated paths are absolute, so the page's own origin is the base.
  const client = () => new ReconciliationApi(getApiConfiguration(window.location.origin));

  return {
    /** What one account's page opens on: account, open draft, defaults, history, feed pickers. */
    page: (accountId) => apiJson(client().reconciliationPageRaw({ ...params, account: Number(accountId) })),
    start: (body) =>
      apiJson(
        client().reconciliationStartRaw({
          ...params,
          reconciliationStart: {
            account: body.account,
            statementDate: apiDate(body.statement_date),
            statementBalance: body.statement_balance,
            lineIds: body.line_ids,
          },
        }),
      ),
    get: (id, includeLater = false) =>
      apiJson(client().reconciliationRetrieveRaw({ ...params, id, includeLater: includeLater || undefined })),
    update: (id, body) =>
      apiJson(
        client().reconciliationUpdateRaw({
          ...params,
          id,
          patchedReconciliationUpdate: {
            statementDate: apiDate(body.statement_date),
            statementBalance: body.statement_balance,
          },
        }),
      ),
    discard: (id) => apiJson(client().reconciliationDiscardRaw({ ...params, id })),
    tick: (id, lineIds, ticked) =>
      apiJson(client().reconciliationTickRaw({ ...params, id, reconciliationTick: { lineIds, ticked } })),
    tickThrough: (id, date) =>
      apiJson(
        client().reconciliationTickThroughRaw({ ...params, id, reconciliationTickThrough: { date: apiDate(date) } }),
      ),
    untickAll: (id) => apiJson(client().reconciliationUntickAllRaw({ ...params, id })),
    finish: (id, body) =>
      apiJson(
        client().reconciliationFinishRaw({
          ...params,
          id,
          reconciliationFinish: { adjust: body.adjust, expectedDifference: body.expected_difference },
        }),
      ),
    undo: (id) => apiJson(client().reconciliationUndoRaw({ ...params, id })),
    history: (accountId) => apiJson(client().reconciliationListRaw({ ...params, account: Number(accountId) })),
  };
};
