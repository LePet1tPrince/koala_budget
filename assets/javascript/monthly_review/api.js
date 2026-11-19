import { MonthlyReviewApi } from 'api-client';

import { apiCall, getApiConfiguration } from '../api';

/**
 * The monthly review's API (`apps/monthly_review/views.py`): one read of the whole
 * review for a month, and the small writes recording walkthrough progress.
 */
const client = () => new MonthlyReviewApi(getApiConfiguration(window.location.origin));

/** Book page URLs the review links to, built from `book-base` (the Django URLconf). */
export const reviewUrls = (base, month) => ({
  export: `${base}reports/monthly-review/export/?month=${month}`,
  reportsHome: `${base}reports/`,
  inbox: `${base}bankfeed/`,
  transactions: `${base}journal/transactions/`,
});

// Money arrives as decimal strings; the review components do arithmetic on it.
const MONEY_KEYS = new Set([
  'amount',
  'assets',
  'assigned',
  'available',
  'avg',
  'balance',
  'balance_change',
  'balance_gap',
  'delta',
  'gap',
  'income',
  'liabilities',
  'metric',
  'net',
  'over',
  'prev',
  'reconciled_balance',
  'saved',
  'spend',
  'spent',
  'values',
  'vs_avg',
]);
// Maps of id -> amount.
const MONEY_MAPS = new Set(['cat_avg', 'changes']);

const asNumber = (value) => (typeof value === 'string' ? Number(value) : value);

function withNumbers(value, key) {
  if (Array.isArray(value)) {
    return value.map((item) => (MONEY_KEYS.has(key) ? asNumber(item) : withNumbers(item)));
  }
  if (value && typeof value === 'object') {
    const out = {};
    Object.entries(value).forEach(([childKey, child]) => {
      out[childKey] = MONEY_MAPS.has(key) ? asNumber(child) : withNumbers(child, childKey);
    });
    return out;
  }
  return MONEY_KEYS.has(key) ? asNumber(value) : value;
}

/**
 * The review in the shape the components read: the server's own snake_case keys
 * (the raw response, not the camelCased generated model -- every step and part is
 * written against those keys), money as numbers, and the links the API leaves to
 * the client (an insight's `action`, a transaction's `entry_id`) as page URLs.
 */
function reviewForPage(review, urls) {
  const out = withNumbers(review);
  out.insights = out.insights.map((insight) => ({ ...insight, url: insight.action === 'inbox' ? urls.inbox : '' }));
  out.biggest = out.biggest.map((row) => ({ ...row, entry_url: urls.transactions }));
  return out;
}

const stateForPage = (state) => ({
  step: state.step,
  stepsSeen: state.steps_seen,
  baseline: state.baseline,
  isFinished: state.is_finished,
});

/** `{month, hasActivity, review, state}` for `month` (YYYY-MM). */
export async function loadReview(book, month, urls) {
  const response = await apiCall(client().monthlyReviewRetrieveRaw({ ...book.params, month }));
  const payload = await response.raw.json();
  return {
    month: payload.month,
    hasActivity: payload.has_activity,
    review: payload.review ? reviewForPage(payload.review, urls) : null,
    state: stateForPage(payload.state),
  };
}

/** Progress bookkeeping for one month's walkthrough. */
export const getMonthlyReviewApi = (book, month) => ({
  step: (step, baseline) =>
    apiCall(client().monthlyReviewStep({ ...book.params, reviewStepRequest: { month, step, baseline } })),
  complete: () => apiCall(client().monthlyReviewComplete({ ...book.params, reviewMonthRequest: { month } })),
  dismiss: () => apiCall(client().monthlyReviewDismiss({ ...book.params, reviewMonthRequest: { month } })),
});
