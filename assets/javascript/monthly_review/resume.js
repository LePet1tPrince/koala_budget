import Cookies from 'js-cookie';

/**
 * The "Dismiss" button on the dashboard's monthly-review nudge card. Vanilla,
 * same shape as onboarding's resume.js -- one button, no React island needed.
 */
const button = document.querySelector('[data-dismiss-monthly-review]');

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
        body: JSON.stringify({ month: button.dataset.month }),
      });
      if (response.ok) {
        document.querySelector('[data-testid="monthly-review-nudge"]')?.remove();
        return;
      }
    } catch {
      // Fall through to re-enabling, so the button is not left dead.
    }
    button.disabled = false;
  });
}
