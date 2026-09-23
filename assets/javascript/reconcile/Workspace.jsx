import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import DateField from '../common/DateField';
import Icon from '../common/Icon';
import Modal from '../common/Modal';
import { formatMoney, sanitizeAmount, toCents } from '../common/amount';
import DifferenceHints from './DifferenceHints';
import { formatDate, labelsFor } from './labels';

/* globals gettext, interpolate */

// Ticks are collected for this long and sent as one request.
const TICK_BATCH_MS = 250;

const FILTERS = [
  { key: 'all', label: () => gettext('All') },
  { key: 'plus', label: (labels) => labels.plus },
  { key: 'minus', label: (labels) => labels.minus },
  { key: 'unticked', label: () => gettext('Unticked') },
];

const matchesQuery = (line, query) => {
  if (!query) return true;
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const digits = q.replace(/[$,\s-]/g, '');
  if (digits && /^\d*\.?\d*$/.test(digits) && line.amount.replace('-', '').includes(digits)) return true;
  return `${line.payee} ${line.description} ${line.category}`.toLowerCase().includes(q);
};

/**
 * Step two: tick lines until the difference is zero.
 *
 * The summary is computed here from the local tick set, in integer cents, so
 * it answers each click at once. The server is told in batches; it recomputes
 * everything and sends back hints. Each batch takes a ticket and only the
 * newest response may paint -- an older one arriving late must not overwrite
 * fresher hints (the same rule as the budget page's autosave).
 */
