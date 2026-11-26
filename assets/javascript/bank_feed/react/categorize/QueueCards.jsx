/* globals gettext, interpolate, ngettext */
import React, { useState } from 'react';

import Combobox from '../../../common/Combobox';
import Icon from '../../../common/Icon';
import { formatMoney } from '../../../common/amount';
import TransferMatchPanel from '../TransferMatchPanel';
import { includedIds, signedAmount, totalOf } from './queue';
import { useSwipe } from './useSwipe';

// Cards drawn behind the top one: enough to read as a stack.
const STACK_DEPTH = 3;

function Amount({ value, className = '' }) {
  const out = value > 0;
  return (
    <span className={`${out ? 'text-error' : 'text-success'} ${className}`}>
      {out ? `-${formatMoney(value)}` : `+${formatMoney(-value)}`}
    </span>
  );
}

/**
 * The payee and description of the card on top, editable in place. Nothing is
 * written while you type: the draft is held by the parent and saved with the
 * category, so a card is never left renamed but uncategorized.
 */
function DetailsEditor({ values, dirty, appliesTo, payeeOptions, onChange, onRevert, onDone }) {
  const handleKeyDown = (e) => {
    if (e.key === 'Escape') {
      // Escape backs out of the edit, never out of the queue.
      e.stopPropagation();
      if (dirty) onRevert();
      else onDone();
      return;
    }
    if (e.key === 'Enter' && e.target.tagName === 'INPUT') {
      e.preventDefault();
      onDone();
    }
  };

  return (
    <div className="space-y-2" onKeyDown={handleKeyDown} data-testid="categorize-details-editor">
      <Combobox
        label={gettext('Payee')}
        value={values.payee}
        onChange={(v) => onChange('payee', v)}
        options={payeeOptions}
        freeText
        placeholder={gettext('Who was this with?')}
        testId="categorize-payee"
      />
      <label className="form-control w-full">
        <span className="label-text mb-1 block text-sm text-base-content/70">{gettext('Description')}</span>
        <input
          type="text"
          className="input input-bordered w-full"
          value={values.description}
          placeholder={gettext('What was it for?')}
          onChange={(e) => onChange('description', e.target.value)}
          data-testid="categorize-description"
        />
      </label>
      <div className="flex items-center justify-between gap-2 min-h-6">
        <span className="text-xs text-base-content/70">
          {dirty && (
            <span className="text-warning font-medium" data-testid="categorize-details-dirty">
              {appliesTo > 1
                ? interpolate(gettext('Saved on all %s when you pick a category'), [appliesTo])
                : gettext('Saved when you pick a category')}
            </span>
          )}
        </span>
        <span className="flex gap-1">
          {dirty && (
            <button
              type="button"
              onClick={onRevert}
              className="btn btn-ghost btn-xs"
              data-testid="categorize-details-revert"
            >
              {gettext('Revert')}
            </button>
          )}
          <button type="button" onClick={onDone} className="btn btn-ghost btn-xs" data-testid="categorize-details-done">
            {gettext('Done')}
          </button>
        </span>
      </div>
    </div>
  );
}

/** The rows of a group, each with a tick: unticked rows wait for a pick of their own. */
function GroupReview({ unit, rowsById, excluded, onToggle }) {
  const out = excluded?.[unit.key];
  return (
    <ul className="max-h-48 overflow-y-auto space-y-1 mt-2" data-testid="categorize-group-review">
      {unit.ids.map((id) => {
        const row = rowsById.get(id);
        const checked = !out?.has(id);
        return (
          <li key={id}>
            <label className="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-base-200 cursor-pointer text-sm">
              <input
                type="checkbox"
                className="checkbox checkbox-xs checkbox-primary"
                checked={checked}
                onChange={() => onToggle(unit.key, id)}
                data-testid={`categorize-group-row-${id}`}
              />
              <span className="flex-1 min-w-0 truncate">{row?.description || row?.merchant_name}</span>
              <span className="text-base-content/70 text-xs shrink-0">{row?.posted_date}</span>
              <Amount value={signedAmount(row)} className="text-xs font-semibold shrink-0" />
            </label>
          </li>
        );
      })}
    </ul>
  );
}

