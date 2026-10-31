import React, { useEffect, useMemo, useRef, useState } from 'react';
import AmountInput from '../common/AmountInput';
import Combobox from '../common/Combobox';
import Modal from '../common/Modal';
import { buildCategoryOptions } from '../common/categoryOptions';
import { amountForPayload } from '../common/amount';
import { DIRECTIONS, MATCH_KINDS } from './ruleText';
import { fieldErrors, rulesApi } from './rulesApi';

/* globals gettext, interpolate, ngettext */

const PREVIEW_DELAY_MS = 350;

const blank = (v) => (v === null || v === undefined ? '' : String(v));

function formFrom(rule) {
  return {
    name: rule?.name || '',
    payee_match: rule?.payee_match || '',
    payee_value: rule?.payee_value || '',
    description_match: rule?.description_match || '',
    description_value: rule?.description_value || '',
    amount_min: blank(rule?.amount_min),
    amount_max: blank(rule?.amount_max),
    direction: rule?.direction || 'any',
    account: rule?.account ?? null,
    category: rule?.category ?? null,
    set_payee: rule?.set_payee || '',
    set_description: rule?.set_description || '',
    mode: rule?.mode || 'auto',
    is_enabled: rule?.is_enabled ?? true,
  };
}

function payloadFrom(form) {
  const amount = (value) => (value.trim() === '' ? null : amountForPayload(value));
  return {
    ...form,
    name: form.name.trim(),
    amount_min: amount(form.amount_min),
    amount_max: amount(form.amount_max),
    account: form.account || null,
  };
}

function TextCondition({ label, kind, value, onKind, onValue, testId, error }) {
  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-[7rem_10rem_1fr] sm:items-center">
      <span className="text-sm font-medium">{label}</span>
      <select
        className="select select-bordered select-sm w-full"
        value={kind}
        onChange={(e) => onKind(e.target.value)}
        data-testid={`${testId}-match`}
        aria-label={interpolate(gettext('How the %s matches'), [label.toLowerCase()])}
      >
        {MATCH_KINDS.map((k) => (
          <option key={k.value} value={k.value}>
            {k.label()}
          </option>
        ))}
      </select>
      <input
        type="text"
        className={`input input-bordered input-sm w-full ${error ? 'input-error' : ''}`}
        value={value}
        disabled={!kind}
        onChange={(e) => onValue(e.target.value)}
        data-testid={`${testId}-value`}
        aria-label={label}
      />
    </div>
  );
}

/**
 * Create or edit one categorization rule, with a live test against the book.
 *
 * Opened from the rules page, from categorize mode ("Always categorize
 * transactions like this") and from the bank feed's edit modal, each with a
 * draft the server built from the transaction (`rules/api/rules/draft/`).
 * Saving a new rule can also file the uncategorized transactions it matches.
 */
