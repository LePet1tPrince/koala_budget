import { sendJson } from '../common/http';

/**
 * The rules endpoints (`apps/rules/views.py`), from the API root the page is given
 * (`/a/{team}/{book}/rules/api/`). The feed builds the same object from the book base.
 */
export const getRulesApi = (base) => ({
  list: () => sendJson('GET', `${base}rules/`),
  create: (body) => sendJson('POST', `${base}rules/`, body),
  update: (id, body) => sendJson('PATCH', `${base}rules/${id}/`, body),
  remove: (id) => sendJson('DELETE', `${base}rules/${id}/`),
  reorder: (ids) => sendJson('POST', `${base}rules/reorder/`, { ids }),
  test: (draft) => sendJson('POST', `${base}rules/test/`, draft),
  explain: (draft, transactionId) =>
    sendJson('POST', `${base}rules/explain/`, { rule: draft, transaction_id: transactionId }),
  apply: (id) => sendJson('POST', `${base}rules/${id}/apply/`, {}),
  graduate: (id, accept) => sendJson('POST', `${base}rules/${id}/graduate/`, { accept }),
  prompts: () => sendJson('GET', `${base}rules/prompts/`),
  draftFromTransaction: (transactionId) =>
    sendJson('POST', `${base}rules/draft_from_transaction/`, { transaction_id: transactionId }),
  declineDraft: (signature, category) => sendJson('POST', `${base}rules/decline_draft/`, { signature, category }),
  acceptMatches: (transactionIds) => sendJson('POST', `${base}matches/accept/`, { transaction_ids: transactionIds }),
  dismissMatch: (transactionId) => sendJson('POST', `${base}matches/${transactionId}/dismiss/`, {}),
  undoMatch: (transactionId) => sendJson('POST', `${base}matches/${transactionId}/undo/`, {}),
  proposals: () => sendJson('GET', `${base}proposals/`),
  acceptProposal: (id) => sendJson('POST', `${base}proposals/${id}/accept/`, {}),
  dismissProposal: (id) => sendJson('POST', `${base}proposals/${id}/dismiss/`, {}),
});

/** The rules API for a page that knows only its book base (`/a/{team}/{book}/`). */
export const rulesApiForBook = (bookBase) => getRulesApi(`${bookBase}rules/api/`);

/** The Rules page, optionally opening the builder on one rule or on a draft. */
export const rulesPageUrl = (bookBase, { edit, draft } = {}) => {
  const url = `${bookBase}rules/`;
  if (edit) return `${url}?edit=${encodeURIComponent(edit)}`;
  if (draft) return `${url}?draft=${encodeURIComponent(JSON.stringify(draft))}`;
  return url;
};
