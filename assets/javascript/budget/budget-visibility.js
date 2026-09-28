// Budget page: hide a category, bring one back, and fold the hidden ones away.
//
// Hiding is a display choice, never an accounting one: the server moves the
// category into its section's "Hidden" group and every figure stays where it
// was. So rather than rebuild rows by hand, a hide/unhide re-renders the month
// in place through month-swap.js — the markup is exactly what a reload would
// have produced, without losing the scroll position.
//
// Without JS the Hide/Unhide buttons are plain form posts that redirect back,
// and the hidden rows are simply shown (see the <noscript> style in
// budget_table.html).
import Cookies from 'js-cookie';

import { swapToMonth } from './month-swap';

const STORAGE_KEY = 'budget-hidden-open';

// Which sections' hidden groups are expanded. Survives a hide/unhide or a month
// change (both replace the table), and a reload within the tab.
const open = new Set(readOpen());

function readOpen() {
  try {
    return JSON.parse(sessionStorage.getItem(STORAGE_KEY) || '[]');
  } catch {
    return [];
  }
}

function writeOpen() {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify([...open]));
  } catch {
    // Private mode or blocked storage: the state just doesn't outlive the page.
  }
}

function render(section) {
  const expanded = open.has(section);
  document.querySelectorAll(`tr[data-hidden-row="${section}"]`).forEach((tr) => {
    tr.hidden = !expanded;
  });
  const toggle = document.querySelector(`[data-hidden-toggle="${section}"]`);
  if (!toggle) return;
  toggle.setAttribute('aria-expanded', String(expanded));
  const chevron = toggle.querySelector('[data-hidden-chevron]');
  if (chevron) chevron.classList.toggle('rotate-90', expanded);
}

function renderAll() {
  document.querySelectorAll('[data-hidden-toggle]').forEach((toggle) => render(toggle.dataset.hiddenToggle));
}

function announce(message) {
  const live = document.querySelector('[data-budget-live]');
  if (live) live.textContent = message;
}

document.addEventListener('click', (event) => {
  const toggle = event.target.closest('[data-hidden-toggle]');
  if (!toggle) return;
  const section = toggle.dataset.hiddenToggle;
  if (open.has(section)) open.delete(section);
  else open.add(section);
  writeOpen();
  render(section);
});

document.addEventListener('submit', async (event) => {
  const form = event.target.closest('form[data-budget-visibility]');
  if (!form) return;
  event.preventDefault();

  const hiding = form.elements.hidden.value === '1';
  const { section, categoryId, categoryName } = form.dataset;
  const month = form.elements.month.value;
  form.querySelectorAll('button').forEach((btn) => {
    btn.disabled = true;
  });

  let ok = false;
  try {
    const response = await fetch(form.action, {
      method: 'POST',
      headers: { Accept: 'application/json', 'X-CSRFToken': Cookies.get('csrftoken') || '' },
      body: new FormData(form),
      credentials: 'same-origin',
    });
    ok = response.ok;
  } catch {
    ok = false;
  }
  // The plain form post still works and reports its own outcome.
  if (!ok) {
    form.submit();
    return;
  }

  if (!(await swapToMonth(month, { push: false }))) return;

  // The button that was pressed went out with the old markup: land focus on
  // where the category went, so a keyboard user isn't dropped at the top.
  if (hiding) {
    document.querySelector(`[data-hidden-toggle="${section}"]`)?.focus();
    announce(`${categoryName} hidden. It is listed under hidden categories.`);
  } else {
    const input = document.querySelector(
      `form[data-budget-autosave][data-category-id="${categoryId}"] input[name="budget_amount"]`,
    );
    input?.focus();
    announce(`${categoryName} is back in the budget.`);
  }
});

renderAll();
document.addEventListener('budget:swapped', renderAll);
