/* globals gettext */

import React, { useEffect, useRef, useState } from 'react';

import Icon from '../common/Icon';

/**
 * The import running, and then what it did.
 *
 * The progress bar's rules are copied from `apps/ynab_import/Step6Apply.jsx`,
 * not reinvented: it never goes backwards, never fills while work is still
 * going on (the server caps live progress at 99 for the same reason this
 * caps it again), and creeps gently between the server's own reports so a
 * long silent phase never reads as a hang. See that file's comments for why
 * each number here is what it is.
 */
const POLL_MS = 900;
const CREEP_CEILING = 6;
const CREEP_SECONDS = 25;
const CREEP_TICK_MS = 400;
const NEARLY_DONE = 99;
const QUEUE_PATIENCE_SECONDS = 12;

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

const CountRow = ({ label, value }) => (
  <div className="flex justify-between text-sm">
    <span className="text-base-content/70">{label}</span>
    <span>{Number(value).toLocaleString()}</span>
  </div>
);

const Step4Apply = ({ api, importId, safetyExportUrl, homeUrl, onStartOver }) => {
  const [status, setStatus] = useState(null);
  const polling = useRef(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const first = await api.status(importId);
        if (!cancelled) setStatus(first);
      } catch {
        // The next poll tick will try again.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [api, importId]);

  useEffect(() => {
    if (status && (status.status === 'done' || status.status === 'failed')) return undefined;
    polling.current = setInterval(async () => {
      try {
        setStatus(await api.status(importId));
      } catch {
        // A single failed poll says nothing -- the next one will.
      }
    }, POLL_MS);
    return () => clearInterval(polling.current);
  }, [api, importId, status]);

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

  const safetyLink = safetyExportUrl ? `${safetyExportUrl}?import_id=${encodeURIComponent(importId)}` : null;

  if (!status) {
    return (
      <div className="app-card" data-testid="apply-loading">
        <span className="loading loading-spinner loading-md" />
      </div>
    );
  }

  if (failed) {
    return (
      <div className="app-card space-y-5" data-testid="apply-failed">
        <div className="alert alert-error">
          <Icon name="triangle-alert" className="h-5 w-5 shrink-0" />
          <span>{status.error || gettext('The import could not be completed.')}</span>
        </div>
        <p className="text-base-content/70 text-sm">
          {gettext(
            'Nothing was changed — the whole import runs in one transaction, so a run that does not finish leaves your books exactly as they were.',
          )}
        </p>
        {/* Both controls are `inline-flex` (daisyUI `btn`), so `space-y-5`
            would not separate them either -- lay them out deliberately. */}
        <div className="flex flex-wrap items-center gap-3">
          {status.safety_archive_available && safetyLink && (
            <a href={safetyLink} className="btn btn-outline btn-sm" data-testid="safety-download-failed">
              <Icon name="download" className="h-4 w-4" />
              {gettext('Download the backup taken before this run')}
            </a>
          )}
          <button type="button" className="btn btn-primary" onClick={onStartOver} data-testid="start-over-button">
            {gettext('Start again')}
          </button>
        </div>
      </div>
    );
  }

  if (running) {
    const remaining = remainingText(status?.eta_seconds);
    const waiting = queued && waited > QUEUE_PATIENCE_SECONDS;

    return (
      <div className="app-card space-y-4" data-testid="apply-running">
        <h2 className="text-lg font-semibold">{gettext('Importing…')}</h2>

        <div>
          <progress
            className="progress progress-primary w-full"
            value={percent}
            max="100"
            data-testid="apply-progress"
            data-percent={percent}
          ></progress>
          <div className="mt-2 flex flex-wrap items-baseline justify-between gap-2 text-sm">
            <span data-testid="apply-step">{status.step || gettext('Getting started…')}</span>
            <span className="money text-base-content/70">
              {percent}%{remaining && ` · ${remaining}`}
            </span>
          </div>
        </div>

        <p className="text-sm text-base-content/70">
          {elapsedText(elapsed || waited)}
          {elapsedText(elapsed || waited) && ' · '}
          {gettext('A large team takes a moment. You can leave this page open.')}
        </p>

        {waiting && (
          <div className="alert alert-warning" data-testid="apply-queued">
            <Icon name="triangle-alert" className="h-5 w-5 shrink-0" />
            <span>
              {gettext(
                'This import is queued but nothing has picked it up yet. It runs in a background worker — if this does not start shortly, check that the worker is running.',
              )}
            </span>
          </div>
        )}
      </div>
    );
  }

  const result = status.result || {};

  return (
    <div className="app-card space-y-6" data-testid="apply-done">
      <div className="flex items-start gap-3">
        <Icon name="circle-check" className="mt-1 h-8 w-8 shrink-0 text-success" />
        <div>
          <h2 className="text-xl font-semibold tracking-tight">{gettext('Import complete')}</h2>
          <p className="mt-1 text-base-content/70 text-sm">
            {gettext('This set of books now matches the file you loaded.')}
          </p>
        </div>
      </div>

      <div className="app-surface p-4 space-y-1" data-testid="apply-result-counts">
        <CountRow label={gettext('Accounts')} value={result.accounts || 0} />
        <CountRow label={gettext('Goals')} value={result.goals || 0} />
        <CountRow label={gettext('Transactions')} value={result.entries || 0} />
        <CountRow label={gettext('Budget amounts')} value={result.budgets || 0} />
        <CountRow label={gettext('Goal contributions')} value={result.goal_allocations || 0} />
        <CountRow label={gettext('Bank feed rows')} value={result.bank_transactions || 0} />
      </div>

      {/* `block w-fit`, not a bare anchor: an inline element is not a block-
          level sibling, so the card's `space-y-6` applies no margin against it
          and this link would sit on the button's own line (and, at phone width,
          three pixels above it). */}
      {status.safety_archive_available && safetyLink && (
        <a href={safetyLink} className="link link-primary text-sm block w-fit" data-testid="safety-download-done">
          {gettext('Download a copy of this set of books from just before the import')}
        </a>
      )}

      <a href={homeUrl} className="btn btn-primary w-fit" data-testid="apply-go-home">
        {gettext('Go to my dashboard')}
      </a>
    </div>
  );
};

export default Step4Apply;
