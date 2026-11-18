import React, { useState } from 'react';

import Combobox from '../common/Combobox';
import Icon from '../common/Icon';
import { AccountFilter, Dropdown, MenuRow } from '../bank_feed/react/LineTableParts';
import { AMOUNT_OPS, TEXT_OPS, opLabel } from './summary';

/* globals gettext, interpolate */

/**
 * A rule as one plain sentence the user edits in place:
 *
 *   When a [money-out transaction] in the [any account] feed has [description] [contains] [insurance]
 *   [and] [amount] [is more than] [120] (+), [suggest it as] [Car Insurance].
 *
 * Every bracketed part is a control: a menu, a text field, or the category picker.
 * (+) adds a condition; a rename ("and set the payee to …") is added the same way.
 * It edits the same rule object the API takes -- only the presentation is a sentence.
 */

// A part of the sentence the user can change: underlined, tinted, still reads as text.
const TOKEN =
  'inline-flex items-center gap-0.5 rounded-md border-b-2 border-dashed border-primary/50 bg-primary/5 ' +
  'px-1.5 py-0.5 font-medium text-primary transition-colors hover:bg-primary/10 ' +
  'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary';

const TOKEN_INPUT =
  'rounded-md border-b-2 border-dashed border-primary/50 bg-primary/5 px-1.5 py-0.5 font-medium text-primary ' +
  'placeholder:font-normal placeholder:text-primary/50 focus:border-solid focus:bg-base-100 focus:outline-none';

const Caret = () => (
  <svg className="h-3 w-3 opacity-60" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
    <path d="M5.5 7.5 10 12l4.5-4.5h-9Z" />
  </svg>
);

/** A menu in the sentence: shows the chosen option's words, opens the others. */
function ChoiceToken({ value, options, onChange, ariaLabel, testId }) {
  const [open, setOpen] = useState(false);
  const current = options.find((o) => o.value === value) ?? options[0];
  return (
    <Dropdown
      open={open}
      onOpenChange={setOpen}
      trigger={({ toggle, open: isOpen }) => (
        <button
          type="button"
          className={TOKEN}
          aria-haspopup="menu"
          aria-expanded={isOpen}
          aria-label={`${ariaLabel}: ${current.label}`}
          onClick={toggle}
          data-testid={testId}
        >
          {current.label}
          <Caret />
        </button>
      )}
    >
      {({ close }) =>
        options.map((o) => (
          <MenuRow
            key={o.value}
            label={o.label}
            checked={o.value === value}
            disabled={o.disabled}
            testId={testId ? `${testId}-${o.value}` : undefined}
            onClick={() => {
              onChange(o.value);
              close();
            }}
          />
        ))
      }
    </Dropdown>
  );
}

/** A value typed into the sentence; grows with what is typed. */
function TextToken({ value, onChange, placeholder, ariaLabel, testId, numeric = false, maxLength = 255 }) {
  const shown = String(value ?? '') || placeholder || '';
  return (
    <input
      type="text"
      inputMode={numeric ? 'decimal' : 'text'}
      className={TOKEN_INPUT}
      style={{ width: `calc(${Math.max(numeric ? 4 : 6, shown.length + 1)}ch + 1rem)` }}
      value={value ?? ''}
      placeholder={placeholder}
      maxLength={maxLength}
      aria-label={ariaLabel}
      onChange={(e) => onChange(e.target.value)}
      data-testid={testId}
    />
  );
}

/** The small round + / × buttons inside the sentence. */
function IconButton({ icon, label, onClick, testId }) {
  return (
    <button
      type="button"
      className="btn btn-ghost btn-xs btn-circle text-base-content/70 hover:text-primary"
      onClick={onClick}
      aria-label={label}
      title={label}
      data-testid={testId}
    >
      <Icon name={icon} className="h-3.5 w-3.5" />
    </button>
  );
}

// Restyles the shared Combobox's input as a sentence token.
const COMBO_AS_TOKEN =
  '[&_.input]:rounded-md! [&_.input]:border-0! [&_.input]:border-b-2! [&_.input]:border-dashed! ' +
  '[&_.input]:border-primary/50! [&_.input]:bg-primary/5! [&_.input]:font-medium! [&_.input]:text-primary! ' +
  '[&_.input]:shadow-none! [&_.input]:outline-none! [&_.input:focus-within]:border-solid! ' +
  '[&_.input:focus-within]:bg-base-100! [&_input::placeholder]:font-normal! [&_input::placeholder]:text-primary/50! ' +
  '[&_.input]:text-base! [&_.input]:h-8! [&_.input]:px-1.5!';

