/* globals gettext */

import React from 'react';

import Icon from '../common/Icon';

/**
 * Which savings categories become goals.
 *
 * In YNAB, "move $500 to the TFSA and record it as budgeted" is one transaction
 * with a savings category on it. In double-entry that movement is asset to asset,
 * so the category cannot be a spending category -- but it maps exactly onto a goal,
 * which is what Koala Budget has for money set aside on purpose.
 *
 * Only categories with a decision worth making are listed: the ones funded by
 * transfers, and the odd one out (`Investment Gain/Loss`) that is a valuation
 * change rather than either.
 */
const money = (value) =>
  `$${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const KINDS = [
  { value: 'goal', label: gettext('A savings goal') },
  { value: 'expense', label: gettext('A spending category') },
  { value: 'investment', label: gettext('Investment growth or loss') },
];

const Step4Goals = ({ categories, choices, onChange }) => {
  if (categories.length === 0) {
    return (
      <div className="space-y-4">
        <h2 className="text-xl font-semibold tracking-tight">{gettext('Savings')}</h2>
        <p className="text-base-content/70">
          {gettext(
            'Nothing in this export looks like money you were setting aside, so there is nothing to decide here.',
          )}
        </p>
      </div>
    );
  }

  const choiceFor = (category) => choices[category.key] || {};
  const update = (category, patch) => onChange({ ...choices, [category.key]: { ...choiceFor(category), ...patch } });

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-semibold tracking-tight">{gettext('Money you were setting aside')}</h2>
        <p className="mt-2 max-w-prose text-base-content/70">
          {gettext(
            'These categories were funded by moving money between your own accounts. We can carry them over as savings goals, with everything you have already put in.',
          )}
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2" data-testid="ynab-goals-grid">
        {categories.map((category) => {
          const choice = choiceFor(category);
          const kind = choice.kind ?? category.kind;
          return (
            <div
              key={category.key}
              className="app-card space-y-3"
              data-testid="ynab-goal-card"
              data-category={category.name}
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <input
                    type="text"
                    className="input input-bordered input-sm w-full"
                    value={choice.name ?? category.name}
                    onChange={(e) => update(category, { name: e.target.value })}
                    aria-label={gettext('Name')}
                  />
                  <p className="mt-1 text-xs text-base-content/70">{category.group}</p>
                </div>
                {kind === 'goal' && (
                  <span className="badge badge-success badge-soft whitespace-nowrap">
                    {money(category.saved)} {gettext('saved')}
                  </span>
                )}
              </div>

              <select
                className="select select-bordered select-sm w-full"
                value={kind}
                onChange={(e) => update(category, { kind: e.target.value })}
                aria-label={gettext('Import as')}
              >
                {KINDS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>

              <p className="text-xs text-base-content/70">
                {category.transfer_legs > 0
                  ? gettext('{n} transfers into this category').replace('{n}', category.transfer_legs.toLocaleString())
                  : gettext('No transfers — this one was only ever spent from')}
                {category.plain_rows > 0 &&
                  ` · ${gettext('{n} payments out of it').replace('{n}', category.plain_rows.toLocaleString())}`}
              </p>
            </div>
          );
        })}
      </div>

      <p className="flex items-start gap-2 text-sm text-base-content/70">
        <Icon name="info" className="mt-0.5 h-4 w-4 shrink-0" />
        {gettext(
          'A YNAB export carries no savings targets, so each goal starts with its target set to what you have already saved. Raise it on the Goals page for anything you are still saving for.',
        )}
      </p>
    </div>
  );
};

export default Step4Goals;