function TopCard({
  unit,
  rowsById,
  excluded,
  onToggleExcluded,
  details,
  detailsDirty,
  editing,
  setEditing,
  payeeOptions,
  onDetailChange,
  onDetailsRevert,
  transferMatch,
  onMatch,
  onDismissMatch,
  swipeHint,
}) {
  const [reviewing, setReviewing] = useState(false);
  const [showTransfer, setShowTransfer] = useState(false);
  const row = rowsById.get(unit.ids[0]);
  const ids = includedIds(unit, excluded);
  const group = unit.ids.length > 1;
  const amount = signedAmount(row);
  const title = details.payee || row.description || gettext('No description');

  return (
    <div className="card-body p-5 gap-0">
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs text-base-content/70 truncate" data-testid="categorize-card-account">
          {row.account?.name || gettext('Unknown account')} · {row.posted_date}
        </p>
        {group && (
          <span className="badge badge-primary badge-sm gap-1 shrink-0" data-testid="categorize-group-badge">
            <Icon name="layers" className="h-3 w-3" />
            {interpolate(gettext('%s like this'), [unit.ids.length])}
          </span>
        )}
      </div>

      <div className="mt-1">
        {editing ? (
          <DetailsEditor
            values={details}
            dirty={detailsDirty}
            appliesTo={ids.length}
            payeeOptions={payeeOptions}
            onChange={onDetailChange}
            onRevert={onDetailsRevert}
            onDone={() => setEditing(false)}
          />
        ) : (
          <button
            type="button"
            className="group w-full text-left"
            onClick={() => setEditing(true)}
            title={gettext('Edit the payee and description')}
            data-testid="categorize-edit-details"
          >
            <span className="flex items-center gap-2">
              <span className="font-bold text-xl truncate" data-testid="categorize-card-payee">
                {title}
              </span>
              <Icon name="pencil" className="h-3.5 w-3.5 shrink-0 text-base-content/40 group-hover:text-primary" />
              {detailsDirty && (
                <span className="badge badge-warning badge-xs" data-testid="categorize-details-dirty">
                  {gettext('edited')}
                </span>
              )}
            </span>
            {details.description && details.description !== title && (
              <span className="block text-sm text-base-content/70 truncate" data-testid="categorize-card-description">
                {details.description}
              </span>
            )}
          </button>
        )}
      </div>

      <div className="flex items-end justify-between mt-3 gap-2">
        <span className="text-sm text-base-content/70">
          {group &&
            interpolate(gettext('%s of %s selected · %s'), [
              ids.length,
              unit.ids.length,
              formatMoney(totalOf(ids, rowsById)),
            ])}
        </span>
        <Amount value={amount} className="text-3xl font-black tabular-nums" />
      </div>

      {group && (
        <div className="mt-2">
          <button
            type="button"
            className="btn btn-ghost btn-xs px-1"
            onClick={() => setReviewing((r) => !r)}
            aria-expanded={reviewing}
            data-testid="categorize-group-toggle"
          >
            {reviewing
              ? gettext('Hide the list')
              : interpolate(
                  ngettext(
                    'Filed with %s more like it — review',
                    'Filed with %s more like it — review',
                    unit.ids.length - 1,
                  ),
                  [unit.ids.length - 1],
                )}
          </button>
          {reviewing && <GroupReview unit={unit} rowsById={rowsById} excluded={excluded} onToggle={onToggleExcluded} />}
        </div>
      )}

      {transferMatch && (
        <div className="mt-3" data-testid="categorize-transfer-hint">
          {showTransfer ? (
            <TransferMatchPanel
              id={`categorize-transfer-${unit.key}`}
              match={transferMatch}
              onMatch={onMatch}
              onDismiss={onDismissMatch}
              onGoTo={() => {}}
              onClose={() => setShowTransfer(false)}
            />
          ) : (
            <button
              type="button"
              className="alert alert-warning alert-soft w-full py-2 text-sm text-left"
              onClick={() => setShowTransfer(true)}
              data-testid="categorize-transfer-open"
            >
              <Icon name="exchange" className="h-4 w-4" />
              {interpolate(gettext('Looks like a transfer also reported by %s — match?'), [
                transferMatch.other.account?.name || gettext('another account'),
              ])}
            </button>
          )}
        </div>
      )}

      {swipeHint && (
        <p className="sm:hidden mt-3 text-xs text-center text-base-content/70" data-testid="categorize-swipe-hint">
          {swipeHint}
        </p>
      )}
    </div>
  );
}

