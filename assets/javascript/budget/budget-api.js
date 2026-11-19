// The budget page's side of the budget API (apps/budget/api/).
//
// The page is rendered by the server; every figure in it carries a
// `data-budget-cell` key (budget_table.html, budget_sidebar.html). The API
// answers with structured figures — sections → groups → rows, by id — and this
// module turns them into those keys and paints them, so the autosave, the cover
// dialog, Auto-Assign and the month change all repaint the same way.
import { BudgetApi } from 'api-client';

import { getApiConfiguration } from '../api';
import { formatMoney } from '../common/amount';
import { readBook } from '../common/book';

/* globals gettext, ngettext, interpolate */

let client = null;
let book = null;

/** The generated client and the book's slugs, for `budget().api.budgetX({ ...budget().params, ... })`. */
export function budget() {
  if (!client) {
    book = readBook();
    client = new BudgetApi(getApiConfiguration(window.location.origin));
  }
  return { api: client, params: book.params, book };
}

/** `YYYY-MM` for the API from the page's `YYYY-MM-DD` (or a `YYYY-MM` already). */
export const apiMonth = (value) => String(value || '').slice(0, 7);

/** The page's `YYYY-MM-DD` (first of the month) from the API's `YYYY-MM`. */
export const pageMonth = (value) => `${apiMonth(value)}-01`;

/** The last day of `YYYY-MM`, as `YYYY-MM-DD`. */
export function monthEnd(value) {
  const [year, month] = apiMonth(value).split('-').map(Number);
  const last = new Date(Date.UTC(year, month, 0)).getUTCDate();
  return `${apiMonth(value)}-${String(last).padStart(2, '0')}`;
}

/** The month's name in the page's language ("March"), as the template's `date:"F"`. */
export function monthName(value) {
  const [year, month] = apiMonth(value).split('-').map(Number);
  return new Intl.DateTimeFormat(document.documentElement.lang || undefined, {
    month: 'long',
    timeZone: 'UTC',
  }).format(new Date(Date.UTC(year, month - 1, 1)));
}

/** The month's figures, from the API. */
export function fetchMonth(month) {
  const { api, params } = budget();
  return api.budgetMonthRetrieve({ ...params, month: apiMonth(month) });
}

/** The first message of a DRF error body (`{field: [msg]}`, `{detail}`), or `fallback`. */
export async function errorMessage(error, fallback) {
  let body = null;
  try {
    body = error?.response ? await error.response.json() : null;
  } catch {
    body = null;
  }
  const first = (value) => {
    if (typeof value === 'string') return value;
    if (Array.isArray(value)) return value.length ? first(value[0]) : null;
    if (value && typeof value === 'object') return first(Object.values(value)[0]);
    return null;
  };
  return (body && (body.detail || first(body))) || fallback;
}

// ---------------------------------------------------------------------------
// Words: the same as the templates' (`apps/budget/display.py`)
// ---------------------------------------------------------------------------

const t = (text) => (typeof gettext === 'function' ? gettext(text) : text);

function format(template, values) {
  if (typeof interpolate === 'function') return interpolate(template, values, true);
  return template.replace(/%\((\w+)\)s/g, (_, key) => values[key]);
}

export function overspentText(count) {
  const template =
    typeof ngettext === 'function'
      ? ngettext('%(counter)s overspent', '%(counter)s overspent', count)
      : '%(counter)s overspent';
  return format(template, { counter: count });
}

/** [text, tone] for an Available figure: budgeted income not yet received reads "still expected". */
export function availableDisplay(amount, income = false) {
  const value = Number(amount) || 0;
  if (income && value < 0) return [format(t('%(amount)s still expected'), { amount: formatMoney(-value) }), 'expected'];
  return [formatMoney(value), value < 0 ? 'neg' : value > 0 ? 'pos' : ''];
}

// ---------------------------------------------------------------------------
// Structured figures → the page's cells
// ---------------------------------------------------------------------------

/**
 * `{cell key: {value, tone, toned, hidden?, width?}}` for every figure in `figures`
 * (a `BudgetMonth`), keyed like the templates' `data-budget-cell` attributes.
 * A group's key is its position in its section, as the template numbers it.
 *
 * Row actuals are left out: a budget write never moves them, and the Actual
 * popover keeps its own (a month change sets them, see `applyMonth`).
 */
