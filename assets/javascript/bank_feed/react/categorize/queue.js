import { accountKind } from '../../../common/accountKind';
import { directionOf } from '../../categoryOrder';

/**
 * Categorize Mode's queue, as plain data. Pure: no React, no requests.
 *
 * A *unit* is what one pick files: a group from `feed/categorize_queue/` --
 * the uncategorized rows of one account, direction and merchant -- as
 * `{key, ids, suggestions, confident}`, its ids newest first. The card shows
 * the first id's row (the *lead*).
 */

/** A feed row's BankTransaction id: what the queue, the suggestions and every write key on. */
export function rowId(row) {
  return row?.imported_transaction_id ?? row?.id ?? null;
}

/** `row`'s signed amount: positive = money out (the books' convention). */
export function signedAmount(row) {
  return (parseFloat(row?.outflow) || 0) - (parseFloat(row?.inflow) || 0);
}

/**
 * The server's groups joined to the rows the feed list returned. A group id the
 * list did not return (a row filed elsewhere in between) is dropped, and a row
 * no group names gets a unit of its own, after the rest.
 */
export function buildUnits(groups, rowsById) {
  const seen = new Set();
  const units = [];
  (groups || []).forEach((group) => {
    const ids = group.ids.filter((id) => rowsById.has(id) && !seen.has(id));
    ids.forEach((id) => seen.add(id));
    if (ids.length) units.push({ ...group, ids });
  });
  rowsById.forEach((_row, id) => {
    if (!seen.has(id)) units.push({ key: `row:${id}`, ids: [id], suggestions: [], confident: false });
  });
  return units;
}

/** The ids a pick on `unit` files: all of them but the ones unticked in review. */
export function includedIds(unit, excluded) {
  const out = excluded?.[unit.key];
  return out ? unit.ids.filter((id) => !out.has(id)) : unit.ids;
}

/**
 * After a pick on `unit`, what is left of it: the unticked rows, as a unit of
 * their own (the same suggestions, no longer confident -- they were held back
 * for a reason), or null.
 */
export function remainderOf(unit, excluded) {
  const out = excluded?.[unit.key];
  if (!out || out.size === 0) return null;
  const ids = unit.ids.filter((id) => out.has(id));
  return ids.length ? { ...unit, key: `${unit.key}~rest`, ids, confident: false } : null;
}

/** Units with ids in `ids` taken out of them; units left empty are dropped. */
export function withoutIds(units, ids) {
  const drop = ids instanceof Set ? ids : new Set(ids);
  return units
    .map((u) => (u.ids.some((id) => drop.has(id)) ? { ...u, ids: u.ids.filter((id) => !drop.has(id)) } : u))
    .filter((u) => u.ids.length > 0);
}

/** Sum of the absolute amounts of `ids`. */
export function totalOf(ids, rowsById) {
  return ids.reduce((sum, id) => sum + Math.abs(signedAmount(rowsById.get(id))), 0);
}

/** How many rows are in `units`. */
export const countOf = (units) => units.reduce((n, u) => n + u.ids.length, 0);

// The first few picks of a session say little about pace; until then, this.
const DEFAULT_SECONDS_PER_UNIT = 5;
// A pause (a phone call, a long look at a statement) is not the pace either.
const MAX_SECONDS_PER_UNIT = 60;

/** Seconds per pick so far, from the times of the picks (ms), or the default. */
export function secondsPerUnit(pickTimes) {
  if (pickTimes.length < 3) return DEFAULT_SECONDS_PER_UNIT;
  const recent = pickTimes.slice(-11);
  const gaps = recent.slice(1).map((t, i) => Math.min((t - recent[i]) / 1000, MAX_SECONDS_PER_UNIT));
  return gaps.reduce((a, b) => a + b, 0) / gaps.length;
}

/** Whole minutes left for `unitsLeft` picks at `secondsEach` (at least 1 while any are left). */
export function minutesLeft(unitsLeft, secondsEach) {
  if (unitsLeft <= 0) return 0;
  return Math.max(1, Math.round((unitsLeft * secondsEach) / 60));
}

/** How many shortcut chips the picker shows (keys 1-9). */
export const CHIP_COUNT = 9;

/**
 * The shortcut chips for `row`: its suggestions first, then the categories used
 * most for money going this way (`usage`), up to `CHIP_COUNT`. Never the row's
 * own feed account. `[{account, suggestion|null}]`.
 */
export function chipsFor(row, suggestions, accounts, usage) {
  const feedAccountId = row?.account?.id ?? null;
  const byId = new Map(accounts.map((a) => [a.id, a]));
  const chips = [];
  const used = new Set();
  suggestions.forEach((s) => {
    const account = byId.get(s.category_id);
    if (!account || used.has(account.id)) return;
    used.add(account.id);
    chips.push({ account, suggestion: s });
  });
  const key = directionOf(row) === 'out' ? 'outflow' : 'inflow';
  accounts
    .filter((a) => a.id !== feedAccountId && !used.has(a.id) && (usage[a.id]?.[key] || 0) > 0)
    .sort((a, b) => (usage[b.id][key] || 0) - (usage[a.id][key] || 0) || a.name.localeCompare(b.name))
    .slice(0, Math.max(0, CHIP_COUNT - chips.length))
    .forEach((account) => chips.push({ account, suggestion: null }));
  return chips;
}

/** `YYYY-MM` of a row's posted date. */
export const monthOf = (row) => String(row?.posted_date || '').slice(0, 7);

/**
 * `{categoryId: {budgeted, actual, available, kind}}` from the budget month API's
 * body (sections -> groups -> rows), as numbers.
 */
export function figuresFromBudgetMonth(body) {
  const out = {};
  (body?.sections || []).forEach((section) => {
    (section.groups || []).forEach((group) => {
      (group.rows || []).forEach((r) => {
        out[r.category_id] = {
          budgeted: parseFloat(r.budgeted) || 0,
          actual: parseFloat(r.actual) || 0,
          available: parseFloat(r.available) || 0,
          kind: section.key,
        };
      });
    });
  });
  return out;
}

/**
 * How filing `amount` (signed, positive = money out) to `account` moves its
 * figures: spending adds to an expense's actual and takes from what is left;
 * income adds to an income category's actual and to its available. `null` for
 * anything else (a transfer, a goal: goals keep their own `goal_left`).
 */
export function applyToFigures(figure, account, amount) {
  if (!figure) return null;
  const kind = accountKind(account);
  if (kind === 'expense') return { ...figure, actual: figure.actual + amount, available: figure.available - amount };
  if (kind === 'income') return { ...figure, actual: figure.actual - amount, available: figure.available - amount };
  return null;
}
