import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Icon from '../common/Icon';
import Modal from '../common/Modal';
import Toast from '../common/Toast';
import RuleEditorModal from './RuleEditorModal';
import { actionText, conditionText } from './ruleText';
import { rulesApi } from './rulesApi';

/* globals gettext, interpolate, ngettext */

const NEW_RULE = { mode: 'auto', is_enabled: true, description_match: 'contains', direction: 'any' };

function appliedMessage(applied) {
  const filed = applied?.categorized ?? 0;
  const refused = applied?.refused?.length ?? 0;
  let message = interpolate(ngettext('Categorized %s transaction.', 'Categorized %s transactions.', filed), [filed]);
  if (refused) {
    message += ` ${interpolate(
      ngettext('%s could not be categorized: %s', '%s could not be categorized: %s', refused),
      [refused, applied.refused[0].error],
    )}`;
  }
  return message;
}

/**
 * The rules page: every rule in the order it runs, with its conditions and
 * action in words. Reorder with the arrows, toggle with the switch, test and
 * apply from the row. Members see it read-only.
 */
export default function RulesApp({ book, canEdit, accounts, feedAccounts, inboxUrl, categorizeUrl }) {
  const api = useMemo(() => rulesApi(book), [book]);
  const [rules, setRules] = useState(null);
  const [editing, setEditing] = useState(null); // a rule, or NEW_RULE
  const [testing, setTesting] = useState(null); // {rule, result}
  const [deleting, setDeleting] = useState(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);

  const load = useCallback(async () => {
    try {
      setRules(await api.list());
    } catch (error) {
      setToast({ severity: 'error', message: error.message });
      setRules([]);
    }
  }, [api]);

  useEffect(() => {
    load();
  }, [load]);

  const handleSaved = (saved, applied) => {
    setEditing(null);
    setToast({
      severity: 'success',
      message: applied ? `${gettext('Rule saved.')} ${appliedMessage(applied)}` : gettext('Rule saved.'),
    });
    load();
  };

  const move = async (index, delta) => {
    const next = [...rules];
    const [rule] = next.splice(index, 1);
    next.splice(index + delta, 0, rule);
    setRules(next);
    try {
      await api.reorder(next.map((r) => r.id));
    } catch (error) {
      setToast({ severity: 'error', message: error.message });
      load();
    }
  };

  const toggle = async (rule) => {
    setRules((prev) => prev.map((r) => (r.id === rule.id ? { ...r, is_enabled: !r.is_enabled } : r)));
    try {
      await api.update(rule.id, { is_enabled: !rule.is_enabled });
    } catch (error) {
      setToast({ severity: 'error', message: error.message });
      load();
    }
  };

  const runTest = async (rule) => {
    setTesting({ rule, result: null });
    try {
      setTesting({ rule, result: await api.test(rule.id) });
    } catch (error) {
      setTesting(null);
      setToast({ severity: 'error', message: error.message });
    }
  };

  const runApply = async () => {
    setBusy(true);
    try {
      const applied = await api.apply(testing.rule.id);
      setTesting(null);
      setToast({ severity: 'success', message: appliedMessage(applied) });
      load();
    } catch (error) {
      setToast({ severity: 'error', message: error.message });
    } finally {
      setBusy(false);
    }
  };

  const confirmDelete = async () => {
    setBusy(true);
    try {
      await api.remove(deleting.id);
      setDeleting(null);
      load();
    } catch (error) {
      setToast({ severity: 'error', message: error.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="app-card" data-testid="rules-page">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-base-content/70">
          {gettext('Rules run top to bottom; the first that matches a transaction decides it.')}{' '}
          <a className="link link-primary" href={inboxUrl}>
            {gettext('Open the Inbox')}
          </a>
        </p>
        {canEdit && (
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => setEditing(NEW_RULE)}
            data-testid="rule-new"
          >
            <Icon name="plus" className="h-4 w-4" />
            {gettext('New rule')}
          </button>
        )}
      </div>

      {rules === null ? (
        <div className="flex justify-center py-8">
          <span className="loading loading-spinner" />
        </div>
      ) : rules.length === 0 ? (
        <div className="py-8 text-center" data-testid="rules-empty">
          <p className="font-medium">{gettext('No rules yet')}</p>
          <p className="mt-1 text-sm text-base-content/70">
            {gettext('In Categorize mode, file a transaction and choose “Always categorize transactions like this”.')}{' '}
            <a className="link link-primary" href={categorizeUrl}>
              {gettext('Go to Categorize mode')}
            </a>
          </p>
        </div>
      ) : (
        <ol className="flex flex-col divide-y divide-base-300" data-testid="rules-list">
          {rules.map((rule, index) => (
            <li
              key={rule.id}
              className={`flex flex-wrap items-center gap-3 py-3 ${rule.is_enabled ? '' : 'opacity-60'}`}
              data-testid="rule-row"
              data-rule-id={rule.id}
            >
              {canEdit && (
                <div className="flex flex-col">
                  <button
                    type="button"
                    className="btn btn-ghost btn-xs px-1"
                    disabled={index === 0}
                    onClick={() => move(index, -1)}
                    aria-label={interpolate(gettext('Move %s up'), [rule.name])}
                    data-testid="rule-move-up"
                  >
                    <Icon name="chevron-up" className="h-3.5 w-3.5" />
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost btn-xs px-1"
                    disabled={index === rules.length - 1}
                    onClick={() => move(index, 1)}
                    aria-label={interpolate(gettext('Move %s down'), [rule.name])}
                    data-testid="rule-move-down"
                  >
                    <Icon name="chevron-down" className="h-3.5 w-3.5" />
                  </button>
                </div>
              )}
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium" data-testid="rule-name">
                    {rule.name}
                  </span>
                  <span
                    className={`badge badge-sm ${rule.mode === 'auto' ? 'badge-primary badge-soft' : 'badge-ghost'}`}
                  >
                    {rule.mode === 'auto' ? gettext('Automatic') : gettext('Suggest only')}
                  </span>
                  {rule.problem && (
                    <span
                      className="badge badge-sm badge-warning badge-soft"
                      title={rule.problem}
                      data-testid="rule-problem"
                    >
                      {rule.problem}
                    </span>
                  )}
                </div>
                <p className="truncate text-sm text-base-content/70">{conditionText(rule)}</p>
                <p className="truncate text-sm">
                  <Icon name="arrow-right" className="mr-1 inline-block h-3.5 w-3.5" />
                  {actionText(rule)}
                  {rule.applied_count > 0 && (
                    <span className="ml-2 text-xs text-base-content/70">
                      {interpolate(ngettext('· filed %s transaction', '· filed %s transactions', rule.applied_count), [
                        rule.applied_count,
                      ])}
                    </span>
                  )}
                </p>
              </div>
              <div className="flex items-center gap-1">
                {canEdit && (
                  <input
                    type="checkbox"
                    className="toggle toggle-sm toggle-primary"
                    checked={rule.is_enabled}
                    onChange={() => toggle(rule)}
                    aria-label={interpolate(gettext('Rule %s is on'), [rule.name])}
                    data-testid="rule-enabled"
                  />
                )}
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => runTest(rule)}
                  data-testid="rule-test"
                >
                  {gettext('Test')}
                </button>
                {canEdit && (
                  <>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() => setEditing(rule)}
                      data-testid="rule-edit"
                    >
                      {gettext('Edit')}
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm text-error"
                      onClick={() => setDeleting(rule)}
                      aria-label={interpolate(gettext('Delete %s'), [rule.name])}
                      data-testid="rule-delete"
                    >
                      <Icon name="trash" className="h-4 w-4" />
                    </button>
                  </>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}

      {editing && (
        <RuleEditorModal
          open
          onClose={() => setEditing(null)}
          book={book}
          rule={editing}
          accounts={accounts}
          feedAccounts={feedAccounts}
          onSaved={handleSaved}
        />
      )}

      <Modal
        open={Boolean(testing)}
        onClose={() => setTesting(null)}
        title={testing ? interpolate(gettext('Test “%s”'), [testing.rule.name]) : ''}
        testId="rule-test-dialog"
        actions={
          <>
            <button type="button" className="btn btn-sm" onClick={() => setTesting(null)}>
              {gettext('Close')}
            </button>
            {canEdit && testing?.result?.count > 0 && !testing.rule.problem && (
              <button
                type="button"
                className="btn btn-sm btn-primary"
                onClick={runApply}
                disabled={busy}
                data-testid="rule-apply"
              >
                {interpolate(ngettext('Categorize %s now', 'Categorize %s now', testing.result.count), [
                  testing.result.count,
                ])}
              </button>
            )}
          </>
        }
      >
        {testing?.result ? (
          <div className="flex flex-col gap-2 text-sm" data-testid="rule-test-result">
            <p>
              {interpolate(
                ngettext(
                  '%s uncategorized transaction matches this rule.',
                  '%s uncategorized transactions match this rule.',
                  testing.result.count,
                ),
                [testing.result.count],
              )}
            </p>
            {testing.result.categorized_count > 0 && (
              <p className="text-base-content/70">
                {interpolate(gettext('It also matches %s you already categorized; %s of them are in %s.'), [
                  testing.result.categorized_count,
                  testing.result.agreeing_count,
                  testing.rule.category_name,
                ])}
              </p>
            )}
            {testing.result.sample.length > 0 && (
              <ul className="flex flex-col gap-1 text-xs">
                {testing.result.sample.map((row) => (
                  <li key={row.id} className="flex justify-between gap-3">
                    <span className="truncate">
                      {row.posted_date} · {row.account_name} · {row.payee || row.description}
                    </span>
                    <span className="money shrink-0">{row.amount}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : (
          <div className="flex justify-center py-4">
            <span className="loading loading-spinner" />
          </div>
        )}
      </Modal>

      <Modal
        open={Boolean(deleting)}
        onClose={() => setDeleting(null)}
        title={gettext('Delete this rule?')}
        testId="rule-delete-dialog"
        actions={
          <>
            <button type="button" className="btn btn-sm" onClick={() => setDeleting(null)}>
              {gettext('Keep it')}
            </button>
            <button
              type="button"
              className="btn btn-sm btn-error"
              onClick={confirmDelete}
              disabled={busy}
              data-testid="rule-delete-confirm"
            >
              {gettext('Delete')}
            </button>
          </>
        }
      >
        <p className="text-sm">
          {gettext('Transactions it already categorized keep their category; new ones will no longer be filed by it.')}
        </p>
      </Modal>

      <Toast
        open={Boolean(toast)}
        message={toast?.message}
        severity={toast?.severity}
        onClose={() => setToast(null)}
        testId="rules-toast"
        autoHideMs={6000}
      />
    </section>
  );
}
