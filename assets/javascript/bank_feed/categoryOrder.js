import { accountKind } from '../common/accountKind';

/**
 * The order Categorize mode lists categories in, for one transaction.
 *
 * 1. Tier, by the transaction's direction. Money out is most often an expense,
 *    money in most often income; a transfer between your own accounts is the
 *    next most likely either way. What's left follows -- money out: income (a
 *    returned payment), then goals; money in: expenses (a refund), then goals --
 *    and equity (Reconciliation Adjustments, for opening balances) always last.
 *
 * 2. Within the transfer tier, the likelier side first. Money leaving a bank
 *    account is usually a card or loan payment, so liabilities lead; every other
 *    transfer (savings to chequing, a card payment arriving, a cash advance) is
 *    most often with another asset.
 *
 * 3. Within a tier, usage. `usage` counts how often each category was chosen in
 *    the last year (`services/category_usage.py`), for money out and money in
 *    separately. Use in this direction ranks first, use the other way breaks
 *    ties (a groceries refund still finds Groceries near the top), then the
 *    name. Groups follow their accounts: a group's score is the sum of its
 *    accounts', so the group you reach for most sits at the top of its tier.
 *
 * The transaction's own feed account is left out: categorizing it there would
 * be a transfer to itself.
 */

const TIERS = {
  out: ['expense', 'transfer', 'income', 'goal', 'equity'],
  in: ['income', 'transfer', 'expense', 'goal', 'equity'],
};

const tierOf = (kind) => (kind === 'asset' || kind === 'liability' ? 'transfer' : kind);

/** 0 for the likelier side of a transfer, 1 for the other. */
function transferSide(kind, feedKind, direction) {
  const liabilitiesFirst = feedKind === 'asset' && direction === 'out';
  if (kind === 'liability') return liabilitiesFirst ? 0 : 1;
  return liabilitiesFirst ? 1 : 0;
}

/** `'out'` or `'in'` for a feed row (`outflow`/`inflow` as strings or numbers). */
export function directionOf(transaction) {
  return parseFloat(transaction?.outflow) > 0 ? 'out' : 'in';
}

/** `{account_id: {outflow, inflow}}` from the pickers' `category_usage` list. */
export function usageById(categoryUsage) {
  const byId = {};
  (categoryUsage || []).forEach((u) => {
    byId[u.account_id] = { outflow: u.outflow || 0, inflow: u.inflow || 0 };
  });
  return byId;
}

/**
 * `accounts` as `[{name, accounts}]` groups in display order.
 *
 * @param {object[]} accounts - picker accounts (already filtered)
 * @param {object} options
 * @param {'out'|'in'} options.direction
 * @param {number|null} options.feedAccountId - the transaction's own account
 * @param {string} options.feedKind - its kind ('asset' or 'liability')
 * @param {object} options.usage - `usageById(...)`
 */
export function orderCategories(accounts, { direction, feedAccountId = null, feedKind = 'asset', usage = {} }) {
  const tiers = TIERS[direction] || TIERS.out;
  const same = direction === 'out' ? 'outflow' : 'inflow';
  const other = direction === 'out' ? 'inflow' : 'outflow';

  const rank = (account) => {
    const kind = accountKind(account);
    const tier = tiers.indexOf(tierOf(kind));
    const u = usage[account.id] || {};
    return {
      tier: tier === -1 ? tiers.length : tier,
      side: tierOf(kind) === 'transfer' ? transferSide(kind, feedKind, direction) : 0,
      same: u[same] || 0,
      other: u[other] || 0,
    };
  };

  // Accounts grouped under their account group, each group scored by its accounts.
  const groups = new Map();
  accounts.forEach((account) => {
    if (account.id === feedAccountId) return;
    const r = rank(account);
    const key = `${r.tier}|${r.side}|${account.account_group_name || 'Other'}`;
    if (!groups.has(key)) {
      groups.set(key, {
        name: account.account_group_name || 'Other',
        tier: r.tier,
        side: r.side,
        same: 0,
        other: 0,
        rows: [],
      });
    }
    const group = groups.get(key);
    group.same += r.same;
    group.other += r.other;
    group.rows.push({ account, ...r });
  });

  const byUse = (a, b) => b.same - a.same || b.other - a.other;
  return [...groups.values()]
    .sort((a, b) => a.tier - b.tier || a.side - b.side || byUse(a, b) || a.name.localeCompare(b.name))
    .map((group) => ({
      name: group.name,
      accounts: group.rows
        .sort((a, b) => byUse(a, b) || a.account.name.localeCompare(b.account.name))
        .map((r) => r.account),
    }));
}

/** `usage` with one more choice of `accountId` for money going `direction`. */
export function withUse(usage, accountId, direction, count = 1) {
  const key = direction === 'out' ? 'outflow' : 'inflow';
  const current = usage[accountId] || { outflow: 0, inflow: 0 };
  return { ...usage, [accountId]: { ...current, [key]: current[key] + count } };
}
