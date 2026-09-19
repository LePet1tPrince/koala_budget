/* globals gettext */

import React from 'react';

import Icon from '../common/Icon';

/**
 * What will be created, and what the import decided on the user's behalf.
 *
 * The reconciliation runs here, before anything is written: it is pure, so the
 * checks the user sees on this screen are the same ones the applied books will
 * pass. A failing check is shown rather than hidden -- an import that has quietly
 * lost a transaction is exactly the thing a migration has to be able to say.
 */
const money = (value) =>
  `$${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const Stat = ({ label, value, desc }) => (
  <div className="stat px-4 py-3">
    <div className="stat-title text-xs">{label}</div>
    <div className="stat-value money text-2xl">{value}</div>
    {desc && <div className="stat-desc">{desc}</div>}
  </div>
);

const Step5Preview = ({ preview, loading }) => {
  if (loading || !preview) {
    return (
      <div className="flex items-center gap-3 py-12 text-base-content/70" data-testid="ynab-preview-loading">
        <span className="loading loading-spinner"></span>
        {gettext('Working out what your books will look like…')}
      </div>
    );
  }

  const { summary, notes, chart, reconciliation, goals } = preview;

  return (
    <div className="space-y-6" data-testid="ynab-preview">
      <div>
        <h2 className="text-xl font-semibold tracking-tight">{gettext('Here is what you will get')}</h2>
        <p className="mt-2 max-w-prose text-base-content/70">
          {gettext('Nothing has been written yet. This is the whole import, checked against your YNAB plan.')}
        </p>
      </div>

      <div className="app-surface stats stats-vertical w-full sm:stats-horizontal">
        <Stat
          label={gettext('Transactions')}
          value={Number(summary.entries).toLocaleString()}
          desc={`${summary.first_date} → ${summary.last_date}`}
        />
        <Stat
          label={gettext('Accounts')}
          value={Number(summary.accounts).toLocaleString()}
          desc={gettext('{n} payees').replace('{n}', Number(summary.payees).toLocaleString())}
        />
        <Stat
          label={gettext('Budgets')}
          value={Number(summary.budgets).toLocaleString()}
          desc={gettext('across {n} months').replace('{n}', summary.months)}
        />
        <Stat label={gettext('Net worth')} value={money(summary.net_worth)} desc={gettext('once imported')} />
      </div>

      {reconciliation && (
        <div className="app-card space-y-3" data-testid="ynab-reconciliation">
          <h3 className="font-semibold">{gettext('Checks against your YNAB plan')}</h3>
          <ul className="space-y-2">
            {reconciliation.checks.map((check) => (
              <li key={check.name} className="flex items-start gap-3">
                <Icon
                  name={check.passed ? 'circle-check' : 'triangle-alert'}
                  className={`mt-0.5 h-5 w-5 shrink-0 ${check.passed ? 'text-success' : 'text-warning'}`}
                />
                <div>
                  <div className="text-sm font-medium">{check.label}</div>
                  <div className="text-xs text-base-content/70">{check.detail}</div>
                  {!check.passed && (
                    <ul className="mt-1 space-y-0.5 text-xs text-warning">
                      {check.samples.map((sample) => (
                        <li key={sample}>{sample}</li>
                      ))}
                    </ul>
                  )}
                </div>
              </li>
            ))}
          </ul>
          {reconciliation.export_month && (
            <p className="text-xs text-base-content/70">
              {gettext(
                'The month you exported in is left out of these checks: your plan was a snapshot taken part-way through it, while the register already carries the whole month.',
              )}
            </p>
          )}
        </div>
      )}

      {goals.length > 0 && (
        <div className="app-card">
          <h3 className="font-semibold">{gettext('Savings goals')}</h3>
          <ul className="mt-2 flex flex-wrap gap-2">
            {goals.map((goal) => (
              <li key={goal.name} className="badge badge-soft badge-success">
                {goal.name} · {money(goal.target)}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="app-card">
        <h3 className="font-semibold">{gettext('Your chart of accounts')}</h3>
        <div className="mt-3 grid gap-4 sm:grid-cols-2">
          {chart.map((section) => (
            <div key={section.type}>
              <div className="text-sm font-semibold">{section.label}</div>
              {section.groups.map((group) => (
                <div key={group.name} className="mt-2">
                  <div className="text-xs uppercase tracking-[0.08em] text-base-content/70">{group.name}</div>
                  <div className="text-sm">{group.accounts.join(' · ')}</div>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>

      <div className="app-card">
        <h3 className="font-semibold">{gettext('What we worked out for you')}</h3>
        <ul className="mt-2 space-y-2 text-sm text-base-content/70">
          {notes.map((note) => (
            <li key={note} className="flex items-start gap-2">
              <Icon name="info" className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{note}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
};

export default Step5Preview;
