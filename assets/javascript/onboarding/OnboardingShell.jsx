/* globals gettext */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import CoaReview from './CoaReview';
import GoalCard from './GoalCard';
import QuestionCard from './QuestionCard';

/**
 * The guided-onboarding takeover: welcome, then one question per screen.
 *
 * The question set comes from the server's catalog, so this component never names
 * a question. It knows about *kinds* and *phases*, both of which are data.
 *
 * Motion follows docs/onboarding-walkthrough-plan.md §6.2: transitions are opacity
 * and transform only (no layout-triggering properties), and every one of them is
 * reduced to a short fade under `prefers-reduced-motion`, which lives in the CSS
 * rather than here.
 */

const STEP_MS = 260;

const NO_EDITS = { removed: [], renamed: {}, added: [] };

const isAnswered = (question, value) => {
  if (question.options.length > 0) {
    return Array.isArray(value) ? value.length > 0 : Boolean(value);
  }
  return true; // free-text and currency questions are never blocking
};

const OnboardingShell = ({ props }) => {
  const { questions, phases, state, teamName, firstName, urls, homeUrl, api } = props;

  const [answers, setAnswers] = useState(() => state.answers || {});
  const [started, setStarted] = useState(() => state.phase !== 'welcome');
  const [index, setIndex] = useState(0);
  const [direction, setDirection] = useState('forward');
  const [leaving, setLeaving] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [mounted, setMounted] = useState(false);

  // Phase C: the generated chart of accounts, and the user's edits to it as a
  // diff the server can apply to its own generated set.
  const [reviewing, setReviewing] = useState(() => state.phase === 'review');
  const [sections, setSections] = useState([]);
  const [edits, setEdits] = useState(NO_EDITS);
  const [previewing, setPreviewing] = useState(false);

  // Resuming mid-flow: pick up at the first question of the phase the server
  // last recorded, rather than restarting the questionnaire.
  useEffect(() => {
    if (state.phase === 'review') loadPreview(NO_EDITS);
    // Once, on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!state.question_phase) return;
    const resumeAt = questions.findIndex((q) => q.phase === state.question_phase);
    if (resumeAt > 0) setIndex(resumeAt);
    // Deliberately once, on mount: after that the user drives the position.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    // One frame after mount so the entry transition has a state to animate from.
    const id = requestAnimationFrame(() => setMounted(true));
    return () => cancelAnimationFrame(id);
  }, []);

  const question = questions[index];
  const isLast = index === questions.length - 1;
  const answeredHere = question ? isAnswered(question, answers[question.id]) : true;
  const canContinue = !question?.required || answeredHere;

  const phaseIndex = useMemo(
    () => phases.findIndex((p) => p.key === question?.phase),
    [phases, question],
  );

  const setAnswer = useCallback(
    (value) => setAnswers((prev) => ({ ...prev, [question.id]: value })),
    [question],
  );

  // Save quietly in the background. A failed save must not block the user --
  // every answer is posted again with the final submit, so the worst case is
  // that resuming loses a few answers, not that the flow stalls.
  const persist = useRef(null);
  const savePhase = useCallback(
    (nextPhase) => {
      clearTimeout(persist.current);
      persist.current = setTimeout(() => {
        api.saveAnswers(answers, nextPhase).catch(() => {});
      }, 150);
    },
    [api, answers],
  );

  const step = useCallback(
    (delta) => {
      const next = index + delta;
      if (next < 0 || next >= questions.length) return;

      setDirection(delta > 0 ? 'forward' : 'back');
      setLeaving(true);
      setTimeout(() => {
        setIndex(next);
        setLeaving(false);
        savePhase(questions[next].phase);
      }, STEP_MS);
    },
    [index, questions, savePhase],
  );

  const loadPreview = useCallback(
    async (nextEdits) => {
      setPreviewing(true);
      setError(null);
      try {
        const result = await api.previewCoa(answers, nextEdits);
        setSections(result.sections);
      } catch (e) {
        // A rejected edit (a duplicate name, say) leaves the previous list on
        // screen with the reason above it, rather than blanking the review.
        setError(e.message);
      } finally {
        setPreviewing(false);
      }
    },
    [api, answers],
  );

  const openReview = useCallback(() => {
    // Edits reset on every entry to review. They are keyed by the generated
    // account's name, and going back to change an answer can remove the very
    // account a rename referred to -- carrying them forward would silently apply
    // a rename to nothing, or to a different account that happens to share a name.
    setReviewing(true);
    setEdits(NO_EDITS);
    loadPreview(NO_EDITS);
  }, [loadPreview]);

  const changeEdits = useCallback(
    (next) => {
      setEdits(next);
      loadPreview(next);
    },
    [loadPreview],
  );

  const finish = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const { redirect } = await api.complete(answers, edits);
      window.location.href = redirect || homeUrl;
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }, [api, answers, edits, homeUrl]);

  const skip = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const { redirect } = await api.skip();
      window.location.href = redirect || homeUrl;
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }, [api, homeUrl]);

  // Enter advances, so a keyboard user never has to reach for the mouse.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== 'Enter' || busy || !started) return;
      if (e.target.tagName === 'INPUT' && e.target.type === 'date') return;
      if (reviewing) {
        // Enter is how a user commits a rename; it must not also submit the flow.
        if (e.target.tagName === 'INPUT') return;
        e.preventDefault();
        finish();
        return;
      }
      if (!canContinue) return;
      e.preventDefault();
      isLast ? openReview() : step(1);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [busy, started, canContinue, isLast, reviewing, finish, openReview, step]);

  const greeting = firstName
    ? gettext('Welcome, {name}').replace('{name}', firstName)
    : gettext('Welcome to Koala Budget');

  return (
    <div className={`onboarding-backdrop ${mounted ? 'is-open' : ''}`} data-testid="onboarding-takeover">
      <div className="onboarding-panel app-card" role="dialog" aria-modal="true" aria-label={greeting}>
        {!started ? (
          <div className="onboarding-question" data-testid="onboarding-welcome">
            <p className="text-sm font-semibold uppercase tracking-[0.08em] text-base-content/70">
              {teamName}
            </p>
            <h1 className="mt-2 text-[1.75rem] font-semibold tracking-tight">{greeting}</h1>
            <p className="mt-3 max-w-prose text-base-content/70">
              {gettext(
                'A few quick questions and we’ll set up a chart of accounts that matches your life. It takes about a minute, and you can change anything later.',
              )}
            </p>
            <div className="mt-7 flex flex-wrap items-center gap-3">
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => {
                  setStarted(true);
                  savePhase(questions[0]?.phase);
                }}
                data-testid="onboarding-start"
              >
                {gettext('Set up my books')}
              </button>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={skip}
                disabled={busy}
                data-testid="onboarding-skip"
              >
                {gettext('Skip for now')}
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="onboarding-progress" aria-hidden="true">
              {phases.map((phase, i) => (
                <span
                  key={phase.key}
                  className={`onboarding-dot ${reviewing || i <= phaseIndex ? 'is-filled' : ''}`}
                  title={phase.label}
                />
              ))}
              <span
                className={`onboarding-dot ${reviewing ? 'is-filled' : ''}`}
                title={gettext('Your accounts')}
              />
            </div>

            {reviewing ? (
              <div className="onboarding-step is-entering-forward">
                <CoaReview
                  sections={sections}
                  edits={edits}
                  onEditsChange={changeEdits}
                  loading={previewing && sections.length === 0}
                  error={error}
                />
              </div>
            ) : (
              <>
                <div
                  key={question.id}
                  className={`onboarding-step ${leaving ? `is-leaving-${direction}` : `is-entering-${direction}`}`}
                >
                  {question.kind === 'goal' ? (
                    <GoalCard question={question} value={answers[question.id]} onChange={setAnswer} />
                  ) : (
                    <QuestionCard question={question} value={answers[question.id]} onChange={setAnswer} />
                  )}
                </div>

                {error && (
                  <div className="alert alert-error mt-4" data-testid="onboarding-error">
                    <span>{error}</span>
                  </div>
                )}
              </>
            )}

            <div className="onboarding-actions">
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => (reviewing ? setReviewing(false) : step(-1))}
                disabled={(!reviewing && index === 0) || busy}
                data-testid="onboarding-back"
              >
                {gettext('Back')}
              </button>

              <span className="text-sm text-base-content/70">
                {reviewing
                  ? gettext('Last step')
                  : gettext('{current} of {total}')
                      .replace('{current}', index + 1)
                      .replace('{total}', questions.length)}
              </span>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={skip}
                  disabled={busy}
                  data-testid="onboarding-skip"
                >
                  {gettext('Skip setup')}
                </button>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => {
                    if (reviewing) return finish();
                    return isLast ? openReview() : step(1);
                  }}
                  disabled={(!reviewing && !canContinue) || busy}
                  data-testid="onboarding-continue"
                >
                  {busy && <span className="loading loading-spinner loading-xs"></span>}
                  {reviewing
                    ? gettext('Create my accounts')
                    : isLast
                      ? gettext('Review my accounts')
                      : gettext('Continue')}
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default OnboardingShell;
