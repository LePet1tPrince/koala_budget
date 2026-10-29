import { postJson } from '../common/http';

/**
 * The onboarding endpoints.
 *
 * The server owns the flow: it decides what phase the user is on and what still
 * needs answering. These helpers post and read back state; they never compute it.
 */
export const getOnboardingApi = (urls) => ({
  saveAnswers: (answers, questionPhase) => postJson(urls.answers, { answers, question_phase: questionPhase }),
  previewCoa: (answers, edits) => postJson(urls.previewCoa, { answers, edits }),
  complete: (answers, edits) => postJson(urls.complete, { answers, edits }),
  skip: () => postJson(urls.skip),
});
