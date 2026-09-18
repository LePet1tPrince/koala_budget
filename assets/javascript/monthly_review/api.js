import Cookies from 'js-cookie';

/**
 * The three tiny state-writing endpoints (§2 of the plan): the review itself
 * ships whole in the page's json_script payload, so this is not a data layer,
 * just progress bookkeeping.
 */
const post = async (url, body) => {
  const response = await fetch(url, {
    method: 'POST',
    headers: {
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

export const getMonthlyReviewApi = (urls, month) => ({
  step: (step, baseline) => post(urls.step, { month, step, baseline }),
  complete: () => post(urls.complete, { month }),
  dismiss: () => post(urls.dismiss, { month }),
});
