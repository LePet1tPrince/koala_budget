import { bookFromBase } from '../common/book';
import { getOnboardingApi } from './api';

/**
 * "Pick it back up" on the dashboard: put the guided task rail back.
 *
 * Vanilla rather than a React island — it is one button, and the rail it brings
 * back is already the React surface. Reloads afterwards so the rail mounts
 * through its normal server-rendered path rather than being spawned by hand.
 */
const button = document.querySelector('[data-resume-onboarding]');

if (button) {
  const api = getOnboardingApi(bookFromBase(button.dataset.bookBase));

  button.addEventListener('click', async () => {
    button.disabled = true;
    try {
      await api.task({ action: 'resume' });
      window.location.reload();
      return;
    } catch {
      // Fall through to re-enabling, so the button is not left dead.
    }
    button.disabled = false;
  });
}
