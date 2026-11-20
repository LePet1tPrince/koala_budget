/* globals gettext */
import React, { useState } from 'react';
import { ResponseError } from 'api-client';

import Icon from '../../../common/Icon';
import Modal from '../../../common/Modal';

/**
 * The building blocks every Manage modal (account, group, payee, institution) is
 * made of, so they read like the app's other editors (the transaction modal, the
 * rule builder): muted labels over full-width controls, the error under its field,
 * Delete on the left of the footer confirming in place, Cancel and Save on the right.
 */

export const ACCOUNT_TYPES = [
  { key: 'asset', label: gettext('Asset') },
  { key: 'liability', label: gettext('Liability') },
  { key: 'income', label: gettext('Income') },
  { key: 'expense', label: gettext('Expense') },
  { key: 'goal', label: gettext('Goal') },
];

const camel = (key) => key.replace(/_([a-z])/g, (_m, c) => c.toUpperCase());

/**
 * A failed api-client call as `{ field: message }` (fields in the client's camelCase)
 * plus `_form` for anything not tied to a field (`detail`, `non_field_errors`).
 */
export async function readErrors(error) {
  if (!(error instanceof ResponseError)) return { _form: gettext('Something went wrong. Please try again.') };
  const payload = await error.response.json().catch(() => null);
  if (!payload || typeof payload !== 'object') return { _form: gettext('Something went wrong. Please try again.') };
  const out = {};
  for (const [key, value] of Object.entries(payload)) {
    const message = Array.isArray(value) ? value.join(' ') : String(value);
    if (key === 'detail' || key === 'non_field_errors') out._form = message;
    else out[camel(key)] = message;
  }
  return Object.keys(out).length ? out : { _form: gettext('Something went wrong. Please try again.') };
}

/** A labelled control: the label above, then the control, then its error (or a hint). */
export function Field({ label, error, hint, children, testId }) {
  return (
    <div className="form-control w-full" data-testid={testId}>
      <span className="label-text mb-1 block text-sm text-base-content/70">{label}</span>
      {children}
      {error ? (
        <p className="mt-1 text-xs text-error" data-testid="field-error">
          {error}
        </p>
      ) : (
        hint && <p className="mt-1 text-xs text-base-content/70">{hint}</p>
      )}
    </div>
  );
}

/**
 * A row of buttons standing in for a short `<select>`: one is picked (`btn-primary`).
 * `testIdFor(option)` names each button for tests.
 */
export function ChoiceButtons({ options, value, onChange, disabled, testIdFor }) {
  if (disabled) {
    // Fixed: say what it is rather than show a row of greyed-out buttons.
    const picked = options.find((option) => option.key === value);
    return (
      <span className="badge badge-ghost badge-lg self-start" data-testid="fixed-choice">
        {picked ? picked.label : '—'}
      </span>
    );
  }
  return (
    <div className="flex flex-wrap gap-2" role="radiogroup">
      {options.map((option) => (
        <button
          key={option.key}
          type="button"
          role="radio"
          aria-checked={value === option.key}
          className={`btn btn-sm ${value === option.key ? 'btn-primary' : 'btn-outline'}`}
          onClick={() => onChange(option.key)}
          disabled={disabled}
          data-testid={testIdFor?.(option)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/** A labelled on/off switch with a line saying what "on" means. */
export function Toggle({ label, hint, checked, onChange, testId }) {
  return (
    <label className="flex cursor-pointer items-start gap-3">
      <input
        type="checkbox"
        className="toggle toggle-primary toggle-sm mt-0.5"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        data-testid={testId}
      />
      <span>
        <span className="block text-sm">{label}</span>
        {hint && <span className="block text-xs text-base-content/70">{hint}</span>}
      </span>
    </label>
  );
}

/**
 * The standard editor modal. `onSave` and `onDelete` are async; a thrown
 * `readErrors` object is shown (field errors by the fields, the rest above the
 * footer). Delete asks "Delete?" in the footer rather than in a second dialog
 * (design-document.md, 2026-09-23); `deleteNote` says what deleting does.
 */
export function ManageModal({
  title,
  testId,
  onClose,
  onSave,
  onDelete,
  deleteNote,
  saveLabel = gettext('Save'),
  canSave = true,
  confirmDelete = false,
  formError,
  busy,
  children,
}) {
  const [confirming, setConfirming] = useState(confirmDelete);

  const submit = (event) => {
    event.preventDefault();
    if (!busy && canSave) onSave();
  };

  return (
    <Modal
      open
      size="sm"
      title={title}
      testId={testId}
      onClose={() => !busy && onClose()}
      initialFocus={confirmDelete ? '[data-testid="modal-delete-confirm"]' : '[data-autofocus]'}
      actions={
        <div className="flex w-full flex-wrap items-center gap-2">
          {onDelete && (
            <div className="mr-auto flex items-center gap-1">
              {confirming ? (
                <>
                  <span className="text-sm text-base-content/70">{gettext('Delete?')}</span>
                  <button
                    type="button"
                    className="btn btn-error btn-sm"
                    onClick={onDelete}
                    disabled={busy}
                    data-testid="modal-delete-confirm"
                  >
                    {gettext('Yes, delete')}
                  </button>
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => setConfirming(false)}>
                    {gettext('Keep')}
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  className="btn btn-ghost btn-sm text-error"
                  onClick={() => setConfirming(true)}
                  disabled={busy}
                  data-testid="modal-delete-btn"
                >
                  <Icon name="trash" className="h-4 w-4" />
                  {gettext('Delete')}
                </button>
              )}
            </div>
          )}
          <button
            type="button"
            className="btn btn-sm ml-auto"
            onClick={onClose}
            disabled={busy}
            data-testid="modal-cancel-btn"
          >
            {gettext('Cancel')}
          </button>
          <button
            type="submit"
            form={`${testId}-form`}
            className="btn btn-primary btn-sm"
            disabled={busy || !canSave}
            data-testid="modal-save-btn"
          >
            {busy && <span className="loading loading-spinner loading-xs" />}
            {saveLabel}
          </button>
        </div>
      }
    >
      <form id={`${testId}-form`} onSubmit={submit} className="flex flex-col gap-4" noValidate>
        {children}
        {confirming && deleteNote && !formError && <p className="text-sm text-base-content/70">{deleteNote}</p>}
        {formError && (
          <div role="alert" className="alert alert-error alert-soft text-sm" data-testid="modal-error">
            {formError}
          </div>
        )}
      </form>
    </Modal>
  );
}

/**
 * Runs one save or delete for a modal: busy while it runs, its `readErrors` kept
 * on failure. Returns `[busy, errors, run]`; `run(fn)` resolves to fn's result, or
 * to `undefined` when it failed.
 */
export function useSubmit() {
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState({});
  const run = async (fn) => {
    setBusy(true);
    setErrors({});
    try {
      return await fn();
    } catch (error) {
      setErrors(await readErrors(error));
      return undefined;
    } finally {
      setBusy(false);
    }
  };
  return [busy, errors, run];
}
