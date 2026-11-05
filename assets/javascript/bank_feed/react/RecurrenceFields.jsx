import React from 'react';
import DateField from '../../common/DateField';

/* globals gettext, interpolate */

export const FREQUENCIES = ['daily', 'weekly', 'monthly', 'yearly'];
export const LAST_DAY = -1;
const MAX_INTERVAL = 99;

// Python's weekday numbering (0 = Monday), which is what the server stores.
const WEEKDAYS = () => [
  gettext('Monday'),
  gettext('Tuesday'),
  gettext('Wednesday'),
  gettext('Thursday'),
  gettext('Friday'),
  gettext('Saturday'),
  gettext('Sunday'),
];

const unitLabel = (frequency, n) => {
  const one = n === 1;
  switch (frequency) {
    case 'daily':
      return one ? gettext('day') : gettext('days');
    case 'weekly':
      return one ? gettext('week') : gettext('weeks');
    case 'monthly':
      return one ? gettext('month') : gettext('months');
    default:
      return one ? gettext('year') : gettext('years');
  }
};

/** A 'YYYY-MM-DD' string as a local Date, or null. */
const parseDay = (value) => {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value || '');
  return match ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3])) : null;
};

/** The weekday and day of the month a schedule repeats on when the user hasn't picked one: the date's own. */
export const dateDefaults = (date) => {
  const day = parseDay(date);
  return day ? { weekday: (day.getDay() + 6) % 7, dayOfMonth: day.getDate() } : { weekday: 0, dayOfMonth: 1 };
};

/** A blank schedule: monthly, on the transaction date's day. */
export const emptyRecurrence = () => ({
  frequency: 'monthly',
  interval: '1',
  weekday: null, // null = follow the transaction date
  dayOfMonth: null,
  endDate: '',
});

/** The schedule's first problem, or null. */
export const recurrenceProblem = (recurrence, date) => {
  const n = Number(recurrence.interval);
  if (!Number.isInteger(n) || n < 1 || n > MAX_INTERVAL) {
    return interpolate(gettext('Repeat every 1 to %s.'), [MAX_INTERVAL]);
  }
  if (recurrence.endDate && date && recurrence.endDate < date) {
    return gettext('The end date must be on or after the transaction date.');
  }
  return null;
};

/** The schedule as the feed API takes it (`recurrence` on create). */
export const recurrencePayload = (recurrence, date) => {
  const defaults = dateDefaults(date);
  return {
    frequency: recurrence.frequency,
    interval: Number(recurrence.interval),
    weekday: recurrence.frequency === 'weekly' ? (recurrence.weekday ?? defaults.weekday) : null,
    day_of_month: recurrence.frequency === 'monthly' ? (recurrence.dayOfMonth ?? defaults.dayOfMonth) : null,
    end_date: recurrence.endDate || null,
  };
};

/** "Every 2 weeks on Wednesday" -- the schedule in words, matching the server's wording. */
export const describeRecurrence = (recurrence, date) => {
  const payload = recurrencePayload(recurrence, date);
  const n = payload.interval || 1;
  const every =
    n === 1
      ? interpolate(gettext('Every %s'), [unitLabel(payload.frequency, 1)])
      : interpolate(gettext('Every %s %s'), [n, unitLabel(payload.frequency, n)]);
  if (payload.frequency === 'weekly') {
    return interpolate(gettext('%s on %s'), [every, WEEKDAYS()[payload.weekday]]);
  }
  if (payload.frequency === 'monthly') {
    return payload.day_of_month === LAST_DAY
      ? interpolate(gettext('%s on the last day'), [every])
      : interpolate(gettext('%s on day %s'), [every, payload.day_of_month]);
  }
  if (payload.frequency === 'yearly') {
    const day = parseDay(date);
    if (day) {
      const label = day.toLocaleDateString(undefined, { month: 'long', day: 'numeric' });
      return interpolate(gettext('%s on %s'), [every, label]);
    }
  }
  return every;
};

/**
 * The "Make recurring" schedule fields of the Add Transaction modal.
 *
 * Presentational: the modal owns `recurrence` (see `emptyRecurrence`). The
 * transaction's own date is the first occurrence; the weekday and day of the
 * month follow it until the user picks another.
 */
const RecurrenceFields = ({ recurrence, date, onChange, error }) => {
  const defaults = dateDefaults(date);
  const n = Number(recurrence.interval) || 1;
  const set = (patch) => onChange({ ...recurrence, ...patch });

  return (
    <div className="flex flex-col gap-3 rounded-box border border-base-300 p-3" data-testid="recurrence-fields">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span>{gettext('Repeat every')}</span>
        <input
          type="number"
          min="1"
          max={MAX_INTERVAL}
          inputMode="numeric"
          className="input input-bordered input-sm w-16"
          value={recurrence.interval}
          onChange={(e) => set({ interval: e.target.value })}
          aria-label={gettext('Repeat every')}
          data-testid="recurrence-interval"
        />
        <select
          className="select select-bordered select-sm w-28"
          value={recurrence.frequency}
          onChange={(e) => set({ frequency: e.target.value })}
          aria-label={gettext('Frequency')}
          data-testid="recurrence-frequency"
        >
          {FREQUENCIES.map((f) => (
            <option key={f} value={f}>
              {unitLabel(f, n)}
            </option>
          ))}
        </select>

        {recurrence.frequency === 'weekly' && (
          <span className="flex items-center gap-2">
            <span>{gettext('on')}</span>
            <select
              className="select select-bordered select-sm w-36"
              value={recurrence.weekday ?? defaults.weekday}
              onChange={(e) => set({ weekday: Number(e.target.value) })}
              aria-label={gettext('Day of the week')}
              data-testid="recurrence-weekday"
            >
              {WEEKDAYS().map((name, i) => (
                <option key={name} value={i}>
                  {name}
                </option>
              ))}
            </select>
          </span>
        )}

        {recurrence.frequency === 'monthly' && (
          <span className="flex items-center gap-2">
            <span>{gettext('on day')}</span>
            <select
              className="select select-bordered select-sm w-28"
              value={recurrence.dayOfMonth ?? defaults.dayOfMonth}
              onChange={(e) => set({ dayOfMonth: Number(e.target.value) })}
              aria-label={gettext('Day of the month')}
              data-testid="recurrence-day-of-month"
            >
              {Array.from({ length: 31 }, (_, i) => i + 1).map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
              <option value={LAST_DAY}>{gettext('Last day')}</option>
            </select>
          </span>
        )}
      </div>

      <DateField
        label={gettext('End date (optional)')}
        value={recurrence.endDate}
        onChange={(value) => set({ endDate: value })}
        allowClear
        testId="recurrence-end-date"
      />

      <p className={`text-xs ${error ? 'text-error' : 'text-base-content/70'}`} data-testid="recurrence-summary">
        {error ||
          interpolate(gettext('%s, starting after this one. Each is added to the bank feed on its date.'), [
            describeRecurrence(recurrence, date),
          ])}
      </p>
    </div>
  );
};

export default RecurrenceFields;
