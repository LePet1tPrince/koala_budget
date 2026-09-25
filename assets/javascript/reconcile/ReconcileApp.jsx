import React, { useCallback, useEffect, useRef, useState } from 'react';

import { Toast } from '../common/Toast';
import { formatMoney } from '../common/amount';
import { fireConfetti } from '../common/confetti';
import EditTransactionModal from '../bank_feed/react/EditTransactionModal';
import { getTransactionApi } from '../bank_feed/bank_feed.js';
import { bookFromBase } from '../common/book';
import History from './History';
import StartForm from './StartForm';
import Workspace from './Workspace';
import { formatDate } from './labels';

/* globals gettext, interpolate */

/**
 * The per-account reconciliation page: start form → workspace → result, with
 * the account's statement history underneath.
 *
 * A draft lives on the server, so reopening the page (or a second household
 * member opening it) lands back in the workspace with every tick in place.
 */
const ReconcileApp = ({ props, api }) => {
  const account = props.account;
  const [view, setView] = useState(props.draft_id ? 'loading' : 'start');
  const [draft, setDraft] = useState(null);
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState(props.history);
  const [startError, setStartError] = useState('');
  const [busy, setBusy] = useState(false);
  const [undoing, setUndoing] = useState(null);
  const [addOpen, setAddOpen] = useState(false);
  const [toast, setToast] = useState(null);
  const includeLater = useRef(false);
  const preselect = useRef(props.preselect_line_ids || []);

  const notify = useCallback((message, severity = 'info') => setToast({ message, severity }), []);

  // The `?lines=` handoff from the bank feed is used once, then dropped from the
  // URL so a reload doesn't re-tick rows the user has since unticked.
  const takePreselect = () => {
    const ids = preselect.current;
    preselect.current = [];
    if (ids.length && window.history?.replaceState) {
      const url = new URL(window.location.href);
      url.searchParams.delete('lines');
      window.history.replaceState(null, '', url);
    }
    return ids;
  };

  const load = useCallback(
    async (id, later) => {
      if (later !== undefined) includeLater.current = later;
      const payload = await api.get(id, includeLater.current);
      setDraft(payload);
      setView('work');
      return payload;
    },
    [api],
  );

  const reload = useCallback(
    (later) => {
      if (!draft) return Promise.resolve();
      return load(draft.id, typeof later === 'boolean' ? later : undefined).catch((err) =>
        notify(err.message, 'error'),
      );
    },
    [draft, load, notify],
  );

  useEffect(() => {
    if (!props.draft_id) return;
    (async () => {
      try {
        const ids = takePreselect();
        if (ids.length) await api.tick(props.draft_id, ids, true);
        await load(props.draft_id);
      } catch (err) {
        notify(err.message, 'error');
        await load(props.draft_id).catch(() => setView('start'));
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const refreshHistory = async () => {
    try {
      const payload = await api.history(account.id);
      setHistory(payload.history);
    } catch (err) {
      notify(err.message, 'error');
    }
  };

  const start = async (statementDate, balance) => {
    setBusy(true);
    setStartError('');
    try {
      const payload = await api.start({
        account: account.id,
        statement_date: statementDate,
        statement_balance: balance,
        line_ids: takePreselect(),
      });
      setDraft(payload);
      setView('work');
    } catch (err) {
      setStartError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const finished = (payload) => {
    setResult(payload);
    setDraft(null);
    setView('done');
    refreshHistory();
    if (Number(payload.adjustment_amount) === 0) fireConfetti({ origin: 'cannons' });
  };

  const undo = async (rec) => {
    const message = interpolate(
      gettext('Undo the %s statement? Its transactions become unreconciled and any adjustment is voided.'),
      [formatDate(rec.statement_date)],
    );
    if (!window.confirm(message)) return;
    setUndoing(rec.id);
    try {
      await api.undo(rec.id);
      notify(gettext('Statement undone. Its transactions can be reconciled again.'), 'success');
      await refreshHistory();
      if (draft) await reload();
    } catch (err) {
      notify(err.message, 'error');
    } finally {
      setUndoing(null);
    }
  };

  // "Add missing transaction" reuses the feed's own editor, then ticks what it made.
  const addMissing = async (data) => {
    const row = await getTransactionApi(props.book_base).createTransaction({ ...data, account: account.id });
    const payload = await load(draft.id);
    const line = payload.lines.find((l) => l.entry_id === row.journal_entry_id);
    if (line && !line.ticked) {
      await api.tick(draft.id, [line.id], true);
      await load(draft.id);
    }
    notify(gettext('Transaction added and ticked.'), 'success');
  };

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold" data-testid="reconcile-title">
            {interpolate(gettext('Reconcile %s'), [account.name])}
          </h1>
          <p className="text-sm text-base-content/70">
            {account.is_liability ? gettext('Credit card or loan statement') : gettext('Bank statement')}
            {!account.has_feed && ` · ${gettext('no bank feed')}`}
          </p>
        </div>
        <div className="flex gap-2">
          <a className="btn btn-ghost btn-sm" href={props.urls.hub}>
            {gettext('All accounts')}
          </a>
          <a className="btn btn-ghost btn-sm" href={props.urls.account_detail}>
            {gettext('Account details')}
          </a>
        </div>
      </header>

      {view === 'loading' && <div className="app-card animate-pulse h-40" aria-hidden="true" />}

      {view === 'start' && (
        <StartForm
          account={account}
          defaultDate={props.default_statement_date}
          previous={props.previous}
          reconciledBalance={props.reconciled_balance}
          preselectCount={preselect.current.length}
          onStart={start}
          busy={busy}
          error={startError}
        />
      )}

      {view === 'work' && draft && (
        <Workspace
          draft={draft}
          api={api}
          onReload={reload}
          onFinished={finished}
          onDiscarded={() => {
            setDraft(null);
            setView('start');
          }}
          onAddMissing={account.has_feed ? () => setAddOpen(true) : null}
          notify={notify}
        />
      )}

      {view === 'done' && result && (
        <section className="app-card" data-testid="reconcile-done">
          <div role="status" className={`alert ${Number(result.adjustment_amount) === 0 ? 'alert-success' : 'alert-warning'}`}>
            <span>
              {Number(result.adjustment_amount) === 0
                ? interpolate(gettext('Reconciled. Your statement and Koala both say %s as of %s. You’re clear.'), [
                    formatMoney(result.statement_balance),
                    formatDate(result.statement_date),
                  ])
                : interpolate(gettext('Reconciled with a %s adjustment. The statement balance of %s is recorded.'), [
                    formatMoney(result.adjustment_amount),
                    formatMoney(result.statement_balance),
                  ])}
            </span>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <a className="btn btn-primary btn-sm" href={result.url}>
              {gettext('View statement')}
            </a>
            <a className="btn btn-ghost btn-sm" href={window.location.pathname}>
              {gettext('Reconcile the next statement')}
            </a>
            {account.has_feed && (
              <a className="btn btn-ghost btn-sm" href={props.urls.feed}>
                {gettext('Back to the bank feed')}
              </a>
            )}
          </div>
        </section>
      )}

      <History history={history} onUndo={undo} busyId={undoing} />

      {account.has_feed && addOpen && (
        <EditTransactionModal
          open={addOpen}
          onClose={() => setAddOpen(false)}
          transaction={null}
          mode="create"
          allAccounts={props.all_accounts}
          allPayees={props.all_payees}
          book={bookFromBase(props.book_base)}
          onSave={addMissing}
        />
      )}

      <Toast
        open={!!toast}
        message={toast?.message}
        severity={toast?.severity}
        onClose={() => setToast(null)}
        testId="reconcile-toast"
      />
    </div>
  );
};

export default ReconcileApp;
