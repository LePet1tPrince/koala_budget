// Budget page: hide a category, bring one back, and fold the hidden ones away.
//
// Hiding is a display choice, never an accounting one: the server moves the
// category into its section's "Hidden" group and no figure changes, so the
// click can take effect at once — the row leaves the table before the request
// is even sent. The write goes through the budget API
// (`budgetCategoryVisibility`); once it is in, the `#budget-swap` region is
// redrawn from the server-rendered page (month-swap.js `redraw`), which settles
// the group subtotals and the hidden group's count — a change of structure,
// which the template renders, not a change of figures the API's answer could
// be painted into.
//
// Clicks made in quick succession are sent one after another, and only the
// last one redraws: each request is answered after every earlier one has been
// written, so the redraw after the last already shows them all.
//
// Without JS the Hide/Unhide buttons are plain form posts that redirect back,
// and the hidden rows are simply shown (see the <noscript> style in
// budget_table.html).
import { apiMonth, budget } from './budget-api';
import { monthFromLocation, redraw, swapRoot, swapToMonth } from './month-swap';

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
    tr.hidden = !expanded || tr.dataset.pending === 'true';
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

// ---------------------------------------------------------------------------
// Hide / unhide
// ---------------------------------------------------------------------------

// The requests in flight, chained so each is sent once the one before it has
// been answered; `latest` is the newest, the only one allowed to redraw.
let chain = Promise.resolve();
let latest = 0;
// The region the pending requests were made against. A month change replaces
// or repaints it, and a redraw for the old month must not land over the new one.
let rootAtStart = null;
let monthAtStart = null;
// Where focus goes once the table is redrawn; the button that was pressed
// leaves with its row.
let focusAfter = null;

// Hiding moves no money: the sidebar pill need not re-read its figure
// (unassigned-pill.js skips a write that says so).
const unassignedUnchanged = async ({ init }) => ({ headers: { ...init.headers, 'X-Unassigned-Unchanged': '1' } });

document.addEventListener('submit', (event) => {
  const form = event.target.closest('form[data-budget-visibility]');
  if (!form) return;
  event.preventDefault();

  const hiding = form.elements.hidden.value === '1';
  const { section, categoryId, categoryName } = form.dataset;
  const month = form.elements.month.value;
  const row = form.closest('tr');

  // Take effect now. The row stays in the document (hidden) until the redraw,
  // so a failed request can put it back.
  if (row) {
    row.dataset.pending = 'true';
    row.hidden = true;
  }
  if (hiding) {
    focusAfter = { selector: `[data-hidden-toggle="${section}"]` };
    document.querySelector(focusAfter.selector)?.focus();
    announce(`${categoryName} hidden. It is listed under hidden categories.`);
  } else {
    focusAfter = {
      selector: `form[data-budget-autosave][data-category-id="${categoryId}"] input[name="budget_amount"]`,
    };
    announce(`${categoryName} is back in the budget.`);
  }

  if (!latest) {
    rootAtStart = swapRoot();
    monthAtStart = rootAtStart?.dataset.budgetMonth ?? null;
  }
  const mine = ++latest;
  chain = chain.then(async () => {
    const { api, params } = budget();
    try {
      await api.budgetCategoryVisibility(
        { ...params, id: Number(categoryId), visibilityRequest: { hidden: hiding, month: apiMonth(month) } },
        unassignedUnchanged,
      );
    } catch {
      failed(row, form);
      return;
    }
    // Superseded: a later click is queued, and its redraw shows both.
    if (mine !== latest) return;
    latest = 0;
    settle(month);
  });
});

function failed(row, form) {
  if (row) {
    delete row.dataset.pending;
    row.hidden = row.dataset.hiddenRow ? !open.has(row.dataset.hiddenRow) : false;
  }
  // The plain form post still works, and reports its own outcome.
  if (form.isConnected) form.submit();
}

/** Redraw the table, unless it has moved on or is being typed in. */
async function settle(month) {
  const root = swapRoot();
  const stillOurs =
    root && root === rootAtStart && root.dataset.budgetMonth === monthAtStart && !root.hasAttribute('aria-busy');
  if (stillOurs && !editing() && (await redraw(month))) {
    restoreFocus();
    return;
  }
  // The row already left on click, so waiting costs nothing visible. Once the
  // field is left and its save is in, draw the month on screen afresh: the
  // page may have moved to another month in the meantime.
  whenIdle(() => swapToMonth(monthFromLocation() || month, { push: false }).then(restoreFocus));
}

/** An amount field is focused: replacing it would throw away what is being typed. */
function editing() {
  const active = document.activeElement;
  return Boolean(active?.matches?.('input[name="budget_amount"]') && swapRoot()?.contains(active));
}

function whenIdle(callback) {
  const saving = () => document.querySelector('.budget-status.is-saving');
  const tick = () => {
    if (editing() || saving()) setTimeout(tick, 150);
    else callback();
  };
  tick();
}

function restoreFocus() {
  const target = focusAfter;
  focusAfter = null;
  const active = document.activeElement;
  // Only if focus went nowhere (it was on the button that left with its row).
  if (!target || (active && active !== document.body)) return;
  document.querySelector(target.selector)?.focus();
}

renderAll();
document.addEventListener('budget:swapped', renderAll);
