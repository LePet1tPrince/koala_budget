import React, { useCallback, useEffect, useMemo, useState } from 'react';

import Icon from '../common/Icon';
import Toast from '../common/Toast';
import RuleBuilder from './RuleBuilder';
import { ruleSummary } from './summary';

/* globals gettext, interpolate, ngettext */

/**
 * The Rules page: the book's rules in the order they are tried, the proposed
 * rules tray, and the auto-post offers. Admins edit; members read.
 */

function readUrlIntent() {
  const params = new URLSearchParams(window.location.search);
  const edit = params.get('edit');
  let draft = null;
  try {
    draft = params.get('draft') ? JSON.parse(params.get('draft')) : null;
  } catch {
    draft = null;
  }
  return { edit: edit ? Number(edit) : null, draft };
}

function clearUrlIntent() {
  const url = new URL(window.location.href);
  url.searchParams.delete('edit');
  url.searchParams.delete('draft');
  window.history.replaceState(null, '', url);
}

function lastMatched(value) {
  if (!value) return gettext('Never matched');
  return interpolate(gettext('Last matched %s'), [new Date(value).toLocaleDateString()]);
}

function Proposals({ proposals, onAccept, onDismiss, canEdit }) {
  if (!proposals.length) return null;
  return (
    <section className="mb-5 rounded-box border border-primary/30 bg-primary/5 p-4" data-testid="rule-proposals">
      <h2 className="mb-1 flex items-center gap-2 font-semibold">
        <Icon name="wand-magic-sparkles" className="h-4 w-4" />
        {gettext('Proposed from your history')}
      </h2>
      <p className="mb-3 text-sm text-base-content/70">
        {gettext('You categorize these the same way every time. Make each a rule so it happens on its own.')}
      </p>
      <ul className="space-y-2">
        {proposals.map((p) => (
          <li key={p.id} className="flex flex-wrap items-center gap-2" data-testid="rule-proposal">
            <span className="min-w-0 flex-1 text-sm">
              {interpolate(gettext('%s containing “%s” → %s (%s of %s times)'), [
                p.field === 'payee' ? gettext('Payee') : gettext('Description'),
                p.value,
                p.category_name,
                Math.round(Number(p.consistency) * p.evidence_count),
                p.evidence_count,
              ])}
            </span>
            {canEdit && (
              <button type="button" className="btn btn-primary btn-xs" onClick={() => onAccept(p)}>
                {gettext('Review and create')}
              </button>
            )}
            <button type="button" className="btn btn-ghost btn-xs" onClick={() => onDismiss(p)}>
              {gettext('Not this one')}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Prompts({ prompts, onGraduate, canEdit }) {
  if (!prompts) return null;
  return (
    <>
      {canEdit &&
        prompts.graduation.map((g) => (
          <div key={g.id} role="status" className="alert alert-info alert-soft mb-3" data-testid="rule-graduation">
            <Icon name="check-circle" className="h-4 w-4" />
            <span>
              {interpolate(
                gettext(
                  'You confirmed “%s” %s times in a row without changing it. Categorize these automatically from now on?',
                ),
                [g.name, g.streak],
              )}
            </span>
            <div className="flex gap-2">
              <button type="button" className="btn btn-primary btn-xs" onClick={() => onGraduate(g.id, true)}>
                {gettext('Auto-post')}
              </button>
              <button type="button" className="btn btn-ghost btn-xs" onClick={() => onGraduate(g.id, false)}>
                {gettext('Keep suggesting')}
              </button>
            </div>
          </div>
        ))}
    </>
  );
}

export default function RulesApp({ props, api }) {
  const canEdit = props.can_edit;
  const [rules, setRules] = useState(null);
  const [proposals, setProposals] = useState([]);
  const [prompts, setPrompts] = useState(null);
  const [error, setError] = useState('');
  const [builder, setBuilder] = useState({ open: false, initial: null });
  const [toast, setToast] = useState({ open: false, message: '', severity: 'info' });
  const [dragId, setDragId] = useState(null);

  const accountsById = useMemo(() => new Map(props.categories.map((a) => [a.id, a])), [props.categories]);
  const feedAccountsById = useMemo(() => new Map(props.feed_accounts.map((a) => [a.id, a])), [props.feed_accounts]);

  const notify = (message, severity = 'success') => setToast({ open: true, message, severity });

  const load = useCallback(async () => {
    try {
      const [list, open, asks] = await Promise.all([api.list(), api.proposals(), api.prompts()]);
      setRules(list);
      setProposals(open);
      setPrompts(asks);
      setError('');
      return list;
    } catch (e) {
      setError(e.message);
      return null;
    }
  }, [api]);

  useEffect(() => {
    load().then((list) => {
      const { edit, draft } = readUrlIntent();
      if (edit && list) {
        const rule = list.find((r) => r.id === edit);
        if (rule) setBuilder({ open: true, initial: rule });
      } else if (draft) {
        setBuilder({ open: true, initial: draft });
      }
      if (edit || draft) clearUrlIntent();
    });
  }, [load]);

  const patch = async (rule, body) => {
    try {
      await api.update(rule.id, body);
      await load();
    } catch (e) {
      notify(e.message, 'error');
    }
  };

  const move = async (ids) => {
    try {
      setRules(await api.reorder(ids));
    } catch (e) {
      notify(e.message, 'error');
      load();
    }
  };

  const moveBy = (index, delta) => {
    const ids = rules.map((r) => r.id);
    const target = index + delta;
    if (target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target], ids[index]];
    move(ids);
  };

  const dropOn = (targetId) => {
    if (!dragId || dragId === targetId) return;
    const ids = rules.map((r) => r.id).filter((id) => id !== dragId);
    ids.splice(ids.indexOf(targetId), 0, dragId);
    setDragId(null);
    move(ids);
  };

  const onSaved = (saved, { applied, created }) => {
    setBuilder({ open: false, initial: null });
    load();
    if (applied && applied.auto_posted) {
      notify(
        interpolate(
          ngettext(
            'Rule saved. %s transaction categorized.',
            'Rule saved. %s transactions categorized.',
            applied.auto_posted,
          ),
          [applied.auto_posted],
        ),
      );
    } else {
      notify(created ? gettext('Rule created') : gettext('Rule saved'));
    }
  };

  const onDeleted = () => {
    setBuilder({ open: false, initial: null });
    load();
    notify(gettext('Rule deleted'));
  };

  const acceptProposal = async (proposal) => {
    try {
      setBuilder({ open: true, initial: await api.acceptProposal(proposal.id) });
    } catch (e) {
      notify(e.message, 'error');
    }
  };

  const dismissProposal = async (proposal) => {
    try {
      await api.dismissProposal(proposal.id);
      setProposals((list) => list.filter((p) => p.id !== proposal.id));
    } catch (e) {
      notify(e.message, 'error');
    }
  };

  const graduate = async (id, accept) => {
    try {
      await api.graduate(id, accept);
      await load();
      notify(accept ? gettext('This rule now categorizes automatically.') : gettext('It will keep suggesting.'));
    } catch (e) {
      notify(e.message, 'error');
    }
  };

  if (error) {
    return (
      <div role="alert" className="alert alert-error">
        {error}
      </div>
    );
  }
  if (!rules) return <div className="animate-pulse h-40 rounded-box bg-base-200" aria-hidden="true" />;

  return (
    <div data-testid="rules-page">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-base-content/70">
          {interpolate(ngettext('%s rule', '%s rules', rules.length), [rules.length])}
        </p>
        {canEdit && (
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => setBuilder({ open: true, initial: null })}
            data-testid="rule-new"
          >
            <Icon name="plus" className="h-4 w-4" /> {gettext('New rule')}
          </button>
        )}
      </div>

      <Prompts prompts={prompts} onGraduate={graduate} canEdit={canEdit} />
      <Proposals proposals={proposals} onAccept={acceptProposal} onDismiss={dismissProposal} canEdit={canEdit} />

      {rules.length === 0 ? (
        <div className="rounded-box border border-dashed border-base-300 p-8 text-center" data-testid="rules-empty">
          <Icon name="wand-magic-sparkles" className="mx-auto mb-2 h-6 w-6 text-primary" />
          <p className="font-medium">{gettext('No rules yet')}</p>
          <p className="mx-auto mt-1 max-w-prose text-sm text-base-content/70">
            {gettext(
              'A rule says “whenever a transaction looks like this, categorize it like that”. The quickest way to make one: categorize a transaction in the bank feed, and say yes when it offers to remember.',
            )}
          </p>
        </div>
      ) : (
        <ol className="space-y-2" data-testid="rules-list">
          {rules.map((rule, index) => (
            <li
              key={rule.id}
              className={`rounded-box border border-base-300 p-3 ${dragId === rule.id ? 'opacity-50' : ''} ${
                rule.is_active ? '' : 'bg-base-200/60'
              }`}
              draggable={canEdit}
              onDragStart={() => setDragId(rule.id)}
              onDragOver={(e) => canEdit && e.preventDefault()}
              onDrop={() => dropOn(rule.id)}
              onDragEnd={() => setDragId(null)}
              data-testid="rule-row"
              data-rule-id={rule.id}
            >
              <div className="flex flex-wrap items-start gap-3">
                {canEdit && (
                  <div className="flex flex-col">
                    <button
                      type="button"
                      className="btn btn-ghost btn-xs btn-square"
                      disabled={index === 0}
                      onClick={() => moveBy(index, -1)}
                      aria-label={interpolate(gettext('Move “%s” up'), [rule.name])}
                    >
                      <Icon name="chevron-up" className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost btn-xs btn-square"
                      disabled={index === rules.length - 1}
                      onClick={() => moveBy(index, 1)}
                      aria-label={interpolate(gettext('Move “%s” down'), [rule.name])}
                    >
                      <Icon name="chevron-down" className="h-3.5 w-3.5" />
                    </button>
                  </div>
                )}
                <span className="badge badge-ghost badge-sm mt-1" title={gettext('Tried in this order')}>
                  {index + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      className="link link-hover font-medium"
                      onClick={() => setBuilder({ open: true, initial: rule })}
                      data-testid="rule-open"
                    >
                      {rule.name}
                    </button>
                    {rule.mode === 'auto_post' && (
                      <span className="badge badge-primary badge-soft badge-sm">{gettext('Auto-post')}</span>
                    )}
                    {!rule.is_active && <span className="badge badge-ghost badge-sm">{gettext('Off')}</span>}
                    {rule.problem && (
                      <span className="badge badge-warning badge-sm" title={rule.problem} data-testid="rule-problem">
                        {gettext('Needs attention')}
                      </span>
                    )}
                    {rule.demoted_at && rule.mode === 'suggest' && (
                      <span
                        className="badge badge-warning badge-soft badge-sm"
                        title={gettext(
                          'Its automatic categorizations were changed too often, so it only suggests now.',
                        )}
                        data-testid="rule-demoted"
                      >
                        {gettext('Back to suggesting')}
                      </span>
                    )}
                  </div>
                  <p className="mt-0.5 text-sm text-base-content/70" data-testid="rule-summary">
                    {ruleSummary(rule, { accountsById, feedAccountsById })}
                  </p>
                  {rule.problem && <p className="mt-0.5 text-sm text-warning">{rule.problem}</p>}
                  <p className="mt-0.5 text-xs text-base-content/70">
                    {interpolate(gettext('Posted %s · confirmed %s · changed %s · %s'), [
                      rule.times_applied,
                      rule.times_confirmed,
                      rule.times_overridden,
                      lastMatched(rule.last_matched_at),
                    ])}
                  </p>
                </div>
                {canEdit && (
                  <div className="flex items-center gap-3">
                    <label className="flex cursor-pointer items-center gap-1 text-xs">
                      <input
                        type="checkbox"
                        className="toggle toggle-xs toggle-primary"
                        checked={rule.mode === 'auto_post'}
                        disabled={rule.action === 'rename'}
                        onChange={(e) => patch(rule, { mode: e.target.checked ? 'auto_post' : 'suggest' })}
                        aria-label={interpolate(gettext('Auto-post “%s”'), [rule.name])}
                      />
                      {gettext('Auto')}
                    </label>
                    <label className="flex cursor-pointer items-center gap-1 text-xs">
                      <input
                        type="checkbox"
                        className="toggle toggle-xs"
                        checked={rule.is_active}
                        onChange={(e) => patch(rule, { is_active: e.target.checked })}
                        aria-label={interpolate(gettext('“%s” is on'), [rule.name])}
                      />
                      {gettext('On')}
                    </label>
                  </div>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}

      <RuleBuilder
        open={builder.open}
        initial={builder.initial}
        onClose={() => setBuilder({ open: false, initial: null })}
        api={api}
        bookBase={props.book_base}
        categories={props.categories}
        feedAccounts={props.feed_accounts}
        canEdit={canEdit}
        onSaved={onSaved}
        onDeleted={onDeleted}
      />
      <Toast
        open={toast.open}
        message={toast.message}
        severity={toast.severity}
        onClose={() => setToast((t) => ({ ...t, open: false }))}
        testId="rules-toast"
      />
    </div>
  );
}
