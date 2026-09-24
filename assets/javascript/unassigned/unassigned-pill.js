'use strict';
/**
 * Keeps the Unassigned pill (templates/budget/components/unassigned_pill.html)
 * current, and shows how much each action moved it (docs/unassigned-plan.md §3).
 *
 * Every write in the app goes through `fetch` — the generated API client, the
 * budget autosave, the goals quick-assign, the Inbox and categorize mode — so the
 * pill watches `fetch` rather than asking each of those to remember to tell it.
 * After any successful same-origin write it re-reads the figure; if it moved, the
 * pill flashes and a delta chip ("+$300.00", "−$150.00") says by how much.
 *
 * A full-page form post reloads instead, so the last figure seen is also kept in
 * sessionStorage: arriving on a page with a different figure than the one just
 * left shows the same chip, as long as it is the same month and only minutes old.
 */

const DEBOUNCE_MS = 350;
const CARRY_OVER_MS = 30 * 60 * 1000;
const STORAGE_KEY = 'koala:unassigned';

let pills = [];
let url = '';
let current = null;
let timer = null;
let ticket = 0;

const money = (value) =>
  Math.abs(value).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});

function remember(data) {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({url, month: data.month, raw: data.raw, at: Date.now()}));
  } catch {
    // Storage blocked (private window): the chip after a reload is a nicety.
  }
}

function recalled() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || 'null');
    if (saved && saved.url === url && Date.now() - saved.at < CARRY_OVER_MS) return saved;
  } catch {
    /* ignore */
  }
  return null;
}

function showDelta(pill, delta) {
  const chip = pill.querySelector('[data-unassigned-delta]');
  if (chip) {
    chip.dataset.direction = delta > 0 ? 'up' : 'down';
    chip.textContent = `${delta > 0 ? '+' : '−'}$${money(delta)}`;
    chip.hidden = false;
    // Restart the animation when a second change lands mid-chip.
    chip.style.animation = 'none';
    void chip.offsetWidth;
    chip.style.animation = '';
    clearTimeout(chip._hide);
    chip._hide = setTimeout(() => {
      chip.hidden = true;
    }, 4000);
  }
  pill.classList.remove('is-changed');
  void pill.offsetWidth;
  pill.classList.add('is-changed');
}

function paint(data) {
  const amount = Number(data.raw);
  const delta = current === null ? 0 : Math.round((amount - current) * 100) / 100;
  pills.forEach((pill) => {
    pill.dataset.state = data.state;
    const label = pill.querySelector('[data-unassigned-pill-label]');
    const value = pill.querySelector('[data-unassigned-pill-value]');
    const hint = pill.querySelector('[data-unassigned-pill-hint]');
    if (label) label.textContent = data.label;
    if (value) value.textContent = data.display;
    if (hint) hint.textContent = pill.dataset[`hint${data.state[0].toUpperCase()}${data.state.slice(1)}`] || '';
    if (delta) showDelta(pill, delta);
  });
  if (delta) {
    // One announcement, not one per pill (the mobile and desktop pills both exist),
    // from whichever is on screen: a live region inside display:none is never read.
    const shown = pills.find((pill) => pill.offsetParent !== null) || pills[0];
    const live = shown.querySelector('[data-unassigned-live]');
    if (live) {
      live.textContent = `${data.label} ${data.display}, ${delta > 0 ? 'up' : 'down'} $${money(delta)}`;
    }
  }
  current = amount;
  remember(data);
}

async function refresh() {
  const mine = ++ticket;
  try {
    const response = await nativeFetch(url, {credentials: 'same-origin', headers: {Accept: 'application/json'}});
    if (!response.ok) return;
    const data = await response.json();
    // A slower, older response must not overwrite a newer figure.
    if (mine === ticket) paint(data);
  } catch {
    // Offline or mid-navigation: the next write or page load catches up.
  }
}

function schedule() {
  clearTimeout(timer);
  timer = setTimeout(refresh, DEBOUNCE_MS);
}

function isWrite(input, init) {
  const method = ((init && init.method) || (input instanceof Request ? input.method : 'GET')).toUpperCase();
  return method !== 'GET' && method !== 'HEAD';
}

function sameOriginOther(input) {
  const target = new URL(input instanceof Request ? input.url : String(input), window.location.href);
  return target.origin === window.location.origin && target.pathname !== new URL(url, window.location.href).pathname;
}

const nativeFetch = window.fetch.bind(window);

function watchWrites() {
  window.fetch = async (input, init) => {
    const response = await nativeFetch(input, init);
    try {
      if (response.ok && isWrite(input, init) && sameOriginOther(input)) schedule();
    } catch {
      // Never let the watcher break the request it is watching.
    }
    return response;
  };
}

function init() {
  pills = Array.from(document.querySelectorAll('[data-unassigned-pill]'));
  if (!pills.length) return;
  url = pills[0].dataset.url;
  const raw = pills[0].dataset.raw;
  const month = pills[0].dataset.month;

  // Carry the ripple across a full-page form post.
  const saved = recalled();
  if (saved && saved.month === month) current = Number(saved.raw);
  paint({
    raw,
    month,
    state: pills[0].dataset.state,
    label: pills[0].querySelector('[data-unassigned-pill-label]')?.textContent.trim() || '',
    display: pills[0].querySelector('[data-unassigned-pill-value]')?.textContent.trim() || '',
  });

  watchWrites();
  // Back/forward cache restores a stale page; re-read it.
  window.addEventListener('pageshow', (event) => {
    if (event.persisted) refresh();
  });
  // Anything that changes money without a fetch can still ask.
  document.addEventListener('koala:unassigned-refresh', schedule);
  window.koalaUnassigned = {refresh};
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
