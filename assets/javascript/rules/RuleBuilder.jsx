import React, { useEffect, useMemo, useRef, useState } from 'react';

import Combobox from '../common/Combobox';
import Icon from '../common/Icon';
import Modal from '../common/Modal';
import { buildCategoryOptions } from '../common/categoryOptions';
import { formatMoney } from '../common/amount';
import { getJson } from '../common/http';
import { conditionText } from './summary';
import RuleSentence from './RuleSentence';

/* globals gettext, interpolate, ngettext */

/**
 * Create or edit one rule: conditions on the left, what to do on the right, and
 * underneath a live Test panel (`rules/test/`) showing the feed rows it would
 * catch now, how it would have done on history, and which rules it collides with.
 *
 * `initial` is a saved rule, a draft (create-from-action, a proposal), or null.
 */

const EMPTY = {
  id: null,
  name: '',
  is_active: true,
  mode: 'suggest',
  direction: 'out',
  accounts: [],
  match: 'all',
  conditions: [{ field: 'description', op: 'contains', value: '' }],
  action: 'category',
  category: null,
  splits: null,
  payee_name: '',
  description: '',
  origin: 'manual',
  proposal_id: null,
};

const TEST_DEBOUNCE_MS = 400;

function fromInitial(initial) {
  if (!initial) return { ...EMPTY, conditions: EMPTY.conditions.map((c) => ({ ...c })) };
  return {
    ...EMPTY,
    ...initial,
    conditions: (initial.conditions ?? EMPTY.conditions).map((c) => ({ ...c })),
    accounts: (initial.accounts || []).map(Number),
    splits: initial.splits
      ? initial.splits.map((s) => ({ category: Number(s.category), percent: String(s.percent) }))
      : null,
  };
}

/** Only the conditions the server can read: an unfinished row is left out of the test, not an error. */
function usableConditions(conditions) {
  return conditions.filter((c) => {
    if (c.field === 'amount') {
      if (c.op === 'between')
        return Array.isArray(c.value) && c.value.every((v) => String(v).trim() !== '' && !isNaN(Number(v)));
      return String(c.value).trim() !== '' && !isNaN(Number(c.value));
    }
    return /[a-z0-9]/i.test(String(c.value || ''));
  });
}

function draftBody(rule, { forTest = false } = {}) {
  const body = {
    id: rule.id || null,
    name: rule.name,
    is_active: rule.is_active,
    mode: rule.mode,
    direction: rule.direction,
    accounts: rule.accounts,
    match: rule.match,
    conditions: forTest ? usableConditions(rule.conditions) : rule.conditions,
    action: rule.action,
    category: rule.action === 'category' ? rule.category : null,
    splits: rule.action === 'split' ? rule.splits : null,
    payee_name: rule.payee_name,
    description: rule.description,
    origin: rule.origin,
  };
  if (rule.proposal_id) body.proposal_id = rule.proposal_id;
  return body;
}

