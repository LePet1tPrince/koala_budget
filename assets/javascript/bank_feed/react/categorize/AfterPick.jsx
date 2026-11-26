/* globals gettext, interpolate, ngettext */
import React from 'react';

import Icon from '../../../common/Icon';
import { accountKind, goalLeftLabel } from '../../../common/accountKind';
import { formatMoney } from '../../../common/amount';
import { UNDO_KEY } from './CategoryPicker';

function monthName(month) {
  const [year, m] = String(month).split('-').map(Number);
  if (!year || !m) return '';
  return new Intl.DateTimeFormat(document.documentElement.lang || undefined, {
    month: 'long',
    timeZone: 'UTC',
  }).format(new Date(Date.UTC(year, m - 1, 1)));
}

/** What the last pick did to its category: spending against the budget, a goal's balance, a transfer. */
function Impact({ impact }) {
  const { account, figure, month } = impact;
  const kind = accountKind(account);
  let text;
  let meter = null;
  if (kind === 'expense' && figure) {
    const when = monthName(month);
    if (figure.budgeted > 0) {
      text = interpolate(gettext('%s of %s spent in %s · %s'), [
        formatMoney(figure.actual),
        formatMoney(figure.budgeted),
        when,
        figure.available < 0
          ? interpolate(gettext('%s over'), [formatMoney(-figure.available)])
          : interpolate(gettext('%s left'), [formatMoney(figure.available)]),
      ]);
      meter = {
        value: Math.min(100, Math.max(0, (figure.actual / figure.budgeted) * 100)),
        over: figure.available < 0,
      };
    } else {
      text = interpolate(gettext('%s spent in %s'), [formatMoney(figure.actual), when]);
    }
  } else if (kind === 'income' && figure) {
    text = interpolate(gettext('%s received in %s'), [formatMoney(figure.actual), monthName(month)]);
  } else if (kind === 'goal') {
    text = goalLeftLabel(account);
  } else if (kind === 'asset' || kind === 'liability') {
    text = gettext('Recorded as a transfer');
  }
  if (!text) return null;
  return (
    <div className="w-full" data-testid="categorize-impact">
      <p className="text-sm">
        <span className="font-semibold">{account.name}</span>
        <span className="text-base-content/70"> · {text}</span>
      </p>
      {meter && (
        <div className="mt-1 h-1.5 w-full rounded-full bg-base-300 overflow-hidden" aria-hidden="true">
          <div
            className={`h-full rounded-full transition-all duration-500 ${meter.over ? 'bg-error' : 'bg-success'}`}
            style={{ width: `${meter.value}%` }}
          />
        </div>
      )}
    </div>
  );
}

/**
 * Under the stack after a pick: Undo for it, what it did to the category, and
 * -- when filing it by hand says a rule would help -- the offer to make one.
 */
export default function AfterPick({
  last,
  impact,
  ruleOffer,
  undoing,
  onUndo,
  onCreateRule,
  onCustomizeRule,
  onDeclineRule,
}) {
  if (!last && !ruleOffer) return null;
  return (
    <div className="w-full space-y-2" data-testid="categorize-after-pick">
      {last && (
        <div className="rounded-box bg-base-100 border border-base-300 px-3 py-2 flex items-start gap-3">
          <Icon name="check-circle" className="h-4 w-4 mt-0.5 text-success shrink-0" />
          <div className="flex-1 min-w-0 space-y-1">
            <p className="text-sm" data-testid="categorize-last">
              {interpolate(ngettext('Filed %s transaction as %s', 'Filed %s transactions as %s', last.count), [
                last.count,
                last.label,
              ])}
            </p>
            {impact && <Impact impact={impact} />}
          </div>
          <button
            type="button"
            className="btn btn-ghost btn-xs gap-1 shrink-0"
            onClick={onUndo}
            disabled={undoing}
            data-testid="categorize-undo"
          >
            {undoing ? (
              <span className="loading loading-spinner loading-xs" />
            ) : (
              <Icon name="rotate-ccw" className="h-3.5 w-3.5" />
            )}
            {gettext('Undo')}
            <kbd className="kbd kbd-xs hidden sm:inline-flex">{UNDO_KEY} z</kbd>
          </button>
        </div>
      )}
      {ruleOffer && (
        <div
          className="rounded-box bg-primary/5 border border-primary/30 px-3 py-2"
          data-testid="categorize-rule-offer"
        >
          <p className="text-sm">
            <Icon name="wand-magic-sparkles" className="inline-block h-4 w-4 mr-1 text-primary" />
            {interpolate(gettext('Always suggest %s for “%s”?'), [
              ruleOffer.draft.category_name,
              ruleOffer.draft.conditions[0]?.value ?? '',
            ])}
            {ruleOffer.coverage > 0 && (
              <span className="text-base-content/70">
                {' '}
                {interpolate(
                  ngettext('It matches %s transaction.', 'It matches %s transactions.', ruleOffer.coverage),
                  [ruleOffer.coverage],
                )}
              </span>
            )}
          </p>
          <div className="mt-1 flex flex-wrap gap-1">
            <button
              type="button"
              className="btn btn-primary btn-xs"
              onClick={onCreateRule}
              data-testid="categorize-rule-create"
            >
              {gettext('Create rule')}
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-xs"
              onClick={onCustomizeRule}
              data-testid="categorize-rule-customize"
            >
              {gettext('Customize')}
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-xs"
              onClick={onDeclineRule}
              data-testid="categorize-rule-decline"
            >
              {gettext('No')}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