function BehindCard({ unit, rowsById, blank = false }) {
  const row = rowsById.get(unit.ids[0]);
  return (
    <div className={`card-body p-5 ${blank ? 'invisible' : ''}`}>
      <p className="text-xs text-base-content/70 truncate">{row?.account?.name}</p>
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-bold text-lg truncate">{row?.merchant_name || row?.description}</h3>
        <Amount value={signedAmount(row)} className="text-xl font-black" />
      </div>
    </div>
  );
}

/**
 * The stack: the current unit on top, the next few peeking out below it. On a
 * touch screen the top card is swiped: right files the first suggestion, left
 * skips, up opens the details.
 */
export default function QueueCards({
  units,
  topCardRef,
  reducedMotion,
  topSuggestionName,
  onSwipeRight,
  onSwipeLeft,
  onSwipeUp,
  swipeDisabled,
  ...topProps
}) {
  const { handlers, offset, leaning } = useSwipe({
    onRight: onSwipeRight,
    onLeft: onSwipeLeft,
    onUp: onSwipeUp,
    disabled: swipeDisabled,
  });
  const visible = units.slice(0, STACK_DEPTH + 1);
  const dragging = offset.x !== 0 || offset.y !== 0;
  const leanLabel = {
    right: topSuggestionName
      ? interpolate(gettext('File as %s'), [topSuggestionName])
      : gettext('No suggestion — pick below'),
    left: gettext('Skip'),
    up: gettext('Edit details'),
  }[leaning];
  const swipeHint = topSuggestionName
    ? interpolate(gettext('Swipe right to file as %s · left to skip'), [topSuggestionName])
    : gettext('Swipe left to skip');

  return (
    <div className="relative w-full" data-testid="categorize-stack">
      {visible
        .slice()
        .reverse()
        .map((unit) => {
          const i = visible.indexOf(unit);
          const top = i === 0;
          const depth = Math.min(i, STACK_DEPTH);
          const style = top
            ? {
                transform: dragging
                  ? `translate(${offset.x}px, ${offset.y}px) rotate(${reducedMotion ? 0 : offset.x / 20}deg)`
                  : undefined,
                transition: dragging ? 'none' : undefined,
                touchAction: topProps.editing ? 'auto' : 'none',
                zIndex: 10,
              }
            : {
                // Bottom-anchored, so each card's lower edge shows below the one in
                // front of it however tall the top card is.
                position: 'absolute',
                left: 0,
                right: 0,
                bottom: `${(visible.length - 1 - depth) * 10}px`,
                transform: `scale(${1 - depth * 0.04})`,
                transformOrigin: 'bottom center',
                zIndex: 10 - depth,
              };
          return (
            <div
              key={unit.key}
              className={`${top ? 'relative' : ''} transition-transform duration-200 ease-out`}
              style={style}
              aria-hidden={top ? undefined : 'true'}
              {...(top ? handlers : {})}
            >
              <div
                ref={top ? topCardRef : null}
                className={`card bg-base-100 border border-base-300 ${top ? 'shadow-xl ring-2 ring-primary/30' : 'shadow'}`}
                data-testid={top ? 'categorize-card' : undefined}
              >
                {top ? (
                  <TopCard unit={unit} swipeHint={swipeHint} {...topProps} />
                ) : (
                  // Deeper cards are edges only: their text would show through mid-swipe.
                  <BehindCard unit={unit} rowsById={topProps.rowsById} blank={depth > 1} />
                )}
                {top && leanLabel && (
                  <div
                    className={`absolute inset-x-0 top-3 mx-auto w-max badge badge-lg ${
                      leaning === 'right' ? (topSuggestionName ? 'badge-success' : 'badge-ghost') : 'badge-neutral'
                    }`}
                  >
                    {leanLabel}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      {/* Room for the cards peeking out below the top one. */}
      <div style={{ height: `${Math.max(0, visible.length - 1) * 10}px` }} />
    </div>
  );
}
