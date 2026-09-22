/* globals gettext */

import React, { useState } from 'react';

import Icon from '../common/Icon';
import Spinner from '../common/Spinner';

// Matches the shared `currency` template filter and
// `monthly_review/format.js`: the sign goes *outside* the dollar sign, so a
// negative net worth reads "-$159.12" and not "$-159.12". This screen shows
// the destination's net worth beside the file's, and a figure formatted
// differently from the dashboard it is being compared against is exactly the
// kind of mismatch that makes someone doubt the number.
const money = (value) => {
  const n = Number(value);
  if (Number.isNaN(n)) return '—';
  const sign = n < 0 ? '-' : '';
  return `${sign}$${Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

const dateRangeText = (range) => {
  if (!range?.first || !range?.last) return gettext('No transactions');
  return `${range.first} – ${range.last}`;
};

const SummaryColumn = ({ title, checks, tone, testId }) => (
  <div className={`app-surface p-4 space-y-2 border-2 ${tone}`} data-testid={testId}>
    <h3 className="font-semibold">{title}</h3>
    <dl className="text-sm space-y-1">
      <div className="flex justify-between">
        <dt className="text-base-content/70">{gettext('Accounts')}</dt>
        <dd>{checks?.counts?.accounts ?? '—'}</dd>
      </div>
      <div className="flex justify-between">
        <dt className="text-base-content/70">{gettext('Transactions')}</dt>
        <dd>{checks?.counts?.entries ?? '—'}</dd>
      </div>
      <div className="flex justify-between">
        <dt className="text-base-content/70">{gettext('Goals')}</dt>
        <dd>{checks?.counts?.goals ?? '—'}</dd>
      </div>
      <div className="flex justify-between">
        <dt className="text-base-content/70">{gettext('Net worth')}</dt>
        <dd className="money">{money(checks?.net_worth)}</dd>
      </div>
      <div className="flex justify-between">
        <dt className="text-base-content/70">{gettext('Date range')}</dt>
        <dd>{dateRangeText(checks?.date_range)}</dd>
      </div>
    </dl>
  </div>
);

/**
 * §4.4.5's two-column comparison, the screen this feature lives or dies on.
 * It has to read as a consequence, not a form -- so what will be destroyed
 * sits right beside what is arriving, in the same shape, before the one
 * input that actually confirms anything.
 */
const Step3Confirm = ({ api, importId, teamName, file, destination, onApplyStarted, onError, onCancel }) => {
  const [typedName, setTypedName] = useState('');
  const [busy, setBusy] = useState(false);
  const nameMatches = typedName === teamName;
  const omittedTotal = Object.values(file.omitted || {}).reduce((sum, n) => sum + (Number(n) || 0), 0);

  const handleConfirm = async () => {
    setBusy(true);
    try {
      await api.apply(importId, typedName);
      onApplyStarted(importId);
    } catch (error) {
      onError(error);
      setBusy(false);
    }
  };

  return (
    <div className="app-card space-y-6" data-testid="confirm-step">
      <div>
        <h2 className="text-lg font-semibold">{gettext('This will replace everything in this team')}</h2>
        <p className="text-base-content/70 text-sm mt-1">
          {gettext('There is no merge. Everything on the right is deleted first; everything on the left is written in its place.')}
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <SummaryColumn title={gettext('In the file')} checks={file.checks} tone="border-success/30" testId="summary-file" />
        <SummaryColumn
          title={gettext('Will be destroyed')}
          checks={destination.checks}
          tone="border-error/30"
          testId="summary-destination"
        />
      </div>

      {destination.has_plaid && (
        <div className="alert alert-warning" data-testid="plaid-warning">
          <Icon name="triangle-alert" className="h-5 w-5 shrink-0" />
          <span>
            {gettext(
              'This team has a connected bank (Plaid). The import will disconnect it — you will need to re-link it afterwards.',
            )}
          </span>
        </div>
      )}

      {file.hash_warnings?.length > 0 && (
        <div className="alert alert-warning" data-testid="hash-warning">
          <Icon name="triangle-alert" className="h-5 w-5 shrink-0" />
          <div className="text-sm">
            {file.hash_warnings.map((warning) => (
              <div key={warning}>{warning}</div>
            ))}
          </div>
        </div>
      )}

      {omittedTotal > 0 && (
        <p className="text-sm text-base-content/70" data-testid="omitted-note">
          {gettext(
            'A few things in the source team could not be carried across: empty account groups, unused institutions or payees, and dismissed transfer suggestions. Nothing that affects your balances.',
          )}
        </p>
      )}

      <div className="border-t border-base-300 pt-5 space-y-3">
        <label className="form-control" htmlFor="confirm-team-name">
          <span className="label-text text-sm">
            {gettext('Type this team’s name — {name} — to confirm.').replace('{name}', teamName)}
          </span>
          <input
            id="confirm-team-name"
            type="text"
            className="input input-bordered w-full mt-1"
            value={typedName}
            onChange={(e) => setTypedName(e.target.value)}
            autoComplete="off"
            data-testid="confirm-team-name-input"
          />
        </label>

        <div className="flex justify-end gap-2">
          <button type="button" className="btn btn-ghost" onClick={onCancel} disabled={busy}>
            {gettext('Cancel')}
          </button>
          <button
            type="button"
            className="btn btn-error"
            onClick={handleConfirm}
            disabled={!nameMatches || busy}
            data-testid="confirm-apply-button"
          >
            {busy ? <Spinner size="sm" /> : gettext('Delete and replace this team’s books')}
          </button>
        </div>
      </div>
    </div>
  );
};

export default Step3Confirm;