/** The category picker, styled and sized to sit in a line of text. */
function CategoryToken({ value, options, onChange, testId, minWidth = 12 }) {
  const chars = Math.max(minWidth, (value?.label ?? '').length + 5, 18);
  return (
    <span className={`inline-block max-w-full align-middle ${COMBO_AS_TOKEN}`} style={{ width: `${chars}ch` }}>
      <Combobox
        ariaLabel={gettext('Category')}
        value={value}
        onChange={onChange}
        options={options}
        getGroup={(o) => o.groupLabel}
        placeholder={gettext('pick a category')}
        size="sm"
        testId={testId}
      />
    </span>
  );
}

const DIRECTIONS = [
  { value: 'any', label: gettext('transaction') },
  { value: 'out', label: gettext('money-out transaction') },
  { value: 'in', label: gettext('money-in transaction') },
];

const FIELDS = [
  { value: 'payee', label: gettext('payee') },
  { value: 'description', label: gettext('description') },
  { value: 'amount', label: gettext('amount') },
];

const MATCHES = [
  { value: 'all', label: gettext('and') },
  { value: 'any', label: gettext('or') },
];

// The category picker's own entries for the two actions that are not "one category".
const SPLIT_OPTION = { id: '__split', label: gettext('a split between categories…'), groupLabel: gettext('Other') };
const RENAME_OPTION = { id: '__rename', label: gettext('nothing — only rename it'), groupLabel: gettext('Other') };

const accountsLabel = (selected, accounts) => {
  if (selected.length === 0) return gettext('any account');
  const names = selected.map((id) => accounts.find((a) => a.id === id)?.name ?? '?');
  if (names.length <= 2) return names.join(` ${gettext('or')} `);
  return interpolate(gettext('%s accounts'), [names.length]);
};

function Condition({ condition, index, onChange, onRemove, trailing = null }) {
  const ops = (condition.field === 'amount' ? AMOUNT_OPS : TEXT_OPS).map((op) => ({ value: op, label: opLabel(op) }));
  const setField = (field) => {
    const nextOps = field === 'amount' ? AMOUNT_OPS : TEXT_OPS;
    const op = nextOps.includes(condition.op) ? condition.op : nextOps[0];
    onChange({ field, op, value: op === 'between' ? ['', ''] : '' });
  };
  const setOp = (op) =>
    onChange({
      ...condition,
      op,
      value: op === 'between' ? ['', ''] : Array.isArray(condition.value) ? '' : condition.value,
    });
  const amount = condition.field === 'amount';
  // The × (and, on the last condition, the +) stay on the line of the value they belong to.
  const tail = (
    <>
      <IconButton icon="close" label={gettext('Remove this condition')} onClick={onRemove} />
      {trailing}
    </>
  );
  return (
    <span className="inline-flex flex-wrap items-center gap-1" data-testid={`rule-condition-${index}`}>
      <ChoiceToken
        value={condition.field}
        options={FIELDS}
        onChange={setField}
        ariaLabel={gettext('Field')}
        testId={`rule-condition-field-${index}`}
      />
      <ChoiceToken
        value={condition.op}
        options={ops}
        onChange={setOp}
        ariaLabel={gettext('Comparison')}
        testId={`rule-condition-op-${index}`}
      />
      {condition.op === 'between' ? (
        <>
          <span className="text-base-content/70">$</span>
          <TextToken
            numeric
            value={condition.value?.[0]}
            placeholder="0.00"
            ariaLabel={gettext('Lowest amount')}
            onChange={(v) => onChange({ ...condition, value: [v, condition.value?.[1] ?? ''] })}
            testId={`rule-condition-low-${index}`}
          />
          {gettext('and')}
          <span className="inline-flex items-center gap-1 whitespace-nowrap">
            <span className="text-base-content/70">$</span>
            <TextToken
              numeric
              value={condition.value?.[1]}
              placeholder="0.00"
              ariaLabel={gettext('Highest amount')}
              onChange={(v) => onChange({ ...condition, value: [condition.value?.[0] ?? '', v] })}
              testId={`rule-condition-high-${index}`}
            />
            {tail}
          </span>
        </>
      ) : (
        <span className="inline-flex items-center gap-1 whitespace-nowrap">
          {amount && <span className="text-base-content/70">$</span>}
          <TextToken
            numeric={amount}
            value={condition.value}
            placeholder={amount ? '0.00' : gettext('some text')}
            ariaLabel={gettext('Value')}
            onChange={(v) => onChange({ ...condition, value: v })}
            testId={`rule-condition-value-${index}`}
          />
          {tail}
        </span>
      )}
    </span>
  );
}

