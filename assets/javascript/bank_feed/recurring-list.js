/* globals gettext */
import { apiCall } from '../api';
import { readBook } from '../common/book';
import { getBankFeedApiClient } from './bank_feed';

/**
 * The Recurring page's Stop buttons (`templates/bank_feed/recurring_list.html`):
 * `DELETE bankfeed/api/recurring/{id}/`, then the page reloads with the schedule
 * gone. The transactions it already added stay.
 */
const book = readBook();
const client = getBankFeedApiClient(window.location.origin);
const errorBox = document.querySelector('[data-recurring-error]');

document.addEventListener('click', async (event) => {
  const button = event.target.closest('[data-recurring-stop]');
  if (!button) return;
  if (!window.confirm(button.dataset.confirm)) return;
  button.disabled = true;
  try {
    await apiCall(client.bankFeedRecurringStopRaw({ ...book.params, id: Number(button.dataset.recurringStop) }));
    window.location.reload();
  } catch (err) {
    button.disabled = false;
    if (errorBox) {
      errorBox.textContent = `${gettext('Could not stop that recurring transaction.')} ${err.message}`;
      errorBox.classList.remove('hidden');
    }
  }
});
