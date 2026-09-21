// Budget page: change month without reloading the page.
//
// The picker used to set `window.location.href`, so picking a month threw away
// the whole document — the page blanked, every asset re-evaluated, and the
// browser dropped the reader at the top again. On a long chart of accounts that
// meant scrolling back down to where you were after every single month change.
//
// Instead we fetch the very same URL a full navigation would have loaded and
// replace only `#budget-swap` with the matching element from the response. The
// markup is therefore exactly what the server would have rendered anyway —
// there is no second rendering path to drift out of step with `budget_month_view`,
// which is the same reason `budget_save_amount` recomputes `_budget_figures`
// rather than patching figures by hand.
//
// Anything outside that element which still names the month (the "Edit Multiple
// Months" link, the picker's own `data-month`) is synced across afterwards.

const SWAP_ID = 'budget-swap';

// Long enough that an ordinary swap — a few hundred milliseconds on a local
// network — shows no visual change at all. A dim-and-restore on every month
// change would be the very flicker this exists to remove; it is only worth
// showing once the wait is long enough to look like nothing happened.
const BUSY_AFTER_MS = 400;

/** Elements outside the swapped region that still carry the month. */
const SYNC_ATTR = [
  ['[data-testid="budget-grid-link"]', 'href'],
  ['#budget-month-picker', 'data-month'],
];

export const swapRoot = () => document.getElementById(SWAP_ID);

/** The month currently in the address bar, or null when it says nothing. */
export const monthFromLocation = () => new URL(window.location).searchParams.get('month');

export const urlForMonth = (month) => {
  const url = new URL(window.location);
  url.searchParams.set('month', month);
  return url.toString();
};

// Only the newest request may paint: clicking through several months quickly
// would otherwise let an earlier, slower response land last and leave the page
// showing a month the address bar disagrees with.
let ticket = 0;

/**
 * Replace the budget content with another month's, in place.
 *
 * @param {string}  month        'yyyy-MM-dd', the first of the target month.
 * @param {boolean} opts.push    Add a history entry (false when *handling* one).
 * @returns {Promise<boolean>}   Whether the swap happened.
 */
export async function swapToMonth(month, { push = true } = {}) {
  const root = swapRoot();
  if (!root) return false;

  const url = urlForMonth(month);
  const mine = ++ticket;
  const busy = markBusy(root);

  let html;
  try {
    const response = await fetch(url, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      credentials: 'same-origin',
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    html = await response.text();
  } catch {
    // A superseded request owns nothing: the newer one is still holding the
    // busy state, and navigating would take the reader to a month they have
    // already clicked past.
    if (mine !== ticket) return false;
    busy.clear();
    // Whatever went wrong, a hard navigation still gets the reader to the month
    // they asked for. Losing the scroll position beats losing the click.
    window.location.href = url;
    return false;
  }

  if (mine !== ticket) return false;
  busy.clear();

  const doc = new DOMParser().parseFromString(html, 'text/html');
  const next = doc.getElementById(SWAP_ID);
  if (!next) {
    window.location.href = url;
    return false;
  }

  root.replaceWith(next);
  runScripts(next);
  syncOutside(doc);

  if (doc.title) document.title = doc.title;
  if (push) window.history.pushState({ budgetMonth: month }, '', url);

  // Whatever binds to this markup — the autosave fields, the Actual tooltips,
  // anything added later — listens for this rather than being called by name,
  // so a new feature on the page costs no change here.
  document.dispatchEvent(new CustomEvent('budget:swapped', { detail: { month, root: next } }));
  return true;
}

/**
 * Re-run the `<script>` tags that came in with the new markup.
 *
 * Inserted scripts never execute on their own, and the budget table and sidebar
 * each ship one that wires their checkboxes and Auto-Assign confirmation. They
 * are self-contained IIFEs that bind to whatever is in the document when they
 * run, so re-running them against the replacement markup is all they need; the
 * previous listeners went out with the elements they were attached to.
 */
function runScripts(container) {
  container.querySelectorAll('script').forEach((old) => {
    const fresh = document.createElement('script');
    Array.from(old.attributes).forEach((attr) => fresh.setAttribute(attr.name, attr.value));
    fresh.textContent = old.textContent;
    old.replaceWith(fresh);
  });
}

/** Carry the month across to the parts of the header that name it. */
function syncOutside(doc) {
  SYNC_ATTR.forEach(([selector, attr]) => {
    const source = doc.querySelector(selector);
    const target = document.querySelector(selector);
    const value = source?.getAttribute(attr);
    if (target && value != null) target.setAttribute(attr, value);
  });
}

/**
 * Hold the outgoing content still while the next month is on its way.
 *
 * Nothing changes visually unless the wait runs long — see BUSY_AFTER_MS. What
 * does take effect immediately is `inert`: the figures on screen are about to
 * be replaced, so editing them would be writing to a month the reader has
 * already left.
 */
function markBusy(root) {
  root.setAttribute('aria-busy', 'true');
  root.inert = true;
  const timer = setTimeout(() => root.classList.add('is-swapping'), BUSY_AFTER_MS);
  return {
    clear() {
      clearTimeout(timer);
      root.removeAttribute('aria-busy');
      root.inert = false;
      root.classList.remove('is-swapping');
    },
  };
}
