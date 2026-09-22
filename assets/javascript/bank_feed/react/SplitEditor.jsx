import React from 'react';

import Combobox from '../../common/Combobox';
import Icon from '../../common/Icon';
import { formatMoney } from '../../common/amount';

/* globals gettext, interpolate */

export const MIN_LEGS = 2;
export const MAX_LEGS = 20;

/**
 * The leg table of a split transaction.
 *
 * Presentational: the modal owns the legs and the totals, so this component can
 * be dropped into categorize mode later without moving state around.
 *
 * `legs` are `{ key, category, amount }`, where `amount` is the raw string the
 * user typed -- parsed only on save, so a half-typed "-" or "1." never snaps
 * back under the cursor.
 */
const SplitEditor = ({
  legs,
  categoryOptions,
  total,
  legSum,
  remaining,
  isBalanced,
  disabled = false,
  onChangeLeg,
  onAddLeg,
  onRemoveLeg,
  onAssignRemainder,
  onRemoveSplit,
}) => {
  const canRemoveLeg = legs.length > MIN_LEGS;
  const atMax = legs.length >= MAX_LEGS;

  return (
    <div className="flex flex-col gap-2" data-testid="split-editor">
      <div className="flex items-center justify-between">
        <span className="label-text text-sm text-base-content/70">{gettext('Categories')}</span>
        <button
          type="button"
          className="btn btn-ghost btn-xs"
          onClick={onRemoveSplit}
          disabled={disabled}
          data-testid="remove-split-btn"
        >
          {gettext('Remove split')}
        </button>
      </div>

      <div className="flex flex-col gap-2">
        {legs.map((leg, index) => (
          <div className="flex items-start gap-2" key={leg.key}>
            <div className="min-w-0 flex-1">
              <Combobox
                value={leg.category}
                onChange={(next) => onChangeLeg(index, { category: next })}
                options={categoryOptions}
                getGroup={(option) => option.groupLabel}
                disabled={disabled}
                placeholder={gettext('Choose a category')}
                testId={`split-category-${index}`}
              />
            </div>
            <label className="input input-bordered flex w-32 shrink-0 items-center gap-1">
              <span className="text-base-content/70">$</span>
              <input
                type="text"
                inputMode="decimal"
                className="w-full text-right font-mono"
                value={leg.amount}
                onChange={(e) => onChangeLeg(index, { amount: e.target.value })}
                disabled={disabled}
                aria-label={interpolate(gettext('Amount for split %s'), [index + 1])}
                data-testid={`split-amount-${index}`}
              />
            </label>
            <button
              type="button"
              className="btn btn-ghost btn-sm shrink-0"
              onClick={() => onRemoveLeg(index)}
              disabled={disabled || !canRemoveLeg}
              title={
                canRemoveLeg
                  ? gettext('Remove this category')
                  : gettext('A split needs at least two categories. Use Remove split instead.')
              }
              aria-label={interpolate(gettext('Remove split %s'), [index + 1])}
              data-testid={`split-remove-${index}`}
            >
              <Icon name="times" className="h-4 w-4" />
            </button>
          </div>
        ))}
      </div>

      <div>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={onAddLeg}
          disabled={disabled || atMax}
          title={atMax ? interpolate(gettext('A split cannot have more than %s categories.'), [MAX_LEGS]) : ''}
          data-testid="split-add-btn"
        >
          {gettext('+ Add a category')}
        </button>
      </div>

      <dl className="mt-1 flex flex-col gap-1 border-t border-base-300 pt-2 text-sm">
        <div className="flex justify-between">
          <dt className="text-base-content/70">{gettext('Transaction total')}</dt>
          <dd className="money" data-testid="split-total">
            {formatMoney(total)}
          </dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-base-content/70">{gettext('Assigned')}</dt>
          <dd className="money" data-testid="split-assigned">
            {formatMoney(legSum)}
          </dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-base-content/70">{gettext('Remaining')}</dt>
          <dd className={`money ${isBalanced ? 'text-success' : 'text-error'}`}>
            {isBalanced ? (
              <span data-testid="split-remaining">
                {formatMoney(0)} <Icon name="check" className="inline-block h-4 w-4" />
              </span>
            ) : (
              // Clicking the shortfall drops it into a leg -- the most-used
              // action in any split editor, and it saves reaching for a
              // calculator when apportioning an awkward total.
              <button
                type="button"
                className="link link-error"
                onClick={onAssignRemainder}
                disabled={disabled}
                title={gettext('Assign the rest to the last category')}
                data-testid="split-remaining"
              >
                {formatMoney(remaining)}
              </button>
            )}
          </dd>
        </div>
      </dl>
    </div>
  );
};

export default SplitEditor;