const Workspace = ({ draft, api, onReload, onFinished, onDiscarded, onAddMissing, notify }) => {
  const account = draft.account;
  const labels = labelsFor(account);

  const [lines, setLines] = useState(draft.lines);
  const [hints, setHints] = useState(draft.hints);
  const [uncategorized, setUncategorized] = useState(draft.uncategorized);
  const [filter, setFilter] = useState('all');
  const [query, setQuery] = useState('');
  const [highlight, setHighlight] = useState([]);
  const [finishOpen, setFinishOpen] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editDate, setEditDate] = useState(draft.statement_date);
  const [editBalance, setEditBalance] = useState(draft.statement_balance);
  const [saving, setSaving] = useState(false);
  const [pendingCount, setPendingCount] = useState(0);

  const pending = useRef(new Map());
  const timer = useRef(null);
  const ticket = useRef(0);
  const inFlight = useRef(Promise.resolve());
  const tableRef = useRef(null);

  // A new draft payload (reload, edit, include-later) replaces local state.
  useEffect(() => {
    setLines(draft.lines);
    setHints(draft.hints);
    setUncategorized(draft.uncategorized);
    setEditDate(draft.statement_date);
    setEditBalance(draft.statement_balance);
  }, [draft]);

  const tickedCents = useMemo(
    () => lines.reduce((sum, line) => (line.ticked ? sum + toCents(line.amount) : sum), 0),
    [lines],
  );
  const openingCents = toCents(draft.summary.opening);
  const statementCents = toCents(draft.statement_balance);
  const differenceCents = statementCents - openingCents - tickedCents;
  const tickedCount = lines.filter((line) => line.ticked).length;
  const plusCents = lines.reduce((s, l) => (l.ticked && toCents(l.amount) > 0 ? s + toCents(l.amount) : s), 0);
  const minusCents = lines.reduce((s, l) => (l.ticked && toCents(l.amount) < 0 ? s + toCents(l.amount) : s), 0);

  const flush = useCallback(() => {
    clearTimeout(timer.current);
    timer.current = null;
    if (pending.current.size === 0) return inFlight.current;
    const batch = new Map(pending.current);
    pending.current.clear();
    const mine = ++ticket.current;
    const on = [...batch].filter(([, v]) => v).map(([id]) => id);
    const off = [...batch].filter(([, v]) => !v).map(([id]) => id);

    inFlight.current = inFlight.current
      .then(async () => {
        let response = null;
        if (on.length) response = await api.tick(draft.id, on, true);
        if (off.length) response = await api.tick(draft.id, off, false);
        if (mine === ticket.current && response) {
          setHints(response.hints);
          setUncategorized(response.uncategorized);
        }
      })
      .catch((err) => {
        notify(err.message || gettext('Could not save your ticks.'), 'error');
        onReload();
      })
      .finally(() => setPendingCount(pending.current.size));
    return inFlight.current;
  }, [api, draft.id, notify, onReload]);

  useEffect(() => () => clearTimeout(timer.current), []);

  const setTicked = useCallback(
    (ids, value) => {
      const idSet = new Set(ids);
      setLines((prev) => prev.map((line) => (idSet.has(line.id) ? { ...line, ticked: value } : line)));
      ids.forEach((id) => pending.current.set(id, value));
      setPendingCount(pending.current.size);
      clearTimeout(timer.current);
      timer.current = setTimeout(flush, TICK_BATCH_MS);
    },
    [flush],
  );

  const toggle = (line) => setTicked([line.id], !line.ticked);

  const visible = useMemo(
    () =>
      lines.filter((line) => {
        const cents = toCents(line.amount);
        if (filter === 'plus' && cents <= 0) return false;
        if (filter === 'minus' && cents >= 0) return false;
        if (filter === 'unticked' && line.ticked) return false;
        return matchesQuery(line, query);
      }),
    [lines, filter, query],
  );

  const moveFocus = (from, delta) => {
    const rows = [...(tableRef.current?.querySelectorAll('[data-row]') || [])];
    const next = rows[rows.indexOf(from) + delta];
    if (next) next.focus();
  };

  const onRowKey = (e, line) => {
    if (e.key === ' ' || e.key === 'Enter') {
      e.preventDefault();
      toggle(line);
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      moveFocus(e.currentTarget, 1);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      moveFocus(e.currentTarget, -1);
    }
  };

  const tickThrough = async () => {
    await flush();
    try {
      await api.tickThrough(draft.id, draft.statement_date);
      onReload();
    } catch (err) {
      notify(err.message, 'error');
    }
  };

  const untickAll = async () => {
    await flush();
    try {
      await api.untickAll(draft.id);
      onReload();
    } catch (err) {
      notify(err.message, 'error');
    }
  };

  const saveStatement = async () => {
    const balance = sanitizeAmount(editBalance);
    if (balance === null) return;
    setSaving(true);
    try {
      await flush();
      await api.update(draft.id, { statement_date: editDate, statement_balance: balance });
      setEditing(false);
      onReload();
    } catch (err) {
      notify(err.message, 'error');
    } finally {
      setSaving(false);
    }
  };

  const discard = async () => {
    if (!window.confirm(gettext('Discard this reconciliation? Your ticks are thrown away; nothing is reconciled.'))) {
      return;
    }
    try {
      await api.discard(draft.id);
      onDiscarded();
    } catch (err) {
      notify(err.message, 'error');
    }
  };

  const finish = async (adjust) => {
    setFinishing(true);
    try {
      await flush();
      const body = adjust ? { adjust: true, expected_difference: (differenceCents / 100).toFixed(2) } : {};
      const result = await api.finish(draft.id, body);
      setFinishOpen(false);
      onFinished(result);
    } catch (err) {
      notify(err.message, 'error');
      if (err.status === 409) onReload();
    } finally {
      setFinishing(false);
    }
  };

  const clickFinish = async () => {
    await flush();
    if (differenceCents === 0) finish(false);
    else setFinishOpen(true);
  };

  const balanced = differenceCents === 0;
  const highlighted = new Set(highlight);

  return (
    <div className="space-y-4" data-testid="reconcile-workspace" data-draft-id={draft.id}>
      {/* Summary strip */}
      <section className="app-surface sticky top-2 z-10 p-3" data-testid="reconcile-summary">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div>
            <div className="text-xs text-base-content/70">
              {labels.balance} · {formatDate(draft.statement_date)}
            </div>
            <div className="money text-lg font-semibold" data-testid="summary-statement">
              {formatMoney(draft.statement_balance)}
            </div>
          </div>
          <div>
            <div className="text-xs text-base-content/70">{gettext('Starting balance')}</div>
            <div className="money text-lg" data-testid="summary-opening">
              {formatMoney(draft.summary.opening)}
            </div>
          </div>
          <div>
            <div className="text-xs text-base-content/70">
              {interpolate(gettext('Ticked (%s)'), [tickedCount])}
            </div>
            <div className="money text-sm">
              <span className="text-success">{formatMoney(plusCents / 100)}</span>
              {' / '}
              <span className="text-error">{formatMoney(minusCents / 100)}</span>
            </div>
          </div>
          <div>
            <div className="text-xs text-base-content/70">{gettext('Difference')}</div>
            <div
              className={`money text-2xl font-bold ${balanced ? 'text-success' : ''}`}
              data-testid="summary-difference"
              aria-live="polite"
            >
              {formatMoney(differenceCents / 100)}
            </div>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            className={`btn btn-sm ${balanced ? 'btn-success' : 'btn-primary'}`}
            onClick={clickFinish}
            disabled={finishing}
            data-testid="reconcile-finish-btn"
          >
            {balanced ? gettext('Finish — you’re clear') : gettext('Finish…')}
          </button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEditing((v) => !v)} data-testid="edit-statement-btn">
            {gettext('Edit statement')}
          </button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={discard} data-testid="discard-draft-btn">
            {gettext('Discard')}
          </button>
          <span className="text-xs text-base-content/70 ml-auto" aria-live="polite">
            {pendingCount > 0 ? gettext('Saving…') : gettext('All ticks saved')}
          </span>
        </div>
        {editing && (
          <div className="mt-3 grid gap-3 sm:grid-cols-3 items-end" data-testid="edit-statement-form">
            <DateField label={gettext('Statement date')} value={editDate} onChange={setEditDate} testId="edit-statement-date" />
            <label className="form-control w-full">
              <span className="label-text mb-1 block text-sm text-base-content/70">{labels.balance}</span>
              <input
                type="text"
                inputMode="decimal"
                className="input input-bordered w-full money"
                value={editBalance}
                onChange={(e) => setEditBalance(e.target.value)}
                data-testid="edit-statement-balance"
              />
            </label>
            <button type="button" className="btn btn-primary btn-sm" onClick={saveStatement} disabled={saving}>
              {gettext('Save')}
            </button>
          </div>
        )}
      </section>

      {draft.drift && (
        <div role="alert" className="alert alert-warning items-start" data-testid="drift-banner">
          <Icon name="triangle-alert" className="w-5 h-5 shrink-0" />
          <div className="text-sm">
            <div className="font-medium">
              {interpolate(gettext('Since your %s reconciliation, the reconciled balance has moved by %s.'), [
                formatDate(draft.drift.since),
                formatMoney(draft.drift.amount),
              ])}
            </div>
            <ul className="mt-1 list-disc pl-5">
              {draft.drift.lines.map((line) => (
                <li key={line.id}>
                  {line.label} · {formatDate(line.date)} · <span className="money">{formatMoney(line.amount)}</span> —{' '}
                  {line.reason === 'undone'
                    ? interpolate(gettext('its %s statement was undone'), [formatDate(line.statement_date)])
                    : line.reason === 'voided'
                      ? gettext('voided')
                      : interpolate(gettext('unreconciled from the %s statement'), [formatDate(line.statement_date)])}
                </li>
              ))}
            </ul>
            {draft.drift.lines.some((line) => line.reason !== 'voided') && (
              <div className="mt-1">{gettext('They are back in the list below, ready to tick.')}</div>
            )}
          </div>
        </div>
      )}

      {uncategorized.count > 0 && (
        <div role="status" className="alert alert-info items-start" data-testid="uncategorized-callout">
          <Icon name="info" className="w-5 h-5 shrink-0" />
          <div className="text-sm">
            <div>
              {interpolate(
                gettext(
                  '%s transaction(s) from this account (%s) aren’t categorized yet, so they can’t be reconciled until they are.',
                ),
                [uncategorized.count, formatMoney(uncategorized.total)],
              )}
            </div>
            <a className="link font-medium" href={uncategorized.categorize_url}>
              {gettext('Categorize them')}
            </a>
          </div>
        </div>
      )}

      {!balanced && (
        <DifferenceHints
          hints={hints}
          onAction={(hint) => setTicked(hint.action_ids || hint.line_ids, hint.action === 'tick')}
          onFocus={setHighlight}
        />
      )}

      <section className="app-surface p-3">
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <div role="tablist" className="join">
            {FILTERS.map((f) => (
              <button
                key={f.key}
                type="button"
                role="tab"
                aria-selected={filter === f.key}
                className={`join-item btn btn-sm ${filter === f.key ? 'btn-active' : ''}`}
                onClick={() => setFilter(f.key)}
                data-testid={`filter-${f.key}`}
              >
                {f.label(labels)}
              </button>
            ))}
          </div>
          <label className="input input-bordered input-sm flex items-center gap-2 w-full sm:w-56">
            <Icon name="search" className="w-4 h-4 text-base-content/40" />
            <input
              type="search"
              className="grow"
              placeholder={gettext('Search or type an amount')}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              data-testid="line-search"
            />
          </label>
          <div className="flex gap-2 sm:ml-auto">
            <button type="button" className="btn btn-outline btn-sm" onClick={tickThrough} data-testid="tick-through-btn">
              {interpolate(gettext('Tick all through %s'), [formatDate(draft.statement_date)])}
            </button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={untickAll} data-testid="untick-all-btn">
              {gettext('Untick all')}
            </button>
          </div>
        </div>

        <div className="overflow-x-auto" ref={tableRef}>
          <table className="table table-sm table-quiet" data-testid="reconcile-lines">
            <thead>
              <tr>
                <th className="w-8">
                  <span className="sr-only">{gettext('Ticked')}</span>
                </th>
                <th className="hidden sm:table-cell">{gettext('Date')}</th>
                <th>{gettext('Payee / Description')}</th>
                <th className="hidden md:table-cell">{gettext('Category')}</th>
                <th className="text-right hidden sm:table-cell">{labels.plus}</th>
                <th className="text-right hidden sm:table-cell">{labels.minus}</th>
                <th className="text-right sm:hidden">{gettext('Amount')}</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((line) => {
                const cents = toCents(line.amount);
                return (
                  <tr
                    key={line.id}
                    data-row
                    tabIndex={0}
                    className={`cursor-pointer focus:outline-2 focus:outline-primary ${line.ticked ? 'bg-primary/5' : ''} ${
                      highlighted.has(line.id) ? 'bg-warning/15' : ''
                    }`}
                    onClick={() => toggle(line)}
                    onKeyDown={(e) => onRowKey(e, line)}
                    data-testid={`line-row-${line.id}`}
                    data-ticked={line.ticked ? 'true' : 'false'}
                  >
                    <td>
                      <input
                        type="checkbox"
                        className="checkbox checkbox-sm checkbox-primary rounded-sm"
                        checked={line.ticked}
                        onChange={() => toggle(line)}
                        onClick={(e) => e.stopPropagation()}
                        aria-label={interpolate(gettext('Tick %s'), [line.payee || line.description])}
                        tabIndex={-1}
                        data-testid={`line-check-${line.id}`}
                      />
                    </td>
                    <td className="whitespace-nowrap hidden sm:table-cell">
                      {formatDate(line.date)}
                      {line.after_statement && (
                        <div className="badge badge-ghost badge-xs block mt-0.5">{gettext('after statement')}</div>
                      )}
                    </td>
                    <td>
                      <div className="text-xs text-base-content/70 sm:hidden">
                        {formatDate(line.date)}
                        {line.after_statement && ` · ${gettext('after statement')}`}
                      </div>
                      <div>{line.payee || line.description}</div>
                      {line.payee && line.description && (
                        <div className="text-xs text-base-content/70">{line.description}</div>
                      )}
                    </td>
                    <td className="hidden md:table-cell text-base-content/70">{line.category}</td>
                    <td className="text-right money whitespace-nowrap hidden sm:table-cell">
                      {cents > 0 ? formatMoney(line.amount) : ''}
                    </td>
                    <td className="text-right money whitespace-nowrap hidden sm:table-cell">
                      {cents < 0 ? formatMoney(-cents / 100) : ''}
                    </td>
                    <td className={`text-right money whitespace-nowrap sm:hidden ${cents < 0 ? 'text-error' : ''}`}>
                      {formatMoney(line.amount)}
                    </td>
                  </tr>
                );
              })}
              {visible.length === 0 && (
                <tr>
                  <td colSpan={7} className="text-center text-base-content/70 py-6">
                    {lines.length === 0
                      ? gettext('No unreconciled transactions on this account.')
                      : gettext('Nothing matches this filter.')}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
          {draft.include_later ? (
            <button type="button" className="btn btn-ghost btn-xs" onClick={() => onReload(false)}>
              {gettext('Hide transactions well after the statement date')}
            </button>
          ) : (
            <button type="button" className="btn btn-ghost btn-xs" onClick={() => onReload(true)} data-testid="include-later-btn">
              {gettext('Show transactions after the statement date')}
            </button>
          )}
          {account.has_feed && onAddMissing && (
            <button type="button" className="btn btn-ghost btn-xs" onClick={onAddMissing} data-testid="add-missing-btn">
              <Icon name="plus" className="w-3 h-3" /> {gettext('Add missing transaction')}
            </button>
          )}
          <span className="text-xs text-base-content/70 sm:ml-auto">
            {gettext('Click a row or press Space to tick it; ↑/↓ move between rows.')}
          </span>
        </div>
      </section>

      <Modal
        open={finishOpen}
        onClose={() => setFinishOpen(false)}
        size="sm"
        title={gettext('The statement doesn’t balance yet')}
        testId="finish-dialog"
        actions={
          <>
            <button type="button" className="btn btn-primary btn-sm" onClick={() => setFinishOpen(false)} autoFocus>
              {gettext('Keep working')}
            </button>
            <button
              type="button"
              className="btn btn-outline btn-warning btn-sm"
              onClick={() => finish(true)}
              disabled={finishing}
              data-testid="finish-adjust-btn"
            >
              {interpolate(gettext('Finish with a %s adjustment'), [formatMoney(differenceCents / 100)])}
            </button>
          </>
        }
      >
        <div className="space-y-2 text-sm">
          <p>
            {interpolate(gettext('Your statement says %s. With what you’ve ticked, Koala says %s.'), [
              formatMoney(draft.statement_balance),
              formatMoney((statementCents - differenceCents) / 100),
            ])}
          </p>
          <p>
            {gettext(
              'An adjustment records the difference against the “Reconciliation Adjustments” equity account so the statement balances. It won’t appear in your income or expenses. Your draft is saved — you can come back later instead.',
            )}
          </p>
        </div>
      </Modal>
    </div>
  );
};

export default Workspace;
