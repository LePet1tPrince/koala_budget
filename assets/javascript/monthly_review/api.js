import { postJson } from '../common/http';

/**
 * The three tiny state-writing endpoints (§2 of the plan): the review itself
 * ships whole in the page's json_script payload, so this is not a data layer,
 * just progress bookkeeping.
 */
export const getMonthlyReviewApi = (urls, month) => ({
  step: (step, baseline) => postJson(urls.step, { month, step, baseline }),
  complete: () => postJson(urls.complete, { month }),
  dismiss: () => postJson(urls.dismiss, { month }),
});