function Splits({ splits, onChange, options, optionsById, onUnsplit }) {
  const total = splits.reduce((n, s) => n + (Number(s.percent) || 0), 0);
  const balanced = Math.abs(total - 100) < 0.0005;
  return (
    <>
      {splits.map((split, i) => (
        <span key={i} className="inline-flex flex-wrap items-center gap-1" data-testid={`rule-split-${i}`}>
          {i > 0 && <span>+</span>}
          <span className="inline-flex items-center gap-0.5 whitespace-nowrap">
            <TextToken
              numeric
              value={split.percent}
              placeholder="50"
              ariaLabel={gettext('Percent')}
              onChange={(v) => onChange(splits.map((s, j) => (j === i ? { ...s, percent: v } : s)))}
            />
            <span>%</span>
          </span>
          <CategoryToken
            minWidth={10}
            value={optionsById.get(split.category) ?? null}
            options={options}
            onChange={(o) => onChange(splits.map((s, j) => (j === i ? { ...s, category: o?.id ?? null } : s)))}
          />
          {splits.length > 2 && (
            <IconButton
              icon="close"
              label={gettext('Remove this part')}
              onClick={() => onChange(splits.filter((_s, j) => j !== i))}
            />
          )}
        </span>
      ))}
      <IconButton
        icon="plus"
        label={gettext('Add a part')}
        onClick={() => onChange([...splits, { category: null, percent: '' }])}
      />
      <span className={`text-sm ${balanced ? 'text-success' : 'text-warning'}`} data-testid="rule-split-total">
        {interpolate(gettext('(%s%)'), [Number(total.toFixed(3))])}
      </span>
      <button type="button" className="link link-hover text-sm text-base-content/70" onClick={onUnsplit}>
        {gettext('don’t split')}
      </button>
    </>
  );
}

/** "+ rename": adds a clause that renames the payee or the description. */
function AddRename({ options, onPick }) {
  const [open, setOpen] = useState(false);
  return (
    <Dropdown
      open={open}
      onOpenChange={setOpen}
      trigger={({ toggle, open: isOpen }) => (
        <button
          type="button"
          className="btn btn-ghost btn-xs gap-1 font-normal text-base-content/70"
          aria-haspopup="menu"
          aria-expanded={isOpen}
          onClick={toggle}
          data-testid="rule-add-rename"
        >
          <Icon name="plus" className="h-3.5 w-3.5" />
          {gettext('rename')}
        </button>
      )}
    >
      {({ close }) =>
        options.map((o) => (
          <MenuRow
            key={o.value}
            label={o.label}
            testId={`rule-add-rename-${o.value}`}
            onClick={() => {
              onPick(o.value);
              close();
            }}
          />
        ))
      }
    </Dropdown>
  );
}