function RowsTable({ rows, extra }) {
  if (!rows.length) return null;
  return (
    <div className="max-h-56 overflow-y-auto rounded-box border border-base-300">
      <table className="table table-xs">
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td className="whitespace-nowrap">{row.posted_date}</td>
              <td className="truncate">{row.account_name}</td>
              <td className="max-w-48 truncate" title={row.payee || row.description}>
                {row.payee || row.description}
              </td>
              {extra && <td className="truncate text-base-content/70">{extra(row)}</td>}
              <td className="money whitespace-nowrap text-right">{formatMoney(Math.abs(Number(row.amount)))}</td>
              <td className="text-xs text-base-content/70">
                {Number(row.amount) > 0 ? gettext('out') : gettext('in')}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TestPanel({ result, loading, error }) {
  return (
    <section data-testid="rule-test-panel" aria-live="polite">
      <h4 className="mb-2 text-sm font-semibold">{gettext('What it would catch')}</h4>
      {error && <p className="text-sm text-error">{error}</p>}
      {!error && !result && (
        <p className="text-sm text-base-content/70">
          {loading ? gettext('Testing…') : gettext('Add a condition to see what this rule would catch.')}
        </p>
      )}
      {result && (
        <div className={`space-y-3 ${loading ? 'opacity-60' : ''}`}>
          <div>
            <p className="text-sm font-medium" data-testid="rule-test-pending">
              {interpolate(
                ngettext(
                  '%s transaction in the bank feed would be caught',
                  '%s transactions in the bank feed would be caught',
                  result.pending.count,
                ),
                [result.pending.count],
              )}
            </p>
            <RowsTable rows={result.pending.rows} />
          </div>
          {result.backtest.matched > 0 && (
            <div>
              <p className="text-sm" data-testid="rule-test-backtest">
                {interpolate(
                  gettext(
                    'On your history it matches %s past transactions: %s categorized the same way, %s differently.',
                  ),
                  [result.backtest.matched, result.backtest.agree, result.backtest.differ],
                )}
              </p>
              {result.backtest.differ > 0 && (
                <details className="mt-1">
                  <summary className="cursor-pointer text-sm text-base-content/70">
                    {gettext('Show the ones that differ')}
                  </summary>
                  <RowsTable
                    rows={result.backtest.differ_rows}
                    extra={(row) => (row.category_names || []).join(', ')}
                  />
                </details>
              )}
            </div>
          )}
          <Conflicts conflicts={result.conflicts} />
        </div>
      )}
    </section>
  );
}

function Conflicts({ conflicts }) {
  if (!conflicts) return null;
  const { dead, shadowed_by: shadowed, takes_from: takes } = conflicts;
  if (!dead && !shadowed.length && !takes.length) return null;
  return (
    <div className="space-y-1" data-testid="rule-test-conflicts">
      {dead && (
        <div role="alert" className="alert alert-warning alert-soft py-2 text-sm">
          <Icon name="triangle-exclamation" className="h-4 w-4" />
          <span>
            {gettext(
              'This rule would never win: every transaction it matches is caught first by a rule above it. Move it up, or narrow the other rule.',
            )}
          </span>
        </div>
      )}
      {!dead &&
        shadowed.map((c) => (
          <p key={`s${c.rule_id}`} className="text-sm text-warning">
            {interpolate(gettext('“%s” is above this rule and catches %s of its matches first.'), [
              c.rule_name,
              c.count,
            ])}
          </p>
        ))}
      {takes.map((c) => (
        <p key={`t${c.rule_id}`} className="text-sm text-base-content/70">
          {interpolate(gettext('Takes %s transactions from “%s”, which would categorize them differently.'), [
            c.count,
            c.rule_name,
          ])}
        </p>
      ))}
    </div>
  );
}

function ExplainPanel({ api, bookBase, rule }) {
  const [rows, setRows] = useState(null);
  const [picked, setPicked] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    getJson(`${bookBase}bankfeed/api/feed/?view=active&page_size=200`)
      .then((data) => setRows(data.results || []))
      .catch((e) => setError(e.message));
  }, [bookBase]);

  const options = useMemo(
    () =>
      (rows || []).map((r) => ({
        id: Number(r.id),
        label: `${r.posted_date} · ${r.payee || r.description} · ${formatMoney(
          Math.abs(Number(r.outflow) || Number(r.inflow)),
        )}`,
      })),
    [rows],
  );

  useEffect(() => {
    if (!picked) return;
    api
      .explain(draftBody(rule, { forTest: true }), picked.id)
      .then((data) => {
        setResult(data);
        setError('');
      })
      .catch((e) => setError(e.message));
  }, [picked, rule, api]);

  const tick = (passed) => (
    <Icon
      name={passed ? 'check-circle' : 'times-circle'}
      className={`h-4 w-4 shrink-0 ${passed ? 'text-success' : 'text-error'}`}
    />
  );

  return (
    <section className="border-t border-base-300 pt-3" data-testid="rule-explain">
      <h4 className="text-sm font-semibold">{gettext("Why didn't it match?")}</h4>
      <p className="text-xs text-base-content/70">
        {gettext('Pick a transaction to see which part of the rule it fails.')}
      </p>
      <div className="mt-2 space-y-2">
        <Combobox
          ariaLabel={gettext('Pick a transaction')}
          placeholder={rows ? gettext('Search the bank feed…') : gettext('Loading…')}
          value={picked}
          onChange={setPicked}
          options={options}
          size="sm"
          testId="rule-explain-picker"
        />
        {error && <p className="text-sm text-error">{error}</p>}
        {result && (
          <ul className="space-y-1 text-sm" data-testid="rule-explain-result">
            <li className="font-medium">
              {result.matched ? gettext('This rule matches it.') : gettext("This rule doesn't match it:")}
            </li>
            {result.direction.value !== 'any' && (
              <li className="flex items-center gap-2">
                {tick(result.direction.passed)}
                {result.direction.value === 'out' ? gettext('Money out') : gettext('Money in')}
              </li>
            )}
            {result.accounts.value.length > 0 && (
              <li className="flex items-center gap-2">
                {tick(result.accounts.passed)}
                {gettext('In one of the chosen accounts')}
              </li>
            )}
            {result.conditions.map((c, i) => (
              <li key={i} className="flex items-center gap-2">
                {tick(c.passed)}
                {conditionText(c)}
              </li>
            ))}
            {result.match === 'any' && result.conditions.length > 1 && (
              <li className="text-base-content/70">{gettext('Any one condition is enough.')}</li>
            )}
          </ul>
        )}
      </div>
    </section>
  );
}