export function cellsFromFigures(figures) {
  const cells = {};
  const put = (key, amount, { toned = false, income = false } = {}) => {
    const [value, tone] = availableDisplay(amount, income);
    cells[key] = toned ? { value, tone, toned } : { value: formatMoney(amount), tone: '', toned };
  };

  figures.sections.forEach((section) => {
    const { key, income } = section;
    section.groups.forEach((group, index) => {
      group.rows.forEach((row) => {
        const id = row.categoryId;
        put(`row:${id}:available`, row.available, { toned: true, income });
        cells[`row:${id}:meter`] = {
          value: row.meter.label,
          tone: row.meter.over ? 'neg' : '',
          width: row.meter.width,
        };
        // Not rendered — the Auto-Assign confirm dialog reads it off the row checkbox.
        cells[`row:${id}:budgeted`] = { value: row.budgeted, tone: '', data: true };
      });
      put(`group:${key}:${index}:budgeted`, group.subtotals.budgeted);
      put(`group:${key}:${index}:actual`, group.subtotals.actual);
      put(`group:${key}:${index}:available`, group.subtotals.available, { toned: true, income });
      if (group.hidden) {
        cells[`group:${key}:${index}:overspent`] = {
          value: overspentText(group.overspent),
          tone: '',
          hidden: group.overspent === 0,
        };
      }
    });
    put(`section:${key}:budgeted`, section.totals.budgeted);
    put(`section:${key}:actual`, section.totals.actual);
    // The footer total is worded like Available but never coloured.
    cells[`section:${key}:available`] = { value: availableDisplay(section.totals.available, income)[0], tone: '' };
    put(`tab:${key}:budgeted`, section.totals.budgeted);
    if (key === 'expense') {
      cells['tab:expense:overspent'] = {
        value: overspentText(section.overspent),
        tone: '',
        hidden: section.overspent === 0,
      };
    }
    const { summary } = section;
    put(`sidebar:${key}:leftover`, summary.leftoverLastMonth, { toned: true, income });
    put(`sidebar:${key}:assigned`, summary.assignedThisMonth);
    put(`sidebar:${key}:activity`, summary.activityThisMonth);
    put(`sidebar:${key}:available`, summary.available, { toned: true, income });
  });
  return cells;
}

function flash(el) {
  el.classList.remove('budget-cell-flash');
  // Restart the animation on a cell that is still mid-flash.
  void el.offsetWidth;
  el.classList.add('budget-cell-flash');
}

// A row's progress bar: the fill's width animates in CSS, the label is its %.
function paintMeter(el, cell) {
  const fill = el.querySelector('.budget-meter-fill');
  const label = el.querySelector('.budget-meter-label');
  if (fill) fill.style.width = `${cell.width}%`;
  if (label) label.textContent = cell.value;
  if (!el.classList.contains('is-income')) el.classList.toggle('is-over', cell.tone === 'neg');
}

/**
 * Write `figures` into the page. Only cells whose text changed are touched (and
 * flash). Returns nothing; the Cover buttons follow their row's Available.
 */
export function paintFigures(figures, root = document) {
  const cells = cellsFromFigures(figures);
  const byKey = new Map();
  root.querySelectorAll('[data-budget-cell]').forEach((el) => byKey.set(el.dataset.budgetCell, el));
  root.querySelectorAll('.budget-row-checkbox').forEach((cb) => {
    const cell = cells[`row:${cb.dataset.categoryId}:budgeted`];
    // Keeps the Auto-Assign "this will overwrite N amounts" count honest.
    if (cell) cb.dataset.budgeted = cell.value;
  });

  Object.entries(cells).forEach(([key, cell]) => {
    const el = byKey.get(key);
    if (!el || cell.data) return;
    // A badge that only shows while there is something to count ("N overspent").
    if (cell.hidden !== undefined) el.hidden = cell.hidden;
    if (cell.width !== undefined) {
      paintMeter(el, cell);
      return;
    }
    if (el.textContent.trim() === cell.value) return;
    el.textContent = cell.value;
    if (cell.toned) {
      el.classList.toggle('text-error', cell.tone === 'neg');
      el.classList.toggle('text-success', cell.tone === 'pos');
      // Income budgeted but not received yet: neutral, not a shortfall (apps/budget/display.py).
      el.classList.toggle('text-base-content/70', cell.tone === 'expected');
    }
    flash(el);
  });

  const available = new Map();
  figures.sections.forEach((section) =>
    section.groups.forEach((group) =>
      group.rows.forEach((row) => available.set(String(row.categoryId), row.available)),
    ),
  );
  // The Cover button only makes sense while its row is overspent.
  root.querySelectorAll('[data-cover]').forEach((btn) => {
    const value = available.get(btn.dataset.categoryId);
    if (value !== undefined) btn.hidden = Number(value) >= 0;
  });
}

