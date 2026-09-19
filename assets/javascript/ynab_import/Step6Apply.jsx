/* globals gettext */

import React, { useEffect, useRef, useState } from 'react';

import Icon from '../common/Icon';

/**
 * The import running, and then what it did.
 *
 * Two rules the bar follows, both learned from watching it get them wrong.
 *
 * It never goes backwards, and it never fills while work is still going on: a bar
 * sitting at 100% reads as "finished, hung", which is the one thing it must not
 * say about a job that is still writing. The server caps live progress at 99 for
 * the same reason; this caps it again, because a bar is a promise.
 *
 * And it keeps moving between the server's numbers. An import reports at phase
 * boundaries, so the gaps between them are long and silent -- during which a
 * frozen bar is indistinguishable from a broken one. Between reports it creeps,
 * slowly and always short of the next real figure, so the movement is honest about
 * being an animation rather than news.
 */
const money = (value) =>
  `$${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

// How far the creep may run past the last real figure, and how long it takes to
// get there. Deliberately timid: it is filling silence, not reporting work.
const CREEP_CEILING = 6;
const CREEP_SECONDS = 25;
const CREEP_TICK_MS = 400;

// The bar's own ceiling while the server still says the import is running.
const NEARLY_DONE = 99;

// How long a queued import waits before the wizard says so. Long enough that a
// worker picking it up promptly is never accused of being missing.
const QUEUE_PATIENCE_SECONDS = 12;

/**
 * A coarse bucket, because a per-second estimate from a phased job is a lie.
 *
 * The buckets are wide enough that the estimate does not visibly jitter as the
 * rate changes between phases, and worded so none of them claims more precision
 * than the number behind it has.
 */
const remainingText = (seconds) => {
  if (seconds === null || seconds === undefined) return '';
  if (seconds < 15) return gettext('a few seconds left');
  if (seconds < 45) return gettext('under a minute left');
  if (seconds < 90) return gettext('about a minute left');
  return gettext('about {n} minutes left').replace('{n}', Math.round(seconds / 60));
};

const elapsedText = (seconds) => {
  if (!seconds || seconds < 5) return '';
  if (seconds < 60) return gettext('{n} seconds so far').replace('{n}', Math.round(seconds));
  const minutes = Math.floor(seconds / 60);
  return gettext('{n} min {s} sec so far')
    .replace('{n}', minutes)
    .replace('{s}', Math.round(seconds % 60));
};

/**
 * The number on screen: the server's, nudged along while it is silent.
 *
 * `floor` is the last figure the server gave, so the creep can never carry the bar
 * past what is actually known by more than `CREEP_CEILING`, and a new figure
 * always wins.
 */
const useCreepingProgress = (target, running) => {
  const [shown, setShown] = useState(target);
  const floor = useRef(target);
  const since = useRef(Date.now());

  useEffect(() => {
    if (target > floor.current) {
      floor.current = target;
      since.current = Date.now();
      setShown((current) => Math.max(current, target));
    }
  }, [target]);

  useEffect(() => {
    if (!running) return undefined;
    const id = setInterval(() => {
      const seconds = (Date.now() - since.current) / 1000;
      const crept = floor.current + CREEP_CEILING * Math.min(1, seconds / CREEP_SECONDS);
      setShown((current) => Math.min(NEARLY_DONE, Math.max(current, crept)));
    }, CREEP_TICK_MS);
    return () => clearInterval(id);
  }, [running]);

  return Math.round(Math.min(running ? NEARLY_DONE : 100, shown));
};

const Step6Apply = ({ status, urls, onRetry }) => {
  const failed = status?.status === 'failed';
  const done = status?.status === 'done';
  const running = !failed && !done;

  const percent = useCreepingProgress(status?.progress || 0, running);
  const elapsed = status?.elapsed_seconds || 0;
  const queued = running && !status?.started && elapsed === 0;
  const [waited, setWaited] = useState(0);

  useEffect(() => {
    if (!running) return undefined;
    const started = Date.now();
    const id = setInterval(() => setWaited((Date.now() - started) / 1000), 1000);
    return () => clearInterval(id);
  }, [running]);

  if (failed) {
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
    const remaining = remainingText(status?.eta_seconds);
    const waiting = queued && waited > QUEUE_PATIENCE_SECONDS;

    return (
      <div className="space-y-4" data-testid="ynab-running">
        <h2 className="text-xl font-semibold tracking-tight">{gettext('Importing your budget')}</h2>

        <div>
          <progress
            className="progress progress-primary w-full"
            value={percent}
            max="100"
            data-testid="ynab-progress"
            data-percent={percent}
          ></progress>
          <div className="mt-2 flex flex-wrap items-baseline justify-between gap-2 text-sm">
            <span data-testid="ynab-step">{status?.step || gettext('Getting started…')}</span>
            <span className="money text-base-content/70" data-testid="ynab-eta">
              {percent}%{remaining && ` · ${remaining}`}
            </span>
          </div>
        </div>

        <p className="text-sm text-base-content/70">
          {elapsedText(elapsed || waited)}
          {elapsedText(elapsed || waited) && ' · '}
          {gettext('A long history takes a moment. You can leave this page open.')}
        </p>

        {waiting && (
          <div className="alert alert-warning" data-testid="ynab-queued">
            <Icon name="triangle-alert" className="h-5 w-5 shrink-0" />
            <span>
              {gettext(
                'Your import is queued but nothing has picked it up yet. It runs in a background worker — if this does not start shortly, check that the worker is running.',
              )}
            </span>
          </div>
        )}
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
