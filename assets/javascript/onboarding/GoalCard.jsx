/* globals gettext */

import React from 'react';

/**
 * The optional first-goal question.
 *
 * A composite answer rather than an option pick, so it gets its own component
 * instead of bending QuestionCard's option grid around it. Every field is
 * optional -- leaving the name blank is how the user skips it, and the server
 * creates nothing.
 */
const GoalCard = ({ question, value, onChange }) => {
  const goal = value && typeof value === 'object' ? value : {};
  const set = (key) => (e) => onChange({ ...goal, [key]: e.target.value });

  return (
    <div className="onboarding-question" data-testid={`onboarding-question-${question.id}`}>
      <h2 className="text-xl font-semibold tracking-tight">{question.prompt}</h2>
      {question.help_text && (
        <p className="mt-1 text-sm text-base-content/70">{question.help_text}</p>
      )}

      <div className="mt-5 grid gap-3 sm:grid-cols-2">
        <label className="sm:col-span-2">
          <span className="mb-1 block text-sm text-base-content/70">{gettext('What for?')}</span>
          <input
            type="text"
            className="input input-bordered w-full"
            placeholder={gettext('Emergency fund')}
            value={goal.name ?? ''}
            onChange={set('name')}
            data-testid="goal-name"
          />
        </label>

        <label>
          <span className="mb-1 block text-sm text-base-content/70">{gettext('Target amount')}</span>
          <input
            type="number"
            inputMode="decimal"
            min="0"
            step="0.01"
            className="input input-bordered money w-full"
            placeholder="0.00"
            value={goal.target_amount ?? ''}
            onChange={set('target_amount')}
            data-testid="goal-amount"
          />
        </label>

        <label>
          <span className="mb-1 block text-sm text-base-content/70">
            {gettext('By when?')} <span className="text-base-content/45">{gettext('(optional)')}</span>
          </span>
          <input
            type="date"
            className="input input-bordered w-full"
            value={goal.target_date ?? ''}
            onChange={set('target_date')}
            data-testid="goal-date"
          />
        </label>
      </div>
    </div>
  );
};

export default GoalCard;