/** Every row of `figures`, by category id (a string, as the DOM's data attributes are). */
export function rowsById(figures) {
  const rows = new Map();
  figures.sections.forEach((section) =>
    section.groups.forEach((group) => group.rows.forEach((row) => rows.set(String(row.categoryId), row))),
  );
  return rows;
}

// ---------------------------------------------------------------------------
// Another month into the same markup
// ---------------------------------------------------------------------------

/** The table's structure as `figures` describe it: sections, groups (by name), rows (by id), in order. */
function figuresShape(figures) {
  if (!figures.hasCategories) return '';
  return figures.sections
    .map((section) => {
      const groups = section.groups.map((group) =>
        [group.hidden ? '~hidden' : group.name, ...group.rows.map((row) => row.categoryId)].join(','),
      );
      return `${section.key}:${groups.join('|')}`;
    })
    .join(';');
}

/** The same, read off the markup on screen. */
function domShape(root) {
  return Array.from(root.querySelectorAll('[data-budget-panel]'))
    .map((panel) => {
      const groups = [];
      panel.querySelectorAll('tbody > tr').forEach((tr) => {
        const kind = tr.dataset.testid;
        if (kind === 'budget-hidden-group') groups.push(['~hidden']);
        else if (kind === 'budget-group-header') groups.push([tr.children[1]?.textContent.trim() ?? '']);
        else {
          const form = tr.querySelector('form[data-budget-autosave]');
          if (form && groups.length) groups[groups.length - 1].push(form.dataset.categoryId);
        }
      });
      return `${panel.dataset.budgetPanel}:${groups.map((group) => group.join(',')).join('|')}`;
    })
    .join(';');
}

/** Whether `figures` fit the markup in `root` row for row, so they can be painted in place. */
export function sameStructure(figures, root) {
  const goalOption = root.querySelector('[data-cover-goal-option]');
  return figuresShape(figures) === domShape(root) && Boolean(goalOption);
}

/**
 * Turn the markup in `root` (the `#budget-swap` region) into `figures.month`'s:
 * every month the markup carries (data attributes, hidden form fields, links,
 * month names), every amount field, every Actual, then every figure. Only for
 * figures `sameStructure` accepts. Fires `budget:month-changed` once done.
 */
export function applyMonth(figures, root) {
  const from = root.dataset.budgetMonth;
  const fromEnd = root.dataset.budgetEnd;
  const to = pageMonth(figures.month);
  const toEnd = monthEnd(figures.month);

  root.querySelectorAll('[data-month]').forEach((el) => {
    el.dataset.month = to;
  });
  root
    .querySelectorAll('input[type="hidden"][name="month"], input[type="hidden"][name="budget_month"]')
    .forEach((input) => {
      input.value = to;
    });
  if (from && fromEnd) {
    root.querySelectorAll('a[href]').forEach((link) => {
      const href = link.getAttribute('href');
      const next = href.split(from).join(to).split(fromEnd).join(toEnd);
      if (next !== href) link.setAttribute('href', next);
    });
  }
  const name = monthName(figures.month);
  root.querySelectorAll('[data-budget-month-name]').forEach((el) => {
    el.textContent = name;
  });

  const rows = rowsById(figures);
  root.querySelectorAll('form[data-budget-autosave]').forEach((form) => {
    const row = rows.get(form.dataset.categoryId);
    const input = form.querySelector('input[name="budget_amount"]');
    // A month budgeted at zero shows an empty field, as the server renders it.
    if (row && input) input.value = Number(row.budgeted) ? row.budgeted : '';
  });
  root.querySelectorAll('[data-actual-tooltip]').forEach((el) => {
    const row = rows.get(el.dataset.categoryId);
    if (row) el.dataset.amount = row.actual;
  });

  const goalOption = root.querySelector('[data-cover-goal-option]');
  if (goalOption) goalOption.hidden = !figures.coverGoals.length;

  root.dataset.budgetMonth = to;
  root.dataset.budgetEnd = toEnd;
  paintFigures(figures, root);
  document.dispatchEvent(new CustomEvent('budget:month-changed', { detail: { month: to, figures, root } }));
}
