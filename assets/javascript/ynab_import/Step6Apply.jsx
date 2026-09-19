/* globals gettext */

import React from 'react';

import Icon from '../common/Icon';

/**
 * The import running, and then what it did.
 *
 * Progress is worth showing honestly: 6,000 transactions take long enough that a
 * spinner alone reads as a hang. The finished state leads with the checks, because
 * "your data is in" is only worth saying when the numbers agree with the ones the
 * user is leaving behind.
 */
const money = (value) =>
  `$${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const Step6Apply = ({ status, urls, onRetry }) => {
  const running = !status || status.status === 'running' || status.status === 'uploaded';

  if (status && status.status === 'failed') {
    return (
      <div className="space-y-5" data-testid="ynab-failed">
        <div className="alert alert-error">
          <Icon name="triangle-alert" className="h-5 w-5 shrink-0" />
          <span>{status.error || gettext('The import could not be completed.')}</span>
        </div>
        <p className="text-base-content/70">
          {gettext('Nothing was written — your books are exactly as they were before you started.')}
        </p>
        <button type="button" className="btn btn-primary" onClick={onRetry}>
          {gettext('Start again')}
        </button>
      </div>
    );
  }

  if (running) {
    return (
      <div className="space-y-5" data-testid="ynab-running">
        <h2 className="text-xl font-semibold tracking-tight">{gettext('Importing your budget')}</h2>
        <progress className="progress progress-primary w-full" value={status?.progress || 0} max="100"></progress>
        <p className="text-base-content/70">{status?.step || gettext('Starting…')}</p>
        <p className="text-sm text-base-content/70">
          {gettext('This takes a moment for a long history. You can leave this page open.')}
        </p>
      </div>
    );
  }

  const { created, summary, notes, reconciliation } = status.result || {};

  return (
    <div className="space-y-6" data-testid="ynab-done">
      <div className="flex items-start gap-3">
        <Icon name="circle-check" className="mt-1 h-8 w-8 shrink-0 text-success" />
        <div>
          <h2 className="text-xl font-semibold tracking-tight">{gettext('Your budget is in')}</h2>
          <p className="mt-1 text-base-content/70">
            {gettext('{entries} transactions across {accounts} accounts, with {years} of history.')
              .replace('{entries}', Number(created.entries).toLocaleString())
              .replace('{accounts}', Number(created.accounts).toLocaleString())
              .replace('{years}', `${summary.first_date?.slice(0, 4)}–${summary.last_date?.slice(0, 4)}`)}
          </p>
        </div>
      </div>

      <div className="app-surface stats stats-vertical w-full sm:stats-horizontal">
        <div className="stat px-4 py-3">
          <div className="stat-title text-xs">{gettext('Net worth')}</div>
          <div className="stat-value money text-2xl">{money(summary.net_worth)}</div>
        </div>
        <div className="stat px-4 py-3">
          <div className="stat-title text-xs">{gettext('Budgets')}</div>
          <div className="stat-value money text-2xl">{Number(created.budgets).toLocaleString()}</div>
        </div>
        <div className="stat px-4 py-3">
          <div className="stat-title text-xs">{gettext('Savings goals')}</div>
          <div className="stat-value money text-2xl">{Number(created.goals).toLocaleString()}</div>
        </div>
      </div>

      {reconciliation && (
        <div className="app-card space-y-2" data-testid="ynab-result-checks">
          <h3 className="font-semibold">{gettext('Checked against your YNAB plan')}</h3>
          {reconciliation.checks.map((check) => (
            <div key={check.name} className="flex items-start gap-3">
              <Icon
                name={check.passed ? 'circle-check' : 'triangle-alert'}
                className={`mt-0.5 h-5 w-5 shrink-0 ${check.passed ? 'text-success' : 'text-warning'}`}
              />
              <div>
                <div className="text-sm font-medium">{check.label}</div>
                <div className="text-xs text-base-content/70">{check.detail}</div>
              </div>
            </div>
          ))}
        </div>
      )}

      {notes?.length > 0 && (
        <div className="app-card">
          <h3 className="font-semibold">{gettext('Worth knowing')}</h3>
          <ul className="mt-2 space-y-2 text-sm text-base-content/70">
            {notes.map((note) => (
              <li key={note} className="flex items-start gap-2">
                <Icon name="info" className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{note}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <a href={urls.homeUrl} className="btn btn-primary" data-testid="ynab-go-home">
          {gettext('Go to my dashboard')}
        </a>
        <a href={urls.budgetUrl} className="btn btn-ghost">
          {gettext('See my budget')}
        </a>
        <a href={urls.goalsUrl} className="btn btn-ghost">
          {gettext('See my goals')}
        </a>
        <a href={urls.accountsUrl} className="btn btn-ghost">
          {gettext('See my accounts')}
        </a>
      </div>
    </div>
  );
};

export default Step6Apply;
