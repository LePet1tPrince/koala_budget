import React, { useEffect, useState } from 'react';
import Modal from '../../common/Modal';
import { formatCurrency } from '../../utilities/currency';
import { formatDate as formatDateUtc, formatDateForInput } from '../utils';
import RecurrenceFields, { recurrencePayload, recurrenceProblem } from './RecurrenceFields';

/* globals gettext, interpolate */

/** The modal's schedule state, prefilled from what the detector saw. */
const recurrenceFrom = (suggestion) => ({
  frequency: suggestion.frequency,
  interval: String(suggestion.interval),
  weekday: suggestion.weekday ?? null,
  dayOfMonth: suggestion.dayOfMonth ?? null,
  endDate: '',
});

/** A 'YYYY-MM-DD' string as the UTC-midnight Date the generated client serializes back to that day. */
const utcDay = (value) => (value ? new Date(`${value}T00:00:00Z`) : null);

/**
 * "Make recurring" for a detected pattern: confirm (or adjust) the schedule the
 * detector proposes. The latest occurrence becomes the schedule's first, so
 * nothing already in the feed is written again.
 *
 * Props: `suggestion` (a RecurringSuggestion, or null when closed), `client`
 * (BankFeedApi), `book`, `onClose`, `onCreated(rule)`.
 */
const MakeRecurringModal = ({ suggestion, client, book, onClose, onCreated }) => {
  const [recurrence, setRecurrence] = useState(null);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (suggestion) {
      setRecurrence(recurrenceFrom(suggestion));
      setError(null);
      setSaving(false);
    }
  }, [suggestion]);

  if (!suggestion || !recurrence) return null;

  const startDate = formatDateForInput(suggestion.lastDate);
  const problem = recurrenceProblem(recurrence, startDate);
  const amount = parseFloat(suggestion.outflow) > 0 ? suggestion.outflow : suggestion.inflow;
  const direction = parseFloat(suggestion.outflow) > 0 ? gettext('out') : gettext('in');

  const save = async () => {
    if (problem) {
      setError(problem);
      return;
    }
    setSaving(true);
    setError(null);
    const payload = recurrencePayload(recurrence, startDate);
    try {
      const rule = await client.bankFeedRecurringFromTransaction({
        ...book.params,
        scheduleFromTransaction: {
          transaction: suggestion.transactionId,
          frequency: payload.frequency,
          interval: payload.interval,
          weekday: payload.weekday,
          dayOfMonth: payload.day_of_month,
          endDate: utcDay(payload.end_date),
        },
      });
      onCreated(rule);
    } catch (err) {
      const body = await err.response?.json?.().catch(() => null);
      setError(body?.error || gettext('Failed to make this recurring'));
      setSaving(false);
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      size="sm"
      testId="make-recurring-modal"
      title={gettext('Make recurring')}
      actions={
        <>
          <button type="button" className="btn btn-sm" onClick={onClose} disabled={saving}>
            {gettext('Cancel')}
          </button>
          <button
            type="button"
            className="btn btn-sm btn-primary"
            onClick={save}
            disabled={saving || Boolean(problem)}
            data-testid="make-recurring-save"
          >
            {saving ? gettext('Saving...') : gettext('Make recurring')}
          </button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="rounded-box border border-base-300 p-3 text-sm" data-testid="make-recurring-summary">
          <div className="flex items-baseline justify-between gap-2">
            <span className="font-medium">{suggestion.payee}</span>
            <span className="money">
              {formatCurrency(amount)} {direction}
            </span>
          </div>
          <div className="mt-1 text-xs text-base-content/70">
            {suggestion.account?.name}
            {' · '}
            {suggestion.isSplit
              ? gettext('Split')
              : suggestion.category
                ? suggestion.category.name
                : gettext('Uncategorized')}
          </div>
          <div className="mt-1 text-xs text-base-content/70">
            {interpolate(gettext('Seen %s times, most recently on %s.'), [
              suggestion.occurrences,
              formatDateUtc(suggestion.lastDate),
            ])}
          </div>
        </div>

        {suggestion.bankSynced && (
          <div role="alert" className="alert alert-warning text-sm" data-testid="make-recurring-bank-warning">
            <span>
              {interpolate(
                gettext(
                  '%s is synced from your bank, which will also import each payment. A recurring transaction here adds it a second time.',
                ),
                [suggestion.account?.name],
              )}
            </span>
          </div>
        )}

        <RecurrenceFields recurrence={recurrence} date={startDate} onChange={setRecurrence} error={error} />
      </div>
    </Modal>
  );
};

export default MakeRecurringModal;
