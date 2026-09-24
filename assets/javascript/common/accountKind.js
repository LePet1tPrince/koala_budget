/* globals gettext */

/**
 * How a picker presents an account.
 *
 * The equity account type is stored as 'goal', so it covers both real goals and
 * plain equity (opening balances). Goal-ness comes from the server's `is_goal`
 * (the Goal relation), never from the type: goals show under "Goals", the rest
 * of the equity type under "Equity".
 */
export function accountKind(account) {
  const type = account.account_type || account.accountType;
  if (type !== 'goal') return type;
  return account.is_goal || account.isGoal ? 'goal' : 'equity';
}

export const ACCOUNT_KIND_LABELS = {
  asset: gettext('Asset'),
  liability: gettext('Liability'),
  income: gettext('Income'),
  expense: gettext('Expense'),
  goal: gettext('Goal'),
  equity: gettext('Equity'),
};

/** System accounts are bookkeeping, never a category; the server refuses them too. */
export function pickableAccounts(accounts) {
  return (accounts || []).filter((account) => !(account.is_system || account.isSystem));
}

function formatMoney(value) {
  const n = Number(value);
  const abs = Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${n < 0 ? '−' : ''}$${abs}`;
}

/** "$600 left" for a goal account, or null for any other account. */
export function goalLeftLabel(account) {
  const left = account.goal_left ?? account.goalLeft;
  if (left === null || left === undefined) return null;
  return `${formatMoney(left)} ${gettext('left')}`;
}

/**
 * The non-blocking hint when spending more than a goal holds: "Car will go to
 * −$1,500 — that's fine, it's carried". `amount` is the outflow categorized to
 * the goal (positive = money spent from it). Null when there is nothing to say.
 */
export function goalOverspendHint(account, amount) {
  if (!account || accountKind(account) !== 'goal') return null;
  const left = Number(account.goal_left ?? account.goalLeft);
  const spend = Number(amount);
  if (!Number.isFinite(left) || !Number.isFinite(spend) || spend <= 0 || spend <= left) return null;
  const name = account.name.replace(/^Goal: /, '');
  return `${name} ${gettext('will go to')} ${formatMoney(left - spend)} — ${gettext("that's fine, it's carried")}`;
}
