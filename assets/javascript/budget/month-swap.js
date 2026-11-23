// Budget page: change month without reloading the page.
//
// The picker used to set `window.location.href`, so picking a month threw away
// the whole document — the page blanked, every asset re-evaluated, and the
// browser dropped the reader at the top again. On a long chart of accounts that
// meant scrolling back down to where you were after every single month change.
//
// Instead the month's figures come from the budget API (`budgetMonthRetrieve`)
// and are painted into the markup already on screen (budget-api.js `applyMonth`):
// the table's rows and groups are the book's, not the month's, so only figures,
// month names and the month carried by forms and links change. When the rows
// themselves differ (a category was added or hidden since the page was drawn),
// the region is redrawn from the server-rendered page instead (`redraw`), so the
// template stays the one place the table's structure is rendered.
//
// Anything outside that element which still names the month (the "Edit Multiple
// Months" link, the picker's own `data-month`) is synced across afterwards.
import { applyMonth, fetchMonth, sameStructure } from './budget-api';

const SWAP_ID = 'budget-swap';

// Long enough that an ordinary swap — a few hundred milliseconds on a local
// network — shows no visual change at all. A dim-and-restore on every month
// change would be the very flicker this exists to remove; it is only worth
// showing once the wait is long enough to look like nothing happened.
const BUSY_AFTER_MS = 400;

/** Elements outside the swapped region that still carry the month (synced after a redraw). */
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
 * Show another month's budget, in place.
 *
 * @param {string}  month        'yyyy-MM-dd', the first of the target month.
 * @param {boolean} opts.push    Add a history entry (false when *handling* one).
 * @returns {Promise<boolean>}   Whether the page now shows that month.
 */
export async function swapToMonth(month, { push = true } = {}) {
  const root = swapRoot();
  if (!root) return false;

  const url = urlForMonth(month);
  const mine = ++ticket;
  const busy = markBusy(root);

  let figures;
  try {
    figures = await fetchMonth(month);
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

  if (sameStructure(figures, root)) {
    busy.clear();
    applyMonth(figures, root);
    syncMonthOutside(month);
  } else {
    // The rows changed since the page was drawn: draw it again, for this month.
    const drawn = await redraw(month, { owner: mine });
    if (mine !== ticket) return false;
    busy.clear();
    if (!drawn) {
      window.location.href = url;
      return false;
    }
  }
  rememberMonth(month);
  if (push) window.history.pushState({ budgetMonth: month }, '', url);
  return true;
}

/**
 * Redraw the whole `#budget-swap` region for `month` from the server-rendered
 * page (the same URL a navigation would load) — for a change to the table's
 * structure (hiding a category), which figures can't be painted into.
 *
 * @returns {Promise<boolean>} Whether the region was replaced.
 */
export async function redraw(month, { owner = null } = {}) {
  let html;
  try {
    const response = await window.fetch(urlForMonth(month), {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      credentials: 'same-origin',
    });
    if (!response.ok) return false;
    html = await response.text();
  } catch {
    return false;
  }
  // A month change started since: it owns the region now.
  if (owner !== null && owner !== ticket) return false;
  return applySwap(html, month);
}

// The page remembers the month on screen for the next visit to Budget or Goals
// (`views._month_from_request`): a navigation with ?month= tells the server, an
// in-place change writes this cookie. The suffix makes every change a new value,
// so the server can tell a change it hasn't seen yet from one it has.
const MONTH_COOKIE = 'budget_month';

function rememberMonth(month) {
  const stamp = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
  document.cookie = `${MONTH_COOKIE}=${encodeURIComponent(`${month}.${stamp}`)}; path=/; SameSite=Lax`;
}

/** The parts of the header that name the month, after an in-place change. */
function syncMonthOutside(month) {
  const picker = document.getElementById('budget-month-picker');
  if (picker) picker.dataset.month = month;
  const grid = document.querySelector('[data-testid="budget-grid-link"]');
  if (grid) {
    const href = new URL(grid.getAttribute('href'), window.location.href);
    href.searchParams.set('start', `${month.slice(0, 4)}-01-01`);
    grid.setAttribute('href', `${href.pathname}${href.search}`);
  }
}

/**
 * Replace the budget content with `html`, markup the server already rendered —
 * the whole budget page, of which only `#budget-swap` is taken.
 *
 * The caller owns ordering: a month swap still in flight would paint over this.
 *
 * @returns {boolean} Whether the markup held a `#budget-swap` to swap in.
 */
export function applySwap(html, month) {
  const root = swapRoot();
  if (!root) return false;
  const doc = new DOMParser().parseFromString(html, 'text/html');
  const next = doc.getElementById(SWAP_ID);
  if (!next) return false;

  root.replaceWith(next);
  runScripts(next);
  syncOutside(doc);
  if (doc.title) document.title = doc.title;

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
