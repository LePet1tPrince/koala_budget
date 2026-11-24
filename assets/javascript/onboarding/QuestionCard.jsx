/* globals gettext */

import React from 'react';

import AmountInput from '../common/AmountInput';
import Icon from '../common/Icon';

/**
 * One question, rendered from its catalog entry.
 *
 * Deliberately generic: it switches on `kind`, never on a question id, so adding
 * or cutting a question in `apps/onboarding/questions.py` needs no change here.
 *
 * Props:
 * - question: a catalog entry ({ id, prompt, helpText, kind, options, required })
 * - value: the current answer (array for multi, string for single, string for currency)
 * - onChange: (value) => void
 */

const OptionButton = ({ option, selected, multi, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    aria-pressed={selected}
    data-testid={`option-${option.value}`}
    className={`onboarding-option ${selected ? 'onboarding-option-selected' : ''}`}
  >
    {/* Square for "pick any", round for "pick one": the convention people already read. */}
    <span className={`onboarding-option-mark ${multi ? 'onboarding-option-mark-multi' : ''}`} aria-hidden="true">
      {selected && <Icon name="check" className="inline-block shrink-0 w-4 h-4" />}
    </span>
    <span className="min-w-0">
      <span className="block">{option.label}</span>
      {option.helpText && <span className="block text-sm text-base-content/70">{option.helpText}</span>}
    </span>
  </button>
);

const QuestionCard = ({ question, value, onChange }) => {
  const isMulti = question.kind === 'multi';
  const selected = isMulti ? (Array.isArray(value) ? value : []) : value;

  const toggle = (optionValue) => {
    if (!isMulti) {
      onChange(optionValue);
      return;
    }

    const current = Array.isArray(value) ? value : [];
    const isCatchAll = question.options.find((o) => o.value === optionValue)?.catchAll;

    if (current.includes(optionValue)) {
      onChange(current.filter((v) => v !== optionValue));
      return;
    }

    // "None of these" and the other options are mutually exclusive: picking a
    // catch-all clears the rest, and picking anything else clears the catch-all.
    // Without this a user can answer "None of these, and also a student loan".
    const catchAllValues = question.options.filter((o) => o.catchAll).map((o) => o.value);
    const next = isCatchAll ? [optionValue] : [...current.filter((v) => !catchAllValues.includes(v)), optionValue];

    onChange(next);
  };

  return (
    <div className="onboarding-question" data-testid={`onboarding-question-${question.id}`}>
      <h2 className="text-xl font-semibold tracking-tight">{question.prompt}</h2>
      {question.helpText && <p className="mt-1 text-sm text-base-content/70">{question.helpText}</p>}

      {question.options.length > 0 && (
        <div className="mt-5 grid gap-2 sm:grid-cols-2">
          {question.options.map((option) => (
            <OptionButton
              key={option.value}
              option={option}
              selected={isMulti ? selected.includes(option.value) : selected === option.value}
              multi={isMulti}
              onClick={() => toggle(option.value)}
            />
          ))}
        </div>
      )}

      {question.kind === 'currency' && (
        <label className="mt-5 flex max-w-xs items-center gap-2">
          <span className="text-base-content/70">$</span>
          <AmountInput
            className="input input-bordered w-full money"
            placeholder="0.00"
            value={value}
            onValueChange={onChange}
            data-testid={`input-${question.id}`}
          />
          <span className="text-sm text-base-content/70">{gettext('CAD')}</span>
        </label>
      )}

      {question.kind === 'text' && (
        <input
          type="text"
          className="input input-bordered mt-5 w-full max-w-md"
          value={value ?? ''}
          onChange={(e) => onChange(e.target.value)}
          data-testid={`input-${question.id}`}
        />
      )}
    </div>
  );
};

export default QuestionCard;
