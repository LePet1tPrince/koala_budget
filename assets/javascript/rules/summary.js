/* globals gettext, interpolate */

/**
 * A rule in one plain line: "Money out · Chequing · description contains “insurance” → Car Insurance".
 * The same words on the Rules page and in the feed's popovers.
 */

const OPS = {
  contains: () => gettext('contains'),
  not_contains: () => gettext("doesn't contain"),
  equals: () => gettext('is exactly'),
  gt: () => gettext('is more than'),
  lt: () => gettext('is less than'),
  between: () => gettext('is between'),
};

const FIELDS = {
  payee: () => gettext('payee'),
  description: () => gettext('description'),
  amount: () => gettext('amount'),
};

export const opLabel = (op) => (OPS[op] ? OPS[op]() : op);
export const fieldLabel = (field) => (FIELDS[field] ? FIELDS[field]() : field);

export const TEXT_OPS = ['contains', 'not_contains', 'equals'];
export const AMOUNT_OPS = ['gt', 'lt', 'equals', 'between'];

export function conditionText(condition) {
  const { field, op, value } = condition;
  if (field === 'amount') {
    const shown =
      op === 'between' && Array.isArray(value)
        ? interpolate(gettext('%s and %s'), [`$${value[0]}`, `$${value[1]}`])
        : `$${value}`;
    return `${fieldLabel(field)} ${opLabel(op)} ${shown}`;
  }
  return `${fieldLabel(field)} ${opLabel(op)} “${value}”`;
}

export function directionText(direction) {
  if (direction === 'out') return gettext('Money out');
  if (direction === 'in') return gettext('Money in');
  return '';
}

export function actionText(rule, accountsById) {
  const parts = [];
  if (rule.action === 'category') {
    parts.push(rule.category_name || accountsById?.get(rule.category)?.name || gettext('(missing category)'));
  } else if (rule.action === 'split') {
    const names = (rule.splits || []).map(
      (s) => `${accountsById?.get(Number(s.category))?.name ?? '?'} ${Number(s.percent)}%`,
    );
    parts.push(interpolate(gettext('Split: %s'), [names.join(', ')]));
  }
  if (rule.payee_name) parts.push(interpolate(gettext('payee “%s”'), [rule.payee_name]));
  if (rule.description) parts.push(interpolate(gettext('description “%s”'), [rule.description]));
  return parts.join(' · ');
}

/** "When … → then …", for a saved rule or a draft. */
export function ruleSummary(rule, { accountsById, feedAccountsById } = {}) {
  const when = [];
  const direction = directionText(rule.direction);
  if (direction) when.push(direction);
  if (rule.accounts?.length) {
    when.push(rule.accounts.map((id) => feedAccountsById?.get(Number(id))?.name ?? '?').join(', '));
  }
  const joiner = rule.match === 'any' ? ` ${gettext('or')} ` : ` ${gettext('and')} `;
  if (rule.conditions?.length) when.push(rule.conditions.map(conditionText).join(joiner));
  return `${when.join(' · ')} → ${actionText(rule, accountsById)}`;
}
