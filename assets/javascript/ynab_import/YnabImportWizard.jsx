/* globals gettext */

import React, { useCallback, useEffect, useRef, useState } from 'react';

import Icon from '../common/Icon';
import Modal from '../common/Modal';
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
 *
 * The import itself runs in a worker, so the browser is free to leave once it has
 * been started. `props.resume` is how coming back works: the server hands over an
 * import still running, or one that finished or failed in the last day, and the
 * wizard opens on that screen instead of on the upload form.
 */
const STEPS = [
  { key: 'upload', label: gettext('Your export') },
  { key: 'accounts', label: gettext('Accounts') },
  { key: 'income', label: gettext('Income') },
  { key: 'goals', label: gettext('Savings') },
  { key: 'preview', label: gettext('Review') },
  { key: 'apply', label: gettext('Import') },
];

// How often the apply screen asks how it is going. Fast enough that a phase change
// shows up while it still means something, slow enough that a long import is not a
// thousand requests.
const POLL_MS = 900;

const APPLY_STEP = STEPS.findIndex((item) => item.key === 'apply');

const YnabImportWizard = ({ props }) => {
  const { api, canImport, resume, bookName, homeUrl, accountsUrl, budgetUrl, goalsUrl } = props;

  const [step, setStep] = useState(resume ? APPLY_STEP : 0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const [importId, setImportId] = useState(resume?.id ?? null);
  const [analysis, setAnalysis] = useState(null);
  const [choices, setChoices] = useState({ accounts: {}, income: {}, categories: {} });
  // Names the user added on the accounts and income screens. Held here rather than
  // in the screens, which unmount on Back/Continue, so an added group that no row
  // uses yet is still offered on returning to the screen.
  const [extraGroups, setExtraGroups] = useState([]);
  const [extraIncomeAccounts, setExtraIncomeAccounts] = useState([]);

  const [preview, setPreview] = useState(null);
  const [previewing, setPreviewing] = useState(false);
  const [status, setStatus] = useState(resume ?? null);
  // A resumed import that failed wrote nothing, so starting again means starting
  // from the files -- and must not land back on the screen we just left.
  const [resumed, setResumed] = useState(Boolean(resume));

  const polling = useRef(null);

  const startOver = useCallback(() => {
    setResumed(false);
    setStatus(null);
    setImportId(null);
    setAnalysis(null);
    setPreview(null);
    setChoices({ accounts: {}, income: {}, categories: {} });
    setExtraGroups([]);
    setExtraIncomeAccounts([]);
    setError(null);
    setStep(0);
  }, []);

  const upload = useCallback(
    async (files) => {
      setBusy(true);
      setError(null);
      try {
        const result = await api.upload(files);
        setImportId(result.import_id);
        setAnalysis(result);
        setExtraGroups([]);
        setExtraIncomeAccounts([]);
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
      setStep(APPLY_STEP);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }, [api, importId, choices]);

  // Poll only while something is actually running, and stop the moment it is not:
  // a finished import that keeps asking is a request every second, forever.
  useEffect(() => {
    if (step !== APPLY_STEP || !importId) return undefined;
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

  // The choices made on the review screens live only in this page, so leaving
  // loses them. Not on the upload screen (nothing chosen yet) nor once the import
  // is running (it carries on in the worker without the page).
  const hasChoices = step > 0 && step < APPLY_STEP;
  // Where the user asked to go, while the "leave the import?" dialog is up.
  const [leaveTo, setLeaveTo] = useState(null);
  // Set once the user has confirmed, so the browser's own prompt doesn't follow ours.
  const leaving = useRef(false);

  useEffect(() => {
    if (!hasChoices) return undefined;

    // The takeover's close button is ours to intercept, so it gets a real dialog.
    const onClick = (e) => {
      const link = e.target.closest?.('a[data-takeover-close]');
      if (!link || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      e.preventDefault();
      setLeaveTo(link.href);
    };
    // Closing the tab, reloading and the browser's Back button are not: there the
    // browser only ever shows its own prompt, so that stays as the fallback.
    const warn = (e) => {
      if (leaving.current) return;
      e.preventDefault();
      e.returnValue = '';
    };
    document.addEventListener('click', onClick);
    window.addEventListener('beforeunload', warn);
    return () => {
      document.removeEventListener('click', onClick);
      window.removeEventListener('beforeunload', warn);
    };
  }, [hasChoices]);

  // `showModal()` focuses the first button, which is "Leave". Put focus on the safe
  // choice instead; the Modal child's effect has opened the dialog by the time this
  // parent effect runs.
  const keepGoingRef = useRef(null);
  useEffect(() => {
    if (leaveTo !== null) keepGoingRef.current?.focus();
  }, [leaveTo]);

  const leave = () => {
    leaving.current = true;
    window.location.href = leaveTo;
  };

  if (!canImport && !resumed && step === 0) {
    return (
      <div className="app-card max-w-xl space-y-4" data-testid="ynab-blocked">
        <h2 className="text-xl font-semibold tracking-tight">{gettext('This set of books is not empty')}</h2>
        <p className="text-base-content/70">
          {gettext(
            '{book} already has transactions. A YNAB import brings a whole set of books, so it needs an empty one — create a new set of books for it, or delete the existing transactions first.',
          ).replace('{book}', bookName)}
        </p>
        <a href={homeUrl} className="btn btn-primary">
          {gettext('Back to my dashboard')}
        </a>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Six steps do not fit a phone's width; scroll the bar, not the page. */}
      <div className="overflow-x-auto">
        <ul className="steps w-full" data-testid="ynab-steps">
          {STEPS.map((item, index) => (
            <li key={item.key} className={`step ${index <= step ? 'step-primary' : ''}`}>
              <span className="text-xs">{item.label}</span>
            </li>
          ))}
        </ul>
      </div>

      <div className="app-card">
        {current.key === 'upload' && <Step1Upload onUpload={upload} busy={busy} error={error} />}

        {current.key === 'accounts' && (
          <Step2Accounts
            accounts={analysis.accounts}
            groups={analysis.groups}
            choices={choices.accounts}
            onChange={(accounts) => setChoices({ ...choices, accounts })}
            extraGroups={extraGroups}
            onExtraGroupsChange={setExtraGroups}
          />
        )}

        {current.key === 'income' && (
          <Step3Income
            income={analysis.income}
            suggestions={analysis.income_accounts}
            otherIncome={analysis.other_income}
            choices={choices.income}
            onChange={(income) => setChoices({ ...choices, income })}
            extraAccounts={extraIncomeAccounts}
            onExtraAccountsChange={setExtraIncomeAccounts}
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
          <Step6Apply status={status} urls={{ homeUrl, accountsUrl, budgetUrl, goalsUrl }} onRetry={startOver} />
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

      <Modal
        open={leaveTo !== null}
        onClose={() => setLeaveTo(null)}
        title={gettext('Leave the import?')}
        size="sm"
        testId="ynab-leave-dialog"
        actions={
          <>
            <button type="button" className="btn btn-ghost" onClick={leave} data-testid="ynab-leave-confirm">
              {gettext('Leave without importing')}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => setLeaveTo(null)}
              ref={keepGoingRef}
              data-testid="ynab-leave-cancel"
            >
              {gettext('Keep going')}
            </button>
          </>
        }
      >
        <p className="text-base-content/70">
          {gettext(
            'Nothing has been imported yet, and the choices you made on these screens are not saved. If you leave now, you will start again by uploading your export.',
          )}
        </p>
      </Modal>
    </div>
  );
};

export default YnabImportWizard;
