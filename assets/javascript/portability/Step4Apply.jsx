/* globals gettext */

import React, { useEffect, useRef, useState } from 'react';

import Icon from '../common/Icon';
import ImportRunning from '../common/ImportRunning';

const POLL_MS = 900;

const CountRow = ({ label, value }) => (
  <div className="flex justify-between text-sm">
    <span className="text-base-content/70">{label}</span>
    <span>{Number(value).toLocaleString()}</span>
  </div>
);

const Step4Apply = ({ api, importId, homeUrl, onStartOver }) => {
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

  const safetyLink = api.safetyExportUrl(importId);

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
          {status.safetyArchiveAvailable && safetyLink && (
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

  if (!done) {
    return (
      <ImportRunning
        status={status}
        testId="apply"
        className="app-card"
        title={gettext('Importing…')}
        note={gettext('A large team takes a moment. You can leave this page open.')}
        queuedMessage={gettext(
          'This import is queued but nothing has picked it up yet. It runs in a background worker — if this does not start shortly, check that the worker is running.',
        )}
      />
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
      {status.safetyArchiveAvailable && safetyLink && (
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
