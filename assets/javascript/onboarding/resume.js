import Cookies from 'js-cookie';

/**
 * "Pick it back up" on the dashboard: put the guided task rail back.
 *
 * Vanilla rather than a React island — it is one button, and the rail it brings
 * back is already the React surface. Reloads afterwards so the rail mounts
 * through its normal server-rendered path rather than being spawned by hand.
 */
const button = document.querySelector('[data-resume-onboarding]');

if (button) {
  button.addEventListener('click', async () => {
    button.disabled = true;
    try {
      const response = await fetch(button.dataset.url, {
        method: 'POST',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json',
          'X-CSRFToken': Cookies.get('csrftoken'),
        },
        body: JSON.stringify({ action: 'resume' }),
      });
      if (response.ok) {
        window.location.reload();
        return;
      }
    } catch {
      // Fall through to re-enabling, so the button is not left dead.
    }
    button.disabled = false;
  });
}