export default function RuleSentence({ rule, set, categoryOptions, feedAccounts, feedIds }) {
  // A rename clause shows once it has text, or once the user asked for it.
  const [renames, setRenames] = useState(() => ({ payee: !!rule.payee_name, description: !!rule.description }));
  const showPayee = renames.payee || !!rule.payee_name;
  const showDescription = renames.description || !!rule.description;

  const isTransfer = rule.action === 'category' && feedIds.has(rule.category);
  const renameOnly = rule.action === 'rename';

  const setCondition = (i, next) => set({ conditions: rule.conditions.map((c, j) => (j === i ? next : c)) });
  const addCondition = () =>
    set({ conditions: [...rule.conditions, { field: 'description', op: 'contains', value: '' }] });

  const pickCategory = (option) => {
    if (option?.id === SPLIT_OPTION.id) {
      set({
        action: 'split',
        splits: rule.splits?.length
          ? rule.splits
          : [
              { category: rule.category, percent: '50' },
              { category: null, percent: '50' },
            ],
      });
      return;
    }
    if (option?.id === RENAME_OPTION.id) {
      set({ action: 'rename', mode: 'suggest' });
      if (!showPayee && !showDescription) setRenames((r) => ({ ...r, payee: true }));
      return;
    }
    const id = option?.id ?? null;
    // A transfer is only ever suggested: picking one turns auto-post off.
    set({ action: 'category', category: id, ...(id != null && feedIds.has(id) ? { mode: 'suggest' } : {}) });
  };

  // In a sentence an option reads as its name ("Car Insurance"), not "Living - Car Insurance".
  const named = categoryOptions.map((o) => ({ ...o, label: o.name }));
  const namedById = new Map(named.map((o) => [o.id, o]));
  const categoryChoices = [...named, SPLIT_OPTION, RENAME_OPTION];
  const splitChoices = named.filter((o) => !feedIds.has(o.id));
  const verbs = [
    { value: 'suggest', label: gettext('suggest it as') },
    { value: 'auto_post', label: gettext('post it as'), disabled: isTransfer },
  ];

  const renameMenu = [
    !showPayee && { value: 'payee', label: gettext('set the payee') },
    !showDescription && { value: 'description', label: gettext('set the description') },
  ].filter(Boolean);

  return (
    <div className="space-y-2">
      <div
        className="flex flex-wrap items-center gap-x-1.5 gap-y-2 text-base leading-relaxed"
        data-testid="rule-sentence"
      >
        <span>{gettext('When a')}</span>
        <ChoiceToken
          value={rule.direction}
          options={DIRECTIONS}
          onChange={(direction) => set({ direction })}
          ariaLabel={gettext('Direction')}
          testId="rule-direction"
        />
        <span>{gettext('in the')}</span>
        <AccountFilter
          accounts={feedAccounts}
          selected={rule.accounts}
          onChange={(accounts) => set({ accounts })}
          testId="rule-accounts"
          triggerClassName={TOKEN}
          formatLabel={accountsLabel}
        />
        <span>{gettext('feed has')}</span>

        {rule.conditions.length === 0 ? (
          <button type="button" className={TOKEN} onClick={addCondition} data-testid="rule-add-condition">
            <Icon name="plus" className="h-3.5 w-3.5" />
            {gettext('a condition')}
          </button>
        ) : (
          <>
            {rule.conditions.map((condition, i) => (
              <React.Fragment key={i}>
                {i > 0 && (
                  <ChoiceToken
                    value={rule.match}
                    options={MATCHES}
                    onChange={(match) => set({ match })}
                    ariaLabel={gettext('How conditions combine')}
                    testId={`rule-match-${i}`}
                  />
                )}
                <Condition
                  condition={condition}
                  index={i}
                  onChange={(next) => setCondition(i, next)}
                  onRemove={() => set({ conditions: rule.conditions.filter((_c, j) => j !== i) })}
                  trailing={
                    i === rule.conditions.length - 1 ? (
                      <IconButton
                        icon="plus"
                        label={gettext('Add a condition')}
                        onClick={addCondition}
                        testId="rule-add-condition"
                      />
                    ) : null
                  }
                />
              </React.Fragment>
            ))}
          </>
        )}

        <span>{gettext('then')}</span>
        {renameOnly ? null : (
          <ChoiceToken
            value={rule.mode}
            options={verbs}
            onChange={(mode) => set({ mode })}
            ariaLabel={gettext('When it matches')}
            testId="rule-mode"
          />
        )}

        {rule.action === 'split' ? (
          <Splits
            splits={rule.splits || []}
            onChange={(splits) => set({ splits })}
            options={splitChoices}
            optionsById={namedById}
            onUnsplit={() => set({ action: 'category', category: rule.splits?.[0]?.category ?? null })}
          />
        ) : (
          <CategoryToken
            value={namedById.get(rule.category) ?? null}
            options={categoryChoices}
            onChange={pickCategory}
            testId="rule-category"
          />
        )}

        {showPayee && (
          <span className="inline-flex flex-wrap items-center gap-1" data-testid="rule-rename-payee">
            <span>{renameOnly ? gettext('set the payee to') : gettext('and set the payee to')}</span>
            <TextToken
              value={rule.payee_name}
              placeholder={gettext('a new payee')}
              maxLength={200}
              ariaLabel={gettext('New payee')}
              onChange={(payee_name) => set({ payee_name })}
              testId="rule-payee"
            />
            <IconButton
              icon="close"
              label={gettext('Keep the bank’s payee')}
              onClick={() => {
                set({ payee_name: '' });
                setRenames((r) => ({ ...r, payee: false }));
              }}
            />
          </span>
        )}
        {showDescription && (
          <span className="inline-flex flex-wrap items-center gap-1" data-testid="rule-rename-description">
            <span>
              {renameOnly && !showPayee ? gettext('set the description to') : gettext('and set the description to')}
            </span>
            <TextToken
              value={rule.description}
              placeholder={gettext('a new description')}
              ariaLabel={gettext('New description')}
              onChange={(description) => set({ description })}
              testId="rule-description"
            />
            <IconButton
              icon="close"
              label={gettext('Keep the bank’s description')}
              onClick={() => {
                set({ description: '' });
                setRenames((r) => ({ ...r, description: false }));
              }}
            />
          </span>
        )}
        {renameOnly && (
          <button
            type="button"
            className="btn btn-ghost btn-xs gap-1 font-normal text-base-content/70"
            onClick={() => set({ action: 'category' })}
            data-testid="rule-categorize-too"
          >
            <Icon name="plus" className="h-3.5 w-3.5" />
            {gettext('categorize it too')}
          </button>
        )}
        {renameMenu.length > 0 && (
          <AddRename options={renameMenu} onPick={(which) => setRenames((r) => ({ ...r, [which]: true }))} />
        )}
      </div>
      {isTransfer && (
        <p className="text-xs text-base-content/70">
          {gettext('This is a transfer to another bank account, so it is only ever suggested, never posted twice.')}
        </p>
      )}
    </div>
  );
}