export default function RuleBuilder({
  open,
  onClose,
  api,
  bookBase,
  initial,
  categories,
  feedAccounts,
  canEdit,
  onSaved,
  onDeleted,
}) {
  const [rule, setRule] = useState(() => fromInitial(initial));
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [test, setTest] = useState({ result: null, loading: false, error: '' });
  const [confirmApply, setConfirmApply] = useState(false);
  const [testOpen, setTestOpen] = useState(false);
  // Bumped on every open, so the sentence's own state (shown rename clauses) starts fresh.
  const [session, setSession] = useState(0);
  const testSeq = useRef(0);

  useEffect(() => {
    if (open) {
      setRule(fromInitial(initial));
      setErrors({});
      setTest({ result: null, loading: false, error: '' });
      setConfirmApply(false);
      setTestOpen(false);
      setSession((n) => n + 1);
    }
  }, [open, initial]);

  const categoryOptions = useMemo(() => buildCategoryOptions(categories), [categories]);
  const optionsById = useMemo(() => new Map(categoryOptions.map((o) => [o.id, o])), [categoryOptions]);
  const feedIds = useMemo(() => new Set(feedAccounts.map((a) => a.id)), [feedAccounts]);

  const set = (patch) => setRule((r) => ({ ...r, ...patch }));

  const runTest = () => {
    const body = draftBody(rule, { forTest: true });
    const narrows = body.conditions.length || body.direction !== 'any' || body.accounts.length;
    if (!narrows) {
      setTest({ result: null, loading: false, error: '' });
      return;
    }
    const seq = ++testSeq.current;
    setTest((t) => ({ ...t, loading: true }));
    api
      .test(body)
      .then((result) => seq === testSeq.current && setTest({ result, loading: false, error: '' }))
      .catch((e) => seq === testSeq.current && setTest({ result: null, loading: false, error: e.message }));
  };

  // Live: re-test a moment after the user stops typing.
  useEffect(() => {
    if (!open) return undefined;
    const t = setTimeout(runTest, TEST_DEBOUNCE_MS);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    open,
    rule.direction,
    rule.accounts,
    rule.match,
    rule.conditions,
    rule.action,
    rule.category,
    rule.splits,
    rule.payee_name,
    rule.description,
  ]);

  const save = async ({ applyExisting = false } = {}) => {
    setSaving(true);
    setErrors({});
    try {
      const body = draftBody(rule);
      delete body.id;
      const saved = rule.id ? await api.update(rule.id, body) : await api.create(body);
      let applied = null;
      if (applyExisting) applied = await api.apply(saved.id);
      onSaved(saved, { applied, created: !rule.id });
    } catch (e) {
      setErrors(e.payload && typeof e.payload === 'object' ? e.payload : { error: e.message });
      setConfirmApply(false);
    } finally {
      setSaving(false);
    }
  };

  const onSave = () => {
    const pending = test.result?.pending.count ?? 0;
    if (rule.mode === 'auto_post' && pending > 0 && !confirmApply) {
      setConfirmApply(true);
      return;
    }
    save();
  };

  const remove = async () => {
    // eslint-disable-next-line no-alert
    if (!window.confirm(gettext('Delete this rule? Transactions it already categorized stay categorized.'))) return;
    setSaving(true);
    try {
      await api.remove(rule.id);
      onDeleted(rule.id);
    } catch (e) {
      setErrors({ error: e.message });
    } finally {
      setSaving(false);
    }
  };

  const fieldError = (name) => {
    const value = errors[name];
    if (!value) return null;
    const text = Array.isArray(value)
      ? value.map((v) => (typeof v === 'string' ? v : JSON.stringify(v))).join(' ')
      : String(value);
    return <p className="mt-1 text-sm text-error">{text}</p>;
  };

  const pendingCount = test.result?.pending.count ?? 0;

  const actions = confirmApply ? (
    <div className="flex w-full flex-wrap items-center justify-end gap-2" data-testid="rule-apply-confirm">
      <span className="mr-auto text-sm">
        {interpolate(
          ngettext(
            '%s transaction already in the feed matches. Categorize it now too?',
            '%s transactions already in the feed match. Categorize them now too?',
            pendingCount,
          ),
          [pendingCount],
        )}
      </span>
      <button type="button" className="btn btn-ghost" disabled={saving} onClick={() => save()}>
        {gettext('Save only')}
      </button>
      <button
        type="button"
        className="btn btn-primary"
        disabled={saving}
        onClick={() => save({ applyExisting: true })}
        data-testid="rule-save-apply"
      >
        {interpolate(gettext('Save and apply to %s'), [pendingCount])}
      </button>
    </div>
  ) : (
    <>
      {rule.id && canEdit && (
        <button type="button" className="btn btn-ghost text-error mr-auto" disabled={saving} onClick={remove}>
          {gettext('Delete')}
        </button>
      )}
      <button type="button" className="btn btn-ghost" onClick={onClose}>
        {gettext('Cancel')}
      </button>
      {canEdit && (
        <button type="button" className="btn btn-primary" disabled={saving} onClick={onSave} data-testid="rule-save">
          {gettext('Save rule')}
        </button>
      )}
    </>
  );

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={rule.id ? gettext('Edit rule') : gettext('New rule')}
      size="lg"
      testId="rule-builder"
      initialFocus="[data-autofocus]"
      actions={actions}
    >
      <div className="space-y-4">
        {errors.error && (
          <div role="alert" className="alert alert-error alert-soft text-sm">
            {errors.error}
          </div>
        )}
        {errors.non_field_errors && fieldError('non_field_errors')}
        <label className="block">
          <span className="text-sm font-medium">{gettext('Name')}</span>
          <input
            type="text"
            className="input mt-1 w-full"
            value={rule.name}
            maxLength={100}
            data-autofocus
            onChange={(e) => set({ name: e.target.value })}
            placeholder={gettext('e.g. Car insurance')}
            data-testid="rule-name"
          />
          {fieldError('name')}
        </label>

        <RuleSentence
          key={session}
          rule={rule}
          set={set}
          categoryOptions={categoryOptions}
          feedAccounts={feedAccounts}
          feedIds={feedIds}
        />
        {['conditions', 'accounts', 'category', 'splits', 'payee_name', 'mode'].map((name) => (
          <React.Fragment key={name}>{fieldError(name)}</React.Fragment>
        ))}
        <label className="flex cursor-pointer items-center gap-2">
          <input
            type="checkbox"
            className="toggle toggle-sm"
            checked={rule.is_active}
            onChange={(e) => set({ is_active: e.target.checked })}
            data-testid="rule-active"
          />
          <span className="text-sm">{gettext('Active')}</span>
        </label>

        {/* Closed by default: the test still runs behind it (the summary shows the
            count, and "Save and apply to N" needs it); the explain picker loads
            the feed only once opened. */}
        <details
          className="rounded-box border border-base-300"
          open={testOpen}
          onToggle={(e) => setTestOpen(e.currentTarget.open)}
          data-testid="rule-test-expander"
        >
          <summary className="flex cursor-pointer items-center gap-2 p-3 font-semibold">
            {gettext('Test this rule')}
            {test.result && (
              <span className="badge badge-ghost badge-sm font-normal" data-testid="rule-test-summary">
                {interpolate(ngettext('%s match in the feed', '%s matches in the feed', test.result.pending.count), [
                  test.result.pending.count,
                ])}
              </span>
            )}
            {test.result?.conflicts?.dead && (
              <span className="badge badge-warning badge-sm font-normal">{gettext('Never wins')}</span>
            )}
            {/* In the header so it is there whether the card is open or not; it must not toggle the card. */}
            <button
              type="button"
              className="btn btn-ghost btn-xs ml-auto font-normal"
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                runTest();
              }}
              disabled={test.loading}
              data-testid="rule-test-button"
            >
              <Icon name="refresh" className={`h-3.5 w-3.5 ${test.loading ? 'animate-spin' : ''}`} />
              {gettext('Test again')}
            </button>
          </summary>
          {testOpen && (
            <div className="space-y-4 px-3 pb-3">
              <TestPanel result={test.result} loading={test.loading} error={test.error} />
              <ExplainPanel api={api} bookBase={bookBase} rule={rule} />
            </div>
          )}
        </details>
      </div>
    </Modal>
  );
}
