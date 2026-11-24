/* globals gettext */

import React, { useEffect, useRef, useState } from 'react';

import Icon from './Icon';

/**
 * An import running in a background worker: the bar, the step, and time so far
 * and left. Shared by the YNAB import and the data import wizards.
 *
 * The bar never goes backwards, and never fills while work is still going on: a
 * full bar reads as "finished, hung". The server caps live progress at 99; this
 * caps it again. Between the server's reports (which come at phase boundaries,
 * with long silences between) it creeps -- slowly, and never more than
 * `CREEP_CEILING` past the last real figure -- so a silent phase never reads as
 * a hang.
 */
const CREEP_CEILING = 6;
const CREEP_SECONDS = 25;
const CREEP_TICK_MS = 400;
const NEARLY_DONE = 99;

// How long a queued import waits before the wizard says nothing has picked it up.
const QUEUE_PATIENCE_SECONDS = 12;

/** Coarse buckets: a per-second estimate from a phased job would jitter and overclaim. */
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
  return gettext('{n} min {s} sec so far')
    .replace('{n}', Math.floor(seconds / 60))
    .replace('{s}', Math.round(seconds % 60));
};

/** The server's figure, nudged along while it is silent; a new figure always wins. */
const useCreepingProgress = (target) => {
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
    const id = setInterval(() => {
      const seconds = (Date.now() - since.current) / 1000;
      const crept = floor.current + CREEP_CEILING * Math.min(1, seconds / CREEP_SECONDS);
      setShown((current) => Math.min(NEARLY_DONE, Math.max(current, crept)));
    }, CREEP_TICK_MS);
    return () => clearInterval(id);
  }, []);

  return Math.round(Math.min(NEARLY_DONE, shown));
};

/**
 * `status` is the import's status payload (camelCase). `testId` prefixes the
 * data-testids: `<testId>-running`, `-progress`, `-step`, `-eta`, `-queued`.
 */
const ImportRunning = ({ status, testId, title, note, queuedMessage, className = '' }) => {
  const percent = useCreepingProgress(status?.progress || 0);
  const elapsed = status?.elapsedSeconds || 0;
  const [waited, setWaited] = useState(0);

  useEffect(() => {
    const started = Date.now();
    const id = setInterval(() => setWaited((Date.now() - started) / 1000), 1000);
    return () => clearInterval(id);
  }, []);

  const queued = !status?.started && elapsed === 0 && waited > QUEUE_PATIENCE_SECONDS;
  const remaining = remainingText(status?.etaSeconds);
  const soFar = elapsedText(elapsed || waited);

  return (
    <div className={`space-y-4 ${className}`} data-testid={`${testId}-running`}>
      <h2 className="text-xl font-semibold tracking-tight">{title}</h2>

      <div>
        <progress
          className="progress progress-primary w-full"
          value={percent}
          max="100"
          data-testid={`${testId}-progress`}
          data-percent={percent}
        ></progress>
        <div className="mt-2 flex flex-wrap items-baseline justify-between gap-2 text-sm">
          <span data-testid={`${testId}-step`}>{status?.step || gettext('Getting started…')}</span>
          <span className="money text-base-content/70" data-testid={`${testId}-eta`}>
            {percent}%{remaining && ` · ${remaining}`}
          </span>
        </div>
      </div>

      <p className="text-sm text-base-content/70">
        {soFar && `${soFar} · `}
        {note}
      </p>

      {queued && (
        <div className="alert alert-warning" data-testid={`${testId}-queued`}>
          <Icon name="triangle-alert" className="h-5 w-5 shrink-0" />
          <span>{queuedMessage}</span>
        </div>
      )}
    </div>
  );
};

export default ImportRunning;
