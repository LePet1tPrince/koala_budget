/* globals gettext, interpolate */

/**
 * Plain-language summaries of a rule, shared by the rules list and the editor's
 * preview line. Kept here so the two never word the same rule differently.
 */

export const MATCH_KINDS = [
  { value: '', label: () => gettext('any') },
  { value: 'equals', label: () => gettext('is') },
  { value: 'contains', label: () => gettext('contains') },
  { value: 'words', label: () => gettext('has the words') },
];

export const DIRECTIONS = [
  { value: 'any', label: () => gettext('Money in or out') },
  { value: 'outflow', label: () => gettext('Money out') },
  { value: 'inflow', label: () => gettext('Money in') },
];

const kindLabel = (kind) => MATCH_KINDS.find((k) => k.value === kind)?.label() ?? kind;

const money = (value) => {
  const n = Number(value);
  return Number.isFinite(n) ? `$${n.toFixed(2)}` : value;
};

/** "Payee is “Blue Bottle” · money out · $4.50–$9.00 · in Visa" */
export function conditionText(rule) {
  const parts = [];
  if (rule.payee_match && rule.payee_value) {
    parts.push(interpolate(gettext('Payee %s “%s”'), [kindLabel(rule.payee_match), rule.payee_value]));
  }
  if (rule.description_match && rule.description_value) {
    parts.push(
      interpolate(gettext('Description %s “%s”'), [kindLabel(rule.description_match), rule.description_value]),
    );
  }
  const low = rule.amount_min;
  const high = rule.amount_max;
  const hasLow = low !== null && low !== undefined && low !== '';
  const hasHigh = high !== null && high !== undefined && high !== '';
  if (hasLow && hasHigh && Number(low) === Number(high)) parts.push(interpolate(gettext('exactly %s'), [money(low)]));
  else if (hasLow && hasHigh) parts.push(`${money(low)}–${money(high)}`);
  else if (hasLow) parts.push(interpolate(gettext('%s or more'), [money(low)]));
  else if (hasHigh) parts.push(interpolate(gettext('up to %s'), [money(high)]));
  if (rule.direction === 'outflow') parts.push(gettext('money out'));
  if (rule.direction === 'inflow') parts.push(gettext('money in'));
  if (rule.account_name) parts.push(interpolate(gettext('in %s'), [rule.account_name]));
  return parts.join(' · ');
}

/** "Coffee · rename payee to Blue Bottle" */
export function actionText(rule) {
  return [rule.category_name || gettext('No category'), ...(rule.action_summary || [])].join(' · ');
}
