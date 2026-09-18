import React, { useEffect, useState } from 'react';

import BaselineBar from './BaselineBar';
import Dashboard from './Dashboard';
import StepBiggest from './steps/StepBiggest';
import StepBreakdown from './steps/StepBreakdown';
import StepGlance from './steps/StepGlance';
import StepHealth from './steps/StepHealth';
import StepIncome from './steps/StepIncome';
import StepNetWorth from './steps/StepNetWorth';
import StepOverspent from './steps/StepOverspent';
import StepRecap from './steps/StepRecap';
import StepSaving from './steps/StepSaving';

const STEPS = [
  { key: 'health', Component: StepHealth, title: "Is this month's data complete?" },
  { key: 'glance', Component: StepGlance, title: 'The month at a glance' },
  { key: 'income', Component: StepIncome, title: 'Where the money came from' },
  { key: 'overspent', Component: StepOverspent, title: 'What blew through the budget' },
  { key: 'biggest', Component: StepBiggest, title: 'The biggest line items' },
  { key: 'breakdown', Component: StepBreakdown, title: 'The whole breakdown' },
  { key: 'saving', Component: StepSaving, title: 'What we put away' },
  { key: 'networth', Component: StepNetWorth, title: 'What it all adds up to' },
  { key: 'recap', Component: StepRecap, title: "That's the month" },
];

/**
 * Owns { mode, step, baseline } over one already-fetched `review` payload.
 * Both the walkthrough and the dashboard render from the same data -- changing
 * the baseline is pure client-side reslicing, never a new request.
 */
const ReviewApp = ({ props }) => {
  const { review, state, urls, api } = props;
  const [mode, setMode] = useState(state.isFinished ? 'dashboard' : 'walkthrough');
  const [step, setStep] = useState(Math.min(state.step || 0, STEPS.length - 1));
  const [baseline, setBaseline] = useState(
    state.baseline && review.baselines[state.baseline] ? state.baseline : review.default_baseline
  );

  const currentBaseline = baseline ? review.baselines[baseline] : null;

  const goToStep = (next) => {
    const clamped = Math.max(0, Math.min(STEPS.length - 1, next));
    setStep(clamped);
    api.step(clamped, baseline).catch(() => {});
  };

  const changeBaseline = (id) => {
    setBaseline(id);
    api.step(step, id).catch(() => {});
  };

  const finishWalkthrough = () => {
    api.complete().catch(() => {});
    setMode('dashboard');
  };

  useEffect(() => {
    if (mode !== 'walkthrough') return undefined;
    const onKeyDown = (e) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.key === 'ArrowRight') goToStep(step + 1);
      if (e.key === 'ArrowLeft') goToStep(step - 1);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, step, baseline]);

  if (mode === 'dashboard') {
    return (
      <Dashboard
        review={review}
        baselines={review.baselines}
        baselineOrder={review.baseline_order}
        baseline={baseline}
        currentBaseline={currentBaseline}
        onBaselineChange={changeBaseline}
        onWalkthrough={() => {
          setStep(0);
          setMode('walkthrough');
        }}
        urls={urls}
      />
    );
  }

  const { Component, title } = STEPS[step];
  const showBaselineBar = step >= 1 && step <= 7 && review.baseline_order.length > 0;

  return (
    <div className="max-w-4xl mx-auto py-6" data-testid="monthly-review-walkthrough">
      <div className="flex items-center justify-between mb-4">
        <div className="flex gap-2" data-testid="step-dots">
          {STEPS.map((s, i) => (
            <button
              key={s.key}
              type="button"
              aria-label={s.title}
              className={`w-2.5 h-2.5 rounded-full ${i === step ? 'bg-primary' : 'bg-base-300'}`}
              onClick={() => goToStep(i)}
              data-testid={`step-dot-${i}`}
            />
          ))}
        </div>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() => setMode('dashboard')}
          data-testid="skip-to-dashboard"
        >
          Skip to dashboard
        </button>
      </div>

      <h1 className="text-2xl font-semibold mb-4">{title}</h1>

      {showBaselineBar && (
        <div className="mb-4">
          <BaselineBar
            baselines={review.baselines}
            order={review.baseline_order}
            value={baseline}
            onChange={changeBaseline}
          />
        </div>
      )}

      <Component review={review} baseline={currentBaseline} onFinish={finishWalkthrough} />

      <div className="flex justify-between mt-6">
        <button
          type="button"
          className="btn btn-outline"
          disabled={step === 0}
          onClick={() => goToStep(step - 1)}
          data-testid="step-back"
        >
          Back
        </button>
        {step < STEPS.length - 1 ? (
          <button type="button" className="btn btn-primary" onClick={() => goToStep(step + 1)} data-testid="step-next">
            Next
          </button>
        ) : (
          <button type="button" className="btn btn-primary" onClick={finishWalkthrough} data-testid="step-finish">
            Open the month dashboard &rarr;
          </button>
        )}
      </div>
    </div>
  );
};

export default ReviewApp;
