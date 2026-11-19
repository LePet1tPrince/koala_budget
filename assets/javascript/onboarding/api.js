import { OnboardingApi } from 'api-client';

import { apiCall, getApiConfiguration } from '../api';

/**
 * The onboarding endpoints, through the generated api-client.
 *
 * The server owns the flow: it decides what phase the user is on and what still
 * needs answering. These helpers post and read back state; they never compute it.
 * `book` is `common/book.js`'s: its `params` are the two slugs every call takes.
 */
export const getOnboardingApi = (book) => {
  const client = new OnboardingApi(getApiConfiguration(''));
  const { params } = book;

  return {
    catalog: () => apiCall(client.onboardingCatalog(params)),
    state: () => apiCall(client.onboardingState(params)),
    saveAnswers: (answers, questionPhase) =>
      apiCall(client.onboardingSaveAnswers({ ...params, onboardingAnswersRequest: { answers, questionPhase } })),
    previewCoa: (answers, edits) => apiCall(client.onboardingPreviewCoa({ ...params, coaRequest: { answers, edits } })),
    complete: (answers, edits) => apiCall(client.onboardingComplete({ ...params, coaRequest: { answers, edits } })),
    skip: () => apiCall(client.onboardingSkip(params)),

    // The guided task rail.
    tasks: () => apiCall(client.onboardingTasks(params)),
    task: (body) => apiCall(client.onboardingTask({ ...params, onboardingTaskRequest: body })),
    openingBalances: () => apiCall(client.onboardingOpeningBalances(params)),
    setOpeningBalances: (rows) =>
      apiCall(client.onboardingSetOpeningBalances({ ...params, openingBalancesRequest: { rows } })),
  };
};
