/* globals gettext */

import React, { useCallback, useEffect, useRef, useState } from 'react';

import Icon from '../common/Icon';
import Step1Upload from './Step1Upload';
import Step2Accounts from './Step2Accounts';
import Step3Income from './Step3Income';
import Step4Goals from './Step4Goals';
import Step5Preview from './Step5Preview';
import Step6Apply from './Step6Apply';

/**
 * The YNAB import, one screen at a time.
 *
 * The client holds the user's edits and nothing else: every number on screen comes
 * from the server, which rebuilds the whole import from the stored export each time
 * the choices change. That is what makes the preview trustworthy -- it is produced
 * by the same code that writes the books, not by a second implementation here.
 */
const STEPS = [
  { key: 'upload', label: gettext('Your export') },
  { key: 'accounts', label: gettext('Accounts') },
  { key: 'income', label: gettext('Income') },
  { key: 'goals', label: gettext('Savings') },
  { key: 'preview', label: gettext('Review') },
  { key: 'apply', label: gettext('Import') },
];

// How often the apply screen asks how it is going. Fast enough to feel live,
// slow enough that a long import is not a thousand requests.
const POLL_MS = 1200;

const YnabImportWizard = ({ props }) => {
  const { api, canImport, teamName, homeUrl, accountsUrl, budgetUrl, goalsUrl } = props;

  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const [importId, setImportId] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [choices, setChoices] = useState({ accounts: {}, income: {}, categories: {} });

  const [preview, setPreview] = useState(null);
  const [previewing, setPreviewing] = useState(false);
  const [status, setStatus] = useState(null);

  const polling = useRef(null);

  const upload = useCallback(
    async (files) => {
      setBusy(true);
      setError(null);
      try {
        const result = await api.upload(files);
        setImportId(result.import_id);
        setAnalysis(result);
        setPreview(result);
        setStep(1);
      } catch (e) {
        setError(e.message);
      } finally {
        setBusy(false);
      }
    },
    [api],
  );

  const loadPreview = useCallback(async () => {
    setPreviewing(true);
    setError(null);
    try {
      setPreview(await api.preview(importId, choices));
    } catch (e) {
      // A rejected build leaves the previous preview on screen with the reason
      // above it, rather than blanking the review.
      setError(e.message);
    } finally {
      setPreviewing(false);
    }
  }, [api, importId, choices]);

  const start = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await api.apply(importId, choices);
      setStatus(result);
      setStep(5);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }, [api, importId, choices]);

  // Poll only while something is actually running, and stop the moment it is not:
  // a finished import that keeps asking is a request every second, forever.
  useEffect(() => {
    if (step !== 5 || !importId) return undefined;
    if (status && (status.status === 'done' || status.status === 'failed')) return undefined;

    polling.current = setInterval(async () => {
      try {
        setStatus(await api.status(importId));
      } catch {
        // A single failed poll says nothing -- the next one will.
      }
    }, POLL_MS);
    return () => clearInterval(polling.current);
  }, [api, importId, step, status]);

  const next = useCallback(() => {
    const target = step + 1;
    setStep(target);
    if (STEPS[target]?.key === 'preview') loadPreview();
  }, [step, loadPreview]);

  const current = STEPS[step];

  if (!canImport && step === 0) {
    return (
      <div className="app-card max-w-xl space-y-4" data-testid="ynab-blocked">
        <h1 className="text-xl font-semibold tracking-tight">{gettext('Import from YNAB')}</h1>
        <p className="text-base-content/70">
          {gettext(
            '{team} already has transactions. A YNAB import brings a whole set of books, so it needs an empty team — create a new team for it, or delete the existing transactions first.',
          ).replace('{team}', teamName)}
        </p>
        <a href={homeUrl} className="btn btn-primary">
          {gettext('Back to my dashboard')}
        </a>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <ul className="steps w-full" data-testid="ynab-steps">
        {STEPS.map((item, index) => (
          <li key={item.key} className={`step ${index <= step ? 'step-primary' : ''}`}>
            <span className="text-xs">{item.label}</span>
          </li>
        ))}
      </ul>

      <div className="app-card">
        {current.key === 'upload' && <Step1Upload onUpload={upload} busy={busy} error={error} />}

        {current.key === 'accounts' && (
          <Step2Accounts
            accounts={analysis.accounts}
            groups={analysis.groups}
            choices={choices.accounts}
            onChange={(accounts) => setChoices({ ...choices, accounts })}
          />
        )}

        {current.key === 'income' && (
          <Step3Income
            income={analysis.income}
            suggestions={analysis.income_accounts}
            choices={choices.income}
            onChange={(income) => setChoices({ ...choices, income })}
          />
        )}

        {current.key === 'goals' && (
          <Step4Goals
            categories={analysis.categories}
            choices={choices.categories}
            onChange={(categories) => setChoices({ ...choices, categories })}
          />
        )}

        {current.key === 'preview' && <Step5Preview preview={preview} loading={previewing} />}

        {current.key === 'apply' && (
          <Step6Apply
            status={status}
            urls={{ homeUrl, accountsUrl, budgetUrl, goalsUrl }}
            onRetry={() => window.location.reload()}
          />
        )}

        {error && current.key !== 'upload' && current.key !== 'apply' && (
          <div className="alert alert-error mt-4" data-testid="ynab-error">
            <span>{error}</span>
          </div>
        )}
      </div>

      {step > 0 && current.key !== 'apply' && (
        <div className="flex items-center justify-between">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => setStep(step - 1)}
            disabled={busy}
            data-testid="ynab-back"
          >
            <Icon name="arrow-left" className="mr-1 h-4 w-4 shrink-0" />
            {gettext('Back')}
          </button>

          {current.key === 'preview' ? (
            <button
              type="button"
              className="btn btn-primary"
              onClick={start}
              disabled={busy || previewing}
              data-testid="ynab-apply"
            >
              {busy && <span className="loading loading-spinner loading-xs"></span>}
              {gettext('Import my budget')}
            </button>
          ) : (
            <button type="button" className="btn btn-primary" onClick={next} data-testid="ynab-next">
              {gettext('Continue')}
              <Icon name="arrow-right" className="ml-1 h-4 w-4 shrink-0" />
            </button>
          )}
        </div>
      )}
    </div>
  );
};

export default YnabImportWizard;