export default function RuleEditorModal({ open, onClose, book, rule, accounts, feedAccounts = [], onSaved }) {
  const api = useMemo(() => rulesApi(book), [book]);
  const [form, setForm] = useState(() => formFrom(rule));
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [preview, setPreview] = useState(null);
  const [applyNow, setApplyNow] = useState(true);
  const ticket = useRef(0);
  const isEdit = Boolean(rule?.id);

  useEffect(() => {
    if (!open) return;
    setForm(formFrom(rule));
    setErrors({});
    setPreview(null);
    setApplyNow(!rule?.id);
  }, [open, rule]);

  const categoryOptions = useMemo(() => {
    const current = accounts.find((a) => a.id === form.category);
    return buildCategoryOptions(accounts, { keep: current ? [current] : [] });
  }, [accounts, form.category]);
  const categoryValue = categoryOptions.find((o) => o.id === form.category) || null;

  const set = (field) => (value) => setForm((prev) => ({ ...prev, [field]: value }));

  // Live test of the unsaved conditions; only the newest answer paints.
  useEffect(() => {
    if (!open) return undefined;
    const mine = ++ticket.current;
    const timer = setTimeout(async () => {
      try {
        const result = await api.preview({ ...payloadFrom(form), id: rule?.id });
        if (mine === ticket.current) setPreview(result);
      } catch {
        if (mine === ticket.current) setPreview(null);
      }
    }, PREVIEW_DELAY_MS);
    return () => clearTimeout(timer);
  }, [open, form, api, rule]);

  const save = async () => {
    setSaving(true);
    setErrors({});
    try {
      const payload = payloadFrom(form);
      const saved = isEdit ? await api.update(rule.id, payload) : await api.create(payload);
      let applied = null;
      if (applyNow && preview?.count > 0) applied = await api.apply(saved.id);
      onSaved?.(saved, applied);
    } catch (error) {
      setErrors(fieldErrors(error));
    } finally {
      setSaving(false);
    }
  };

  const previewErrors = preview?.errors;
  const count = preview?.count ?? 0;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isEdit ? gettext('Edit rule') : gettext('New rule')}
      size="lg"
      testId="rule-editor"
      actions={
        <>
          <button type="button" className="btn btn-sm" onClick={onClose} disabled={saving} data-testid="rule-cancel">
            {gettext('Cancel')}
          </button>
          <button
            type="button"
            className="btn btn-sm btn-primary"
            onClick={save}
            disabled={saving || !form.category}
            data-testid="rule-save"
          >
            {saving && <span className="loading loading-spinner loading-xs" />}
            {applyNow && count > 0
              ? interpolate(ngettext('Save and categorize %s', 'Save and categorize %s', count), [count])
              : gettext('Save rule')}
          </button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {errors._ && (
          <div role="alert" className="alert alert-error text-sm" data-testid="rule-error">
            {errors._}
          </div>
        )}

        <section className="flex flex-col gap-2">
          <h3 className="text-sm font-semibold">{gettext('When a transaction…')}</h3>
          <TextCondition
            label={gettext('Payee')}
            kind={form.payee_match}
            value={form.payee_value}
            onKind={set('payee_match')}
            onValue={set('payee_value')}
            testId="rule-payee"
            error={errors.payee_value}
          />
          <TextCondition
            label={gettext('Description')}
            kind={form.description_match}
            value={form.description_value}
            onKind={set('description_match')}
            onValue={set('description_value')}
            testId="rule-description"
            error={errors.description_value}
          />
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-[7rem_1fr_1fr] sm:items-center">
            <span className="text-sm font-medium">{gettext('Amount')}</span>
            <AmountInput
              className="input input-bordered input-sm w-full"
              placeholder={gettext('From (any)')}
              value={form.amount_min}
              onValueChange={set('amount_min')}
              aria-label={gettext('Smallest amount')}
              data-testid="rule-amount-min"
            />
            <AmountInput
              className="input input-bordered input-sm w-full"
              placeholder={gettext('To (any)')}
              value={form.amount_max}
              onValueChange={set('amount_max')}
              aria-label={gettext('Largest amount')}
              data-testid="rule-amount-max"
            />
          </div>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-[7rem_1fr_1fr] sm:items-center">
            <span className="text-sm font-medium">{gettext('Direction')}</span>
            <select
              className="select select-bordered select-sm w-full"
              value={form.direction}
              onChange={(e) => set('direction')(e.target.value)}
              data-testid="rule-direction"
              aria-label={gettext('Direction')}
            >
              {DIRECTIONS.map((d) => (
                <option key={d.value} value={d.value}>
                  {d.label()}
                </option>
              ))}
            </select>
            <select
              className="select select-bordered select-sm w-full"
              value={form.account ?? ''}
              onChange={(e) => set('account')(e.target.value ? Number(e.target.value) : null)}
              data-testid="rule-account"
              aria-label={gettext('Account')}
            >
              <option value="">{gettext('In any account')}</option>
              {feedAccounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {interpolate(gettext('Only in %s'), [a.name])}
                </option>
              ))}
            </select>
          </div>
          {errors.amount_min && <p className="text-xs text-error">{errors.amount_min}</p>}
          {errors.account && <p className="text-xs text-error">{errors.account}</p>}
        </section>

        <section className="flex flex-col gap-2">
          <h3 className="text-sm font-semibold">{gettext('…then')}</h3>
          <Combobox
            label={gettext('Categorize as')}
            value={categoryValue}
            onChange={(option) => set('category')(option ? option.id : null)}
            options={categoryOptions}
            getGroup={(option) => option.groupLabel}
            error={errors.category}
            testId="rule-category"
          />
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <label className="form-control w-full">
              <span className="label-text mb-1 block text-sm text-base-content/70">
                {gettext('Rename payee to (optional)')}
              </span>
              <input
                type="text"
                className="input input-bordered input-sm w-full"
                value={form.set_payee}
                onChange={(e) => set('set_payee')(e.target.value)}
                data-testid="rule-set-payee"
              />
            </label>
            <label className="form-control w-full">
              <span className="label-text mb-1 block text-sm text-base-content/70">
                {gettext('Rename description to (optional)')}
              </span>
              <input
                type="text"
                className="input input-bordered input-sm w-full"
                value={form.set_description}
                onChange={(e) => set('set_description')(e.target.value)}
                data-testid="rule-set-description"
              />
            </label>
          </div>
          <fieldset className="flex flex-col gap-1" data-testid="rule-mode">
            <legend className="sr-only">{gettext('Mode')}</legend>
            <label className="flex cursor-pointer items-start gap-2 text-sm">
              <input
                type="radio"
                className="radio radio-sm mt-0.5"
                name="rule-mode"
                checked={form.mode === 'auto'}
                onChange={() => set('mode')('auto')}
                data-testid="rule-mode-auto"
              />
              <span>
                <span className="font-medium">{gettext('Categorize automatically')}</span>
                <span className="block text-xs text-base-content/70">
                  {gettext('New transactions from your bank or a CSV are filed the moment they arrive.')}
                </span>
              </span>
            </label>
            <label className="flex cursor-pointer items-start gap-2 text-sm">
              <input
                type="radio"
                className="radio radio-sm mt-0.5"
                name="rule-mode"
                checked={form.mode === 'suggest'}
                onChange={() => set('mode')('suggest')}
                data-testid="rule-mode-suggest"
              />
              <span>
                <span className="font-medium">{gettext('Suggest only')}</span>
                <span className="block text-xs text-base-content/70">
                  {gettext('Shown as the top suggestion in Categorize mode; you confirm each one.')}
                </span>
              </span>
            </label>
          </fieldset>
        </section>

        <label className="form-control w-full">
          <span className="label-text mb-1 block text-sm text-base-content/70">{gettext('Rule name (optional)')}</span>
          <input
            type="text"
            className={`input input-bordered input-sm w-full ${errors.name ? 'input-error' : ''}`}
            value={form.name}
            placeholder={gettext('Named for you if left blank')}
            onChange={(e) => set('name')(e.target.value)}
            data-testid="rule-name"
          />
          {errors.name && <span className="mt-1 text-xs text-error">{errors.name}</span>}
        </label>

        <section className="app-surface p-3" aria-live="polite" data-testid="rule-preview">
          {previewErrors ? (
            <p className="text-sm text-base-content/70">
              {Object.values(previewErrors).flat().join(' ') || gettext('Finish the conditions to test the rule.')}
            </p>
          ) : preview ? (
            <>
              <p className="text-sm" data-testid="rule-preview-count">
                {interpolate(
                  ngettext(
                    'Matches %s uncategorized transaction in your Inbox.',
                    'Matches %s uncategorized transactions in your Inbox.',
                    count,
                  ),
                  [count],
                )}
              </p>
              {preview.categorized_count > 0 && (
                <p className="text-xs text-base-content/70">
                  {interpolate(
                    gettext('It also matches %s you already categorized; %s of them are in this category.'),
                    [preview.categorized_count, preview.agreeing_count],
                  )}
                </p>
              )}
              {preview.sample?.length > 0 && (
                <ul className="mt-2 flex flex-col gap-1 text-xs" data-testid="rule-preview-sample">
                  {preview.sample.slice(0, 5).map((row) => (
                    <li key={row.id} className="flex justify-between gap-3">
                      <span className="truncate">
                        {row.posted_date} · {row.payee || row.description}
                      </span>
                      <span className="money shrink-0">{row.amount}</span>
                    </li>
                  ))}
                </ul>
              )}
              {count > 0 && (
                <label className="mt-2 flex cursor-pointer items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="checkbox checkbox-sm rounded-sm"
                    checked={applyNow}
                    onChange={(e) => setApplyNow(e.target.checked)}
                    data-testid="rule-apply-now"
                  />
                  {interpolate(ngettext('Also categorize this %s now', 'Also categorize these %s now', count), [count])}
                </label>
              )}
            </>
          ) : (
            <p className="text-sm text-base-content/70">{gettext('Testing against your transactions…')}</p>
          )}
        </section>
      </div>
    </Modal>
  );
}
