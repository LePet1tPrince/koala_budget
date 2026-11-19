import { bookFromBase } from '../common/book';
import { getMonthlyReviewApi } from './api';

/**
 * The "Dismiss" button on the dashboard's monthly-review nudge card. Vanilla,
 * same shape as onboarding's resume.js -- one button, no React island needed.
 */
const button = document.querySelector('[data-dismiss-monthly-review]');

if (button) {
  button.addEventListener('click', async () => {
    button.disabled = true;
    try {
      await getMonthlyReviewApi(bookFromBase(button.dataset.bookBase), button.dataset.month).dismiss();
      document.querySelector('[data-testid="monthly-review-nudge"]')?.remove();
    } catch {
      // Re-enable, so the button is not left dead.
      button.disabled = false;
    }
  });
}
