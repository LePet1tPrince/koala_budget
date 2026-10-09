// Budget page: one section (Income, Expenses) on screen at a time.
//
// Every panel is already in the page — the server renders them all and marks
// the inactive ones `hidden`, picking the active one from ?tab= or the
// `budget_tab` cookie — so switching is only a matter of moving `hidden`
// around. Nothing is fetched and nothing autosave holds is thrown away.
//
// The tab is written to the address bar (replaceState, so Back still leaves the
// page rather than stepping through tabs) and to the cookie, which is how the
// server knows the tab on a reload, on a month change (month-swap.js re-fetches
// the current URL, ?tab= included) and the next time the page is opened.
//
// Without script the tabs are plain links to ?tab=, which the server honours.

const COOKIE = 'budget_tab';
const COOKIE_MAX_AGE = 60 * 60 * 24 * 365;

const tabs = () => Array.from(document.querySelectorAll('[data-budget-tab]'));

function select(key, { focus = false } = {}) {
  const all = tabs();
  if (!all.some((tab) => tab.dataset.budgetTab === key)) return;

  all.forEach((tab) => {
    const active = tab.dataset.budgetTab === key;
    tab.classList.toggle('tab-active', active);
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
    if (active && focus) tab.focus();
  });
  document.querySelectorAll('[data-budget-panel]').forEach((panel) => {
    panel.hidden = panel.dataset.budgetPanel !== key;
  });
  document.querySelectorAll('[data-budget-tab-for]').forEach((el) => {
    el.hidden = el.dataset.budgetTabFor !== key;
  });

  remember(key);
}

function remember(key) {
  document.cookie = `${COOKIE}=${encodeURIComponent(key)}; path=/; max-age=${COOKIE_MAX_AGE}; SameSite=Lax`;
  const url = new URL(window.location);
  if (url.searchParams.get('tab') !== key) {
    url.searchParams.set('tab', key);
    window.history.replaceState(window.history.state, '', url);
  }
}

document.addEventListener('click', (event) => {
  const tab = event.target.closest('[data-budget-tab]');
  // A modified click opens the link where the user asked for it.
  if (!tab || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
  event.preventDefault();
  select(tab.dataset.budgetTab);
});

// Arrow keys, Home and End move between tabs and select as they go (the WAI-ARIA
// tabs pattern with automatic activation: switching costs nothing here).
document.addEventListener('keydown', (event) => {
  const tab = event.target.closest?.('[data-budget-tab]');
  if (!tab) return;
  const all = tabs();
  const index = all.indexOf(tab);
  let next = null;
  if (event.key === 'ArrowRight') next = all[(index + 1) % all.length];
  else if (event.key === 'ArrowLeft') next = all[(index - 1 + all.length) % all.length];
  else if (event.key === 'Home') next = all[0];
  else if (event.key === 'End') next = all[all.length - 1];
  if (!next) return;
  event.preventDefault();
  select(next.dataset.budgetTab, { focus: true });
});

// The column headings stick below the tab bar, whose height is not a constant
// (the tabs scroll sideways at phone width, and the font can be zoomed), so its
// measured height is published for them — as the page header does its own.
let observer = null;

function publishHeight() {
  const bar = document.getElementById('budget-tabs-bar');
  observer?.disconnect();
  if (!bar) {
    document.documentElement.style.setProperty('--budget-tabs-h', '0px');
    return;
  }
  const publish = () => document.documentElement.style.setProperty('--budget-tabs-h', `${bar.offsetHeight}px`);
  publish();
  if (window.ResizeObserver) {
    observer = new ResizeObserver(publish);
    observer.observe(bar);
  }
}

function init() {
  publishHeight();
  const active = tabs().find((tab) => tab.getAttribute('aria-selected') === 'true');
  if (active) remember(active.dataset.budgetTab);
}

init();
// A month change replaces the tab bar along with everything else in #budget-swap.
document.addEventListener('budget:swapped', init);
