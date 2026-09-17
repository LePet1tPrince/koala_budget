import Cookies from 'js-cookie';

/**
 * The onboarding endpoints.
 *
 * The server owns the flow: it decides what phase the user is on and what still
 * needs answering. These helpers post and read back state; they never compute it.
 */
const post = async (url, body) => {
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      // Accept matters: the skip endpoint answers a plain form post with a
      // redirect (the no-JS fallback) and JSON only when asked for it.
      Accept: 'application/json',
      'Content-Type': 'application/json',
      'X-CSRFToken': Cookies.get('csrftoken'),
    },
    body: JSON.stringify(body || {}),
  });

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw Object.assign(new Error(payload.error || 'Something went wrong.'), { payload });
  }
  return payload;
};

export const getOnboardingApi = (urls) => ({
  saveAnswers: (answers, questionPhase) => post(urls.answers, { answers, question_phase: questionPhase }),
  previewCoa: (answers, edits) => post(urls.previewCoa, { answers, edits }),
  complete: (answers, edits) => post(urls.complete, { answers, edits }),
  skip: () => post(urls.skip),
});
