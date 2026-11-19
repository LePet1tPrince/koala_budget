import { BankFeedApi, RulesApi } from 'api-client';

import { apiJson, getApiConfiguration } from '../api';
import { bookFromBase } from '../common/book';

/**
 * The rules endpoints (`apps/rules/views.py`), over the generated api-client.
 * `book` is `common/book.js`'s; each call answers the server's JSON as sent
 * (snake_case), which is what the builder and the list read. The feed builds the
 * same object from its book base (`rulesApiForBook`).
 */

/**
 * A builder rule (snake_case, as the API answers it) as the generated `Rule` /
 * `RuleDraft` models take it: only the keys the caller set, so a partial update
 * stays partial.
 */
function ruleModel(body) {
  const keys = {
    id: 'id',
    name: 'name',
    is_active: 'isActive',
    priority: 'priority',
    mode: 'mode',
    direction: 'direction',
    accounts: 'accounts',
    match: 'match',
    conditions: 'conditions',
    action: 'action',
    category: 'category',
    splits: 'splits',
    payee_name: 'payeeName',
    description: 'description',
    origin: 'origin',
    proposal_id: 'proposalId',
  };
  const model = {};
  Object.entries(keys).forEach(([key, name]) => {
    if (key in body) model[name] = body[key];
  });
  return model;
}

export const getRulesApi = (book) => {
  const { params } = book;
  // The generated paths are absolute, so the page's own origin is the base.
  const client = () => new RulesApi(getApiConfiguration(window.location.origin));
  const call = (method, extra = {}) => apiJson(client()[method]({ ...params, ...extra }));

  return {
    /** What the Rules page opens on: `{can_edit, categories, feed_accounts}`. */
    page: () => call('rulesPageRaw'),
    list: () => call('rulesListRaw'),
    get: (id) => call('rulesRetrieveRaw', { id }),
    create: (body) => call('rulesCreateRaw', { rule: ruleModel(body) }),
    update: (id, body) => call('rulesPartialUpdateRaw', { id, patchedRule: ruleModel(body) }),
    remove: (id) => call('rulesDestroyRaw', { id }),
    reorder: (ids) => call('rulesReorderRaw', { reorder: { ids } }),
    test: (draft) => call('rulesTestRaw', { ruleDraft: ruleModel(draft) }),
    explain: (draft, transactionId) =>
      call('rulesExplainRaw', { explainRequest: { rule: ruleModel(draft), transactionId } }),
    apply: (id) => call('rulesApplyRaw', { id }),
    graduate: (id, accept) => call('rulesGraduateRaw', { id, graduate: { accept } }),
    prompts: () => call('rulesPromptsRaw'),
    draftFromTransaction: (transactionId) => call('rulesDraftFromTransactionRaw', { transactionId: { transactionId } }),
    declineDraft: (signature, category) => call('rulesDeclineDraftRaw', { declineDraft: { signature, category } }),
    acceptMatches: (transactionIds) => call('rulesMatchesAcceptRaw', { acceptMatches: { transactionIds } }),
    dismissMatch: (transactionId) => call('rulesMatchesDismissRaw', { transactionId: Number(transactionId) }),
    undoMatch: (transactionId) => call('rulesMatchesUndoRaw', { transactionId: Number(transactionId) }),
    proposals: () => call('rulesProposalsListRaw'),
    acceptProposal: (id) => call('rulesProposalsAcceptRaw', { id }),
    dismissProposal: (id) => call('rulesProposalsDismissRaw', { id }),

    /** Recent active feed rows, for the builder's "Why did/didn't this match?" picker. */
    recentFeedRows: () =>
      apiJson(
        new BankFeedApi(getApiConfiguration(window.location.origin)).bankFeedFeedListRaw({
          ...params,
          view: 'active',
          pageSize: 200,
        }),
      ),
  };
};

/** The rules API for a page that knows only its book base (`/a/{team}/{book}/`). */
export const rulesApiForBook = (bookBase) => getRulesApi(bookFromBase(bookBase));

/** The Rules page, optionally opening the builder on one rule or on a draft. */
export const rulesPageUrl = (bookBase, { edit, draft } = {}) => {
  const url = `${bookBase}rules/`;
  if (edit) return `${url}?edit=${encodeURIComponent(edit)}`;
  if (draft) return `${url}?draft=${encodeURIComponent(JSON.stringify(draft))}`;
  return url;
};
