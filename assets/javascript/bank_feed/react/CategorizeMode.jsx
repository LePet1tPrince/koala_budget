/* globals gettext, interpolate, ngettext */
import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';

import DateRangePicker from '../../common/DateRangePicker';
import Icon from '../../common/Icon';
import { Toast } from '../../common/Toast';
import { accountKind, pickableAccounts } from '../../common/accountKind';
import { formatMoney } from '../../common/amount';
import RuleBuilderDialog, { draftFromRow } from '../../rules/RuleBuilderDialog';
import { rulesApiForBook } from '../../rules/api';
import { getBatchOperationsApi, getFeedPageApi, getTransactionApi, getUploadApiHelpers } from '../bank_feed';
import { directionOf, usageById, withUse } from '../categoryOrder';
import { queryFromUrl, scopeSearch } from '../feedQuery';
import CreateAccountModal from './CSVUploadWizard/CreateAccountModal';
import TransactionModal from './TransactionModal';
import AfterPick from './categorize/AfterPick';
import CategoryPicker from './categorize/CategoryPicker';
import QueueCards from './categorize/QueueCards';
import QuickWins from './categorize/QuickWins';
import Summary from './categorize/Summary';
import { mergeSuggestions } from './categorize/matching';
import {
  applyToFigures,
  buildUnits,
  countOf,
  figuresFromBudgetMonth,
  includedIds,
  minutesLeft,
  monthOf,
  remainderOf,
  rowId,
  secondsPerUnit,
  signedAmount,
  totalOf,
  withoutIds,
} from './categorize/queue';
import { feedTransaction } from './feedTransaction';

/**
 * Categorize Mode: the Inbox's uncategorized rows, one merchant at a time.
 *
 * The queue (`feed/categorize_queue/`) is groups, not rows -- one pick files
 * every row of an account, direction and merchant. It opens on the groups the
 * server is sure about (Quick wins, one press for all of them), then shows the
 * rest as a stack of cards. A pick is shown at once and saved behind it; a
 * refusal brings the card back. Every pick can be undone (`feed/uncategorize/`).
 *
 * Runs as its own page (`categorize-app.jsx`) or over the Inbox (`onExit`).
 */

// At most this many suggestions are shown for a transaction.
const MAX_SUGGESTIONS = 3;
// Quick wins open the queue when at least this many groups are confident.
const QUICK_WINS_MIN = 2;
// Units ahead of the current one whose month's budget figures are fetched early.
const FIGURES_PREFETCH = 4;
// A first Escape arms the exit for this long; a second one leaves.
const EXIT_ARM_MS = 2500;

const newSession = () => {
  const now = Date.now();
  return { filed: 0, amount: 0, rules: 0, startedAt: now, lastAt: now, pickTimes: [] };
};

// The feed row maps `merchant_name` onto `payee`; this is the pair the card edits.
function detailsOf(row) {
  return { payee: row?.payee ?? row?.merchant_name ?? '', description: row?.description ?? '' };
}

// What a draft changes, as a `batch_edit` payload; null when nothing changed.
function changedDetails(row, draft) {
  if (!row || !draft) return null;
  const original = detailsOf(row);
  const changes = {};
  if (draft.payee.trim() !== original.payee.trim()) changes.payee = draft.payee.trim();
  if (draft.description.trim() !== original.description.trim()) changes.description = draft.description.trim();
  return Object.keys(changes).length > 0 ? changes : null;
}

function scopeFromUrl() {
  const { accounts, startDate, endDate } = queryFromUrl();
  return { accounts, startDate, endDate };
}

const isScoped = (scope) => scope.accounts.length > 0 || Boolean(scope.startDate || scope.endDate);

const isEditable = (el) => el && (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName));

const media = (query) => (typeof window !== 'undefined' && window.matchMedia?.(query).matches) || false;

/** Narrow the queue to one feed account and/or a date range. Changing either reloads it. */
function ScopeBar({ scope, feedAccounts, onChange }) {
  const multi = scope.accounts.length > 1;
  const accountValue = multi ? 'multi' : (scope.accounts[0] ?? '');
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="categorize-scope">
      <select
        className="select select-bordered select-sm w-auto max-w-xs"
        value={accountValue}
        onChange={(e) => {
          const v = e.target.value;
          if (v === 'multi') return;
          onChange({ ...scope, accounts: v ? [Number(v)] : [] });
        }}
        aria-label={gettext('Account')}
        data-testid="categorize-scope-account"
      >
        <option value="">{gettext('All accounts')}</option>
        {multi && (
          <option value="multi" disabled>
            {interpolate(gettext('%s accounts'), [scope.accounts.length])}
          </option>
        )}
        {feedAccounts.map((a) => (
          <option key={a.id} value={a.id}>
            {a.name}
          </option>
        ))}
      </select>
      <DateRangePicker
        startDate={scope.startDate}
        endDate={scope.endDate}
        onApply={(start, end) => onChange({ ...scope, startDate: start || '', endDate: end || '' })}
      />
      {isScoped(scope) && (
        <button
          type="button"
          className="btn btn-ghost btn-xs"
          onClick={() => onChange({ accounts: [], startDate: '', endDate: '' })}
          data-testid="categorize-scope-clear"
        >
          ✕ {gettext('Clear')}
        </button>
      )}
    </div>
  );
}

/** "12 of 40 sorted · $1,240 of $1,890 · about 2 min left" with a bar by money. */
function Progress({ done, total, amountDone, amountTotal, minutes }) {
  const pct = amountTotal > 0 ? (amountDone / amountTotal) * 100 : total > 0 ? (done / total) * 100 : 0;
  return (
    <div className="w-full" data-testid="categorize-progress">
      <div className="flex justify-between gap-2 text-xs mb-1">
        <span className="font-semibold text-primary">
          {interpolate(gettext('%s of %s sorted'), [formatMoney(amountDone), formatMoney(amountTotal)])}
        </span>
        <span className="text-base-content/70">
          {interpolate(gettext('%s of %s'), [done, total])}
          {minutes > 0
            ? ` · ${interpolate(ngettext('about %s min left', 'about %s min left', minutes), [minutes])}`
            : ''}
        </span>
      </div>
      <div className="w-full bg-base-300 rounded-full h-2.5 overflow-hidden">
        <div
          className="bg-gradient-to-r from-primary to-secondary h-full rounded-full transition-all duration-500 ease-out"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

/**
 * The card just filed, flying into the category it was filed under (or off to
 * the right after a swipe). Drawn over everything and gone in a third of a second;
 * the queue has already moved on underneath it.
 */
function Ghost({ ghost, onDone }) {
  const ref = useRef(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || !el.animate) {
      onDone();
      return undefined;
    }
    const { from, to } = ghost;
    const frames = to
      ? [
          { transform: 'translate(0, 0) scale(1)', opacity: 1 },
          {
            transform: `translate(${to.left + to.width / 2 - (from.left + from.width / 2)}px, ${
              to.top + to.height / 2 - (from.top + from.height / 2)
            }px) scale(0.12)`,
            opacity: 0.2,
          },
        ]
      : [
          { transform: 'translate(0, 0) rotate(0deg)', opacity: 1 },
          { transform: 'translate(120%, -10%) rotate(14deg)', opacity: 0 },
        ];
    const animation = el.animate(frames, { duration: 340, easing: 'cubic-bezier(.5,0,.75,0)', fill: 'forwards' });
    animation.onfinish = onDone;
    return () => animation.cancel();
  }, [ghost, onDone]);
  const { from } = ghost;
  return (
    <div
      ref={ref}
      className="fixed pointer-events-none card bg-base-100 border border-primary shadow-2xl"
      style={{ left: from.left, top: from.top, width: from.width, height: from.height, zIndex: 9998 }}
      aria-hidden="true"
    >
      <div className="card-body p-5">
        <p className="font-bold text-xl truncate">{ghost.title}</p>
        <p className={`text-3xl font-black text-right ${ghost.amount > 0 ? 'text-error' : 'text-success'}`}>
          {ghost.amount > 0 ? `-${formatMoney(ghost.amount)}` : `+${formatMoney(-ghost.amount)}`}
        </p>
      </div>
    </div>
  );
}

export default function CategorizeMode({
  book,
  allAccounts,
  allAccountGroups,
  allPayees = [],
  categoryUsage = [],
  backUrl,
  onExit = null,
}) {
  const pageApi = useMemo(() => getFeedPageApi(book.base), [book]);
  const uploadApi = useMemo(() => getUploadApiHelpers(book.base), [book]);
  const batchApi = useMemo(() => getBatchOperationsApi(book.base), [book]);
  const transactionApi = useMemo(() => getTransactionApi(book.base), [book]);
  const rulesApi = useMemo(() => rulesApiForBook(book.base), [book]);
  const reducedMotion = useMemo(() => media('(prefers-reduced-motion: reduce)'), []);
  const finePointer = useMemo(() => media('(pointer: fine)'), []);

  const [phase, setPhase] = useState('loading'); // loading | quickwins | cards
  const [scope, setScope] = useState(scopeFromUrl);
  const [rowsById, setRowsById] = useState(() => new Map());
  const [units, setUnits] = useState([]);
  const [pile, setPile] = useState([]); // skipped units, offered again at the end
  const [excluded, setExcluded] = useState({}); // unit key -> Set of ids unticked in review
  const [drafts, setDrafts] = useState({}); // lead row id -> {payee, description}
  const [editing, setEditing] = useState(false);
  const [history, setHistory] = useState([]); // filed picks, newest last: what Undo takes back
  const [undoing, setUndoing] = useState(false);
  const [session, setSession] = useState(newSession);
  const [figures, setFigures] = useState({}); // 'YYYY-MM' -> {categoryId: figure}
  const figuresAsked = useRef(new Set());
  const [localAccounts, setLocalAccounts] = useState(() => pickableAccounts(allAccounts));
  const [usage, setUsage] = useState(() => usageById(categoryUsage));
  const [transferPairs, setTransferPairs] = useState([]);
  const [last, setLast] = useState(null); // {count, label, accountId, month} of the latest pick
  const [ruleOffer, setRuleOffer] = useState(null);
  const [error, setError] = useState(null);
  const [exitArmed, setExitArmed] = useState(false);
  const [ghost, setGhost] = useState(null);
  const [quickBusy, setQuickBusy] = useState(false);
  const [showCreateAccount, setShowCreateAccount] = useState(false);
  const [splitOpen, setSplitOpen] = useState(false);
  const [ruleDialog, setRuleDialog] = useState(null);
  const [canEditRules, setCanEditRules] = useState(false);
  const [ruleNotice, setRuleNotice] = useState('');
  const clearRuleNotice = useCallback(() => setRuleNotice(''), []);
  const searchRef = useRef(null);
  const commandsRef = useRef(null);
  const topCardRef = useRef(null);
  const historySeq = useRef(0);

  const accountsById = useMemo(() => Object.fromEntries(localAccounts.map((a) => [a.id, a])), [localAccounts]);
  const payeeOptions = useMemo(() => allPayees.map((p) => p.name).filter(Boolean), [allPayees]);
  const feedAccounts = useMemo(
    () => allAccounts.filter((a) => a.has_feed && !a.is_archived).sort((a, b) => a.name.localeCompare(b.name)),
    [allAccounts],
  );
  const backHref = `${backUrl}${scopeSearch(scope)}`;
  const exit = useCallback(() => {
    if (onExit) onExit();
    else window.location.href = backHref;
  }, [onExit, backHref]);

  useEffect(() => {
    rulesApi
      .prompts()
      .then((p) => setCanEditRules(!!p.can_edit))
      .catch(() => setCanEditRules(false));
  }, [rulesApi]);

  // --- loading ---------------------------------------------------------

  const load = useCallback(
    async (forScope, { keepSession = false } = {}) => {
      setPhase('loading');
      setError(null);
      try {
        const [rows, queue, pairs] = await Promise.all([
          pageApi.uncategorized(forScope),
          pageApi.categorizeQueue(forScope),
          batchApi.transferSuggestions().catch(() => []),
        ]);
        const byId = new Map(rows.map((r) => [rowId(r), r]));
        const built = buildUnits(queue.groups, byId);
        setRowsById((prev) => {
          if (!keepSession) return byId;
          // Rows already filed this session stay known, so Undo can bring them back.
          const merged = new Map(prev);
          byId.forEach((row, id) => merged.set(id, row));
          return merged;
        });
        setUnits(built);
        setPile([]);
        setExcluded({});
        setTransferPairs(pairs || []);
        if (!keepSession) {
          setSession(newSession());
          setHistory([]);
          setLast(null);
          setRuleOffer(null);
        }
        setPhase(built.filter((u) => u.confident).length >= QUICK_WINS_MIN ? 'quickwins' : 'cards');
      } catch (err) {
        console.error('Failed to load the queue:', err);
        setError(err.message || gettext('Could not load the transactions.'));
        setPhase('cards');
      }
    },
    [pageApi, batchApi],
  );

  useEffect(() => {
    load(scope);
    // The first load only: a scope change reloads through `changeScope`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // A new scope is a new queue; the URL follows so a reload keeps it.
  const changeScope = useCallback(
    (next) => {
      setScope(next);
      const url = `${window.location.pathname}${scopeSearch(next)}${window.location.hash}`;
      window.history.replaceState(window.history.state, '', url);
      load(next);
    },
    [load],
  );

  // --- the current unit --------------------------------------------------

  const unit = phase === 'cards' ? (units[0] ?? null) : null;
  const lead = unit ? rowsById.get(unit.ids[0]) : null;
  const leadId = rowId(lead);
  const suggestions = useMemo(
    () => (unit ? mergeSuggestions(unit.suggestions, lead, localAccounts, accountsById, MAX_SUGGESTIONS) : []),
    [unit, lead, localAccounts, accountsById],
  );
  const details = lead ? (drafts[leadId] ?? detailsOf(lead)) : null;
  const detailsDirty = lead ? changedDetails(lead, drafts[leadId]) !== null : false;

  useEffect(() => setEditing(false), [unit?.key]);

  // Possible duplicate transfers, by the id of each leg.
  const transferByRow = useMemo(() => {
    const byRow = {};
    transferPairs.forEach((pair) => {
      const legs = [pair.outflow, pair.inflow];
      legs.forEach((self, i) => {
        byRow[self.imported_transaction_id] = { pair, self, other: legs[1 - i] };
      });
    });
    return byRow;
  }, [transferPairs]);

  // The budget figures of the months about to be seen: what each category has
  // left, on the chips, and how a pick moves it.
  useEffect(() => {
    const months = new Set(
      units
        .slice(0, FIGURES_PREFETCH)
        .map((u) => monthOf(rowsById.get(u.ids[0])))
        .filter(Boolean),
    );
    months.forEach((month) => {
      if (figuresAsked.current.has(month)) return;
      figuresAsked.current.add(month);
      pageApi
        .budgetMonth(month)
        .then((body) => setFigures((prev) => ({ ...prev, [month]: figuresFromBudgetMonth(body) })))
        .catch(() => setFigures((prev) => ({ ...prev, [month]: {} })));
    });
  }, [units, rowsById, pageApi]);

  // --- what a pick does, and undoes ---------------------------------------

  /**
   * Apply (sign 1) or take back (sign -1) a pick's effect on what this page
   * shows: the session's counts, how often the category is used, its budget
   * figures and what a goal has left.
   */
  const applyEffects = useCallback((entry, sign) => {
    const parts = entry.parts.filter((p) => p.account);
    setSession((s) => ({
      ...s,
      filed: s.filed + sign * entry.parts.reduce((n, p) => n + p.ids.length, 0),
      amount: s.amount + sign * entry.parts.reduce((n, p) => n + p.absAmount, 0),
      lastAt: Date.now(),
      pickTimes: sign > 0 ? [...s.pickTimes, Date.now()] : s.pickTimes,
    }));
    setUsage((u) => parts.reduce((acc, p) => withUse(acc, p.account.id, p.direction, sign * p.ids.length), u));
    setFigures((prev) => {
      const next = { ...prev };
      parts.forEach((p) => {
        p.byMonth.forEach((amount, month) => {
          const figure = next[month]?.[p.account.id];
          const moved = applyToFigures(figure, p.account, sign * amount);
          if (moved) next[month] = { ...next[month], [p.account.id]: moved };
        });
      });
      return next;
    });
    const goalSpend = {};
    parts.forEach((p) => {
      if (accountKind(p.account) === 'goal') goalSpend[p.account.id] = (goalSpend[p.account.id] || 0) + p.amount;
    });
    if (Object.keys(goalSpend).length) {
      setLocalAccounts((prev) =>
        prev.map((a) =>
          goalSpend[a.id] == null || a.goal_left == null
            ? a
            : { ...a, goal_left: (parseFloat(a.goal_left) - sign * goalSpend[a.id]).toFixed(2) },
        ),
      );
    }
  }, []);

  /** One part of a pick: these ids of `unit`, filed under `account` (null for a split). */
  const partOf = useCallback(
    (u, ids, account) => {
      const byMonth = new Map();
      ids.forEach((id) => {
        const row = rowsById.get(id);
        const month = monthOf(row);
        byMonth.set(month, (byMonth.get(month) || 0) + signedAmount(row));
      });
      return {
        unit: { ...u, ids },
        ids,
        account,
        rows: ids.map((id) => rowsById.get(id)),
        amount: ids.reduce((s, id) => s + signedAmount(rowsById.get(id)), 0),
        absAmount: totalOf(ids, rowsById),
        byMonth,
        direction: directionOf(rowsById.get(ids[0])),
      };
    },
    [rowsById],
  );

  /** A pick's request failed: it never happened. The queue is re-read to be sure what did. */
  const failed = useCallback(
    (entry, err) => {
      console.error('Failed to categorize:', err);
      setHistory((h) => h.filter((e) => e.id !== entry.id));
      applyEffects(entry, -1);
      setLast(null);
      setError(err?.message || gettext('Could not categorize that transaction.'));
      load(scope, { keepSession: true });
    },
    [applyEffects, load, scope],
  );

  const launchGhost = useCallback(
    (targetEl, row) => {
      if (reducedMotion || !topCardRef.current) return;
      setGhost({
        key: Date.now(),
        from: topCardRef.current.getBoundingClientRect(),
        to: targetEl?.getBoundingClientRect?.() ?? null,
        title: row?.payee || row?.merchant_name || row?.description || '',
        amount: signedAmount(row),
      });
    },
    [reducedMotion],
  );

  /** File the current unit (its ticked rows) under `account`. */
  const file = useCallback(
    (account, sourceEl) => {
      if (!unit || !lead || !account) return;
      const ids = includedIds(unit, excluded);
      if (ids.length === 0) {
        setError(gettext('Tick at least one transaction to file.'));
        return;
      }
      setError(null);
      setExitArmed(false);
      const changes = changedDetails(lead, drafts[leadId]);
      const rest = remainderOf(unit, excluded);
      const part = partOf(unit, ids, account);
      launchGhost(sourceEl, { ...lead, ...(changes?.payee != null ? { payee: changes.payee } : {}) });

      // Shown at once: the next card is up before the server answers.
      setUnits((prev) => (rest ? [rest, ...prev.slice(1)] : prev.slice(1)));
      setExcluded((prev) => {
        const next = { ...prev };
        delete next[unit.key];
        return next;
      });
      if (changes) {
        // The rows carry the new names from now on, as the server will.
        setRowsById((prev) => {
          const next = new Map(prev);
          ids.forEach((id) => {
            const row = next.get(id);
            next.set(id, {
              ...row,
              ...(changes.payee != null ? { payee: changes.payee, merchant_name: changes.payee } : {}),
              ...(changes.description != null ? { description: changes.description } : {}),
            });
          });
          return next;
        });
        setDrafts((prev) => {
          const next = { ...prev };
          delete next[leadId];
          return next;
        });
      }

      const request = changes
        ? batchApi.batchEdit(ids, { category_id: account.id, ...changes })
        : pageApi.categorize(ids, account.id);
      historySeq.current += 1;
      const entry = { id: historySeq.current, parts: [part], promise: request };
      setHistory((h) => [...h, entry]);
      applyEffects(entry, 1);
      setLast({ count: ids.length, label: account.name, accountId: account.id, month: monthOf(lead) });
      setRuleOffer(null);

      const byRule = unit.suggestions[0]?.match_type === 'rule';
      request
        .then(() => {
          if (!canEditRules || byRule || lead.rule_match) return;
          rulesApi
            .draftFromTransaction(ids[0])
            .then((result) => {
              if (result?.offer) setRuleOffer({ draft: result.rule, coverage: result.coverage, afterEntry: entry.id });
            })
            .catch(() => {});
        })
        .catch((err) => failed(entry, err));
    },
    [
      unit,
      lead,
      leadId,
      excluded,
      drafts,
      partOf,
      launchGhost,
      batchApi,
      pageApi,
      applyEffects,
      canEditRules,
      rulesApi,
      failed,
    ],
  );

  /** File every ticked Quick win under its first suggestion: one request per category. */
  const fileQuickWins = useCallback(
    async (chosen) => {
      const parts = chosen
        .map((u) => [u, accountsById[u.suggestions[0]?.category_id]])
        .filter(([, account]) => account)
        .map(([u, account]) => partOf(u, u.ids, account));
      if (!parts.length) return;
      const byCategory = new Map();
      parts.forEach((p) => byCategory.set(p.account.id, [...(byCategory.get(p.account.id) || []), ...p.ids]));
      setQuickBusy(true);
      setError(null);
      const request = Promise.all([...byCategory].map(([categoryId, ids]) => pageApi.categorize(ids, categoryId)));
      historySeq.current += 1;
      const entry = { id: historySeq.current, parts, promise: request };
      try {
        await request;
        setHistory((h) => [...h, entry]);
        applyEffects(entry, 1);
        const filedIds = new Set(parts.flatMap((p) => p.ids));
        setUnits((prev) => withoutIds(prev, filedIds));
        const count = filedIds.size;
        setLast({ count, label: gettext('their suggestions'), accountId: null, month: null });
        setPhase('cards');
      } catch (err) {
        // Some categories may have gone through: the queue says which.
        setError(err?.message || gettext('Could not file the quick wins.'));
        load(scope, { keepSession: true });
      } finally {
        setQuickBusy(false);
      }
    },
    [accountsById, partOf, pageApi, applyEffects, load, scope],
  );

  /** Take back the latest pick: its rows go back to uncategorized, on top of the queue. */
  const undo = useCallback(async () => {
    const entry = history[history.length - 1];
    if (!entry || undoing) return;
    setUndoing(true);
    setError(null);
    try {
      await entry.promise;
      const ids = entry.parts.flatMap((p) => p.ids);
      await pageApi.uncategorize(ids);
      setHistory((h) => h.filter((e) => e.id !== entry.id));
      applyEffects(entry, -1);
      setRowsById((prev) => {
        const next = new Map(prev);
        entry.parts.forEach((p) => p.rows.forEach((row) => next.set(rowId(row), next.get(rowId(row)) ?? row)));
        return next;
      });
      // Under a key of their own: the rest of a split row's group may still be queued under the old one.
      const restored = entry.parts.map((p) => ({ ...p.unit, key: `${p.unit.key}#${entry.id}` }));
      setUnits((prev) => [...restored, ...withoutIds(prev, ids)]);
      setPhase('cards');
      setLast(null);
      setRuleOffer(null);
    } catch (err) {
      // A failed pick took itself back already; anything else is the server's refusal.
      setError(err?.message || gettext('Could not undo that.'));
    } finally {
      setUndoing(false);
    }
  }, [history, undoing, pageApi, applyEffects]);

  const skip = useCallback(() => {
    if (!unit) return;
    setExitArmed(false);
    setRuleOffer(null);
    if (!reducedMotion && topCardRef.current) {
      setGhost({
        key: Date.now(),
        from: topCardRef.current.getBoundingClientRect(),
        to: null,
        title: lead?.payee || lead?.merchant_name || lead?.description || '',
        amount: signedAmount(lead),
      });
    }
    setUnits((prev) => prev.slice(1));
    setPile((prev) => [...prev, unit]);
  }, [unit, lead, reducedMotion]);

  const onEscape = useCallback(() => {
    if (exitArmed) exit();
    else setExitArmed(true);
  }, [exitArmed, exit]);

  useEffect(() => {
    if (!exitArmed) return undefined;
    const t = setTimeout(() => setExitArmed(false), EXIT_ARM_MS);
    return () => clearTimeout(t);
  }, [exitArmed]);

  // The keyboard when focus is not in the search box (a chip or button was
  // clicked): letters go to the search, the queue's keys still work.
  const modalOpen = splitOpen || showCreateAccount || Boolean(ruleDialog);
  const hasUnit = Boolean(unit);
  useEffect(() => {
    const handler = (e) => {
      if (modalOpen || phase !== 'cards' || e.defaultPrevented) return;
      if (isEditable(e.target) || e.target.closest?.('dialog, [role="region"]')) return;
      // The end screen: Escape is the way out, nothing left to arm.
      if (!hasUnit) {
        if (e.key === 'Escape') exit();
        return;
      }
      // Enter and Space on a focused button press that button, and only that.
      if ((e.key === 'Enter' || e.key === ' ') && e.target.closest?.('button, a, label, [role="tab"]')) return;
      if (e.key.length === 1 && /\S/.test(e.key) && !/^[1-9]$/.test(e.key) && !e.ctrlKey && !e.metaKey && !e.altKey) {
        searchRef.current?.focus();
        return;
      }
      commandsRef.current?.(e);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [modalOpen, phase, hasUnit, exit]);

  // --- details, groups, splits, new categories, transfers -------------------

  const handleDetailChange = useCallback(
    (field, value) => {
      if (!lead) return;
      setDrafts((prev) => ({ ...prev, [leadId]: { ...(prev[leadId] ?? detailsOf(lead)), [field]: value } }));
    },
    [lead, leadId],
  );

  const handleDetailsRevert = useCallback(() => {
    setDrafts((prev) => {
      const next = { ...prev };
      delete next[leadId];
      return next;
    });
  }, [leadId]);

  const toggleExcluded = useCallback((key, id) => {
    setExcluded((prev) => {
      const out = new Set(prev[key] || []);
      if (out.has(id)) out.delete(id);
      else out.add(id);
      return { ...prev, [key]: out };
    });
  }, []);

  // The split editor opens on what the user typed, not on what the bank sent.
  const splitTransaction = useMemo(() => {
    if (!lead) return null;
    const draft = drafts[leadId];
    return draft ? { ...lead, payee: draft.payee, description: draft.description } : lead;
  }, [lead, leadId, drafts]);

  // A split files the lead row only: its group's other rows stay in the queue.
  const handleSplitSave = useCallback(
    async (data) => {
      if (!lead || !unit) return;
      await transactionApi.updateTransaction(leadId, {
        date: data.date,
        category: null,
        splits: data.splits,
        inflow: data.inflow,
        outflow: data.outflow,
        payee: data.payee,
        description: data.description,
        account: lead.account.id,
      });
      setSplitOpen(false);
      historySeq.current += 1;
      const entry = { id: historySeq.current, parts: [partOf(unit, [leadId], null)], promise: Promise.resolve() };
      setHistory((h) => [...h, entry]);
      applyEffects(entry, 1);
      setRowsById((prev) => new Map(prev).set(leadId, { ...lead, payee: data.payee, description: data.description }));
      setUnits((prev) => withoutIds(prev, [leadId]));
      setLast({ count: 1, label: gettext('a split'), accountId: null, month: null });
    },
    [lead, leadId, unit, transactionApi, partOf, applyEffects],
  );

  const handleCreateAccount = useCallback(
    async (name, accountGroupId) => {
      const created = await uploadApi.createAccount(name, accountGroupId);
      setLocalAccounts((prev) => [...prev, created].sort((a, b) => a.name.localeCompare(b.name)));
      setShowCreateAccount(false);
      file(created, null);
      return created;
    },
    [uploadApi, file],
  );

  // Both banks reported one transfer: Match keeps one leg (now the transfer) and voids the other.
  const handleMatch = useCallback(
    async ({ pair, self, other }) => {
      const proposal = pair.proposal || {};
      try {
        await batchApi.transferMatch(self.imported_transaction_id, other.imported_transaction_id, proposal.archive_id);
      } catch (err) {
        if (err.status === 409 && err.payload?.proposal) {
          const fresh = err.payload.proposal;
          setTransferPairs((prev) => prev.map((p) => (p === pair ? { ...p, proposal: fresh } : p)));
        }
        setError(err.message || gettext('Could not match these transactions.'));
        return;
      }
      const legIds = [self.imported_transaction_id, other.imported_transaction_id];
      const inQueue = legIds.filter((id) => units.some((u) => u.ids.includes(id)));
      setTransferPairs((prev) => prev.filter((p) => p !== pair));
      setUnits((prev) => withoutIds(prev, legIds));
      setSession((s) => ({ ...s, filed: s.filed + inQueue.length, lastAt: Date.now() }));
      setLast({ count: inQueue.length, label: gettext('a matched transfer'), accountId: null, month: null });
    },
    [batchApi, units],
  );

  const handleDismissMatch = useCallback(
    async ({ pair, self, other }) => {
      try {
        await batchApi.transferDismiss(self.imported_transaction_id, other.imported_transaction_id);
        setTransferPairs((prev) => prev.filter((p) => p !== pair));
      } catch (err) {
        setError(err.message || gettext('Could not dismiss this suggestion.'));
      }
    },
    [batchApi],
  );

  // --- rules ---------------------------------------------------------------

  const createRule = useCallback(async () => {
    if (!ruleOffer) return;
    const { draft } = ruleOffer;
    setRuleOffer(null);
    try {
      await rulesApi.create(draft);
      setSession((s) => ({ ...s, rules: s.rules + 1 }));
      setRuleNotice(gettext('Rule created. Transactions it matches now show its suggestion.'));
      load(scope, { keepSession: true });
    } catch (err) {
      setError(err.message);
    }
  }, [ruleOffer, rulesApi, load, scope]);

  const declineRule = useCallback(() => {
    if (!ruleOffer) return;
    rulesApi.declineDraft(ruleOffer.draft.signature, ruleOffer.draft.category).catch(() => {});
    setRuleOffer(null);
  }, [ruleOffer, rulesApi]);

  // --- render --------------------------------------------------------------

  const left = countOf(units);
  const progress = {
    done: session.filed,
    total: session.filed + left + countOf(pile),
    amountDone: session.amount,
    amountTotal:
      session.amount +
      units.reduce((s, u) => s + totalOf(u.ids, rowsById), 0) +
      pile.reduce((s, u) => s + totalOf(u.ids, rowsById), 0),
    minutes: minutesLeft(units.length, secondsPerUnit(session.pickTimes)),
  };
  const quickUnits = units.filter((u) => u.confident && u.suggestions[0] && accountsById[u.suggestions[0].category_id]);
  const exitLabel = onExit ? gettext('Back to the Inbox') : gettext('Back to Bank Feed');
  const overlay = Boolean(onExit);
  const shell = overlay
    ? 'fixed inset-0 z-[60] overflow-y-auto bg-base-200 flex flex-col'
    : 'min-h-screen bg-base-200 flex flex-col';

  if (phase === 'loading') {
    return (
      <div className={`${shell} items-center justify-center`} data-testid="categorize-loading">
        <div className="text-center m-auto">
          <span className="loading loading-spinner loading-lg text-primary" />
          <p className="mt-4 text-base-content/70">{gettext('Loading transactions…')}</p>
        </div>
      </div>
    );
  }

  const header = (
    <div className="bg-base-100 border-b border-base-300 px-4 sm:px-6 py-3 flex flex-wrap items-center gap-x-4 gap-y-2 sticky top-0 z-20">
      <a
        href={backHref}
        onClick={(e) => {
          if (!overlay) return;
          e.preventDefault();
          exit();
        }}
        className="btn btn-ghost btn-sm gap-1"
        data-testid="categorize-back"
      >
        ← {gettext('Back')}
      </a>
      <h1 className="text-lg sm:text-xl font-black tracking-tight">⚡ {gettext('Categorize Mode')}</h1>
      <ScopeBar scope={scope} feedAccounts={feedAccounts} onChange={changeScope} />
      <div className="flex items-center gap-2 ml-auto">
        {phase === 'cards' && quickUnits.length >= QUICK_WINS_MIN && (
          <button
            type="button"
            className="btn btn-sm btn-soft btn-success gap-1"
            onClick={() => setPhase('quickwins')}
            data-testid="categorize-quick-wins-btn"
          >
            ⚡ {interpolate(gettext('%s quick wins'), [countOf(quickUnits)])}
          </button>
        )}
        {canEditRules && lead && (
          <button
            type="button"
            className="btn btn-outline btn-sm gap-1 hidden sm:inline-flex"
            title={gettext('New rule, starting from this transaction')}
            onClick={() => setRuleDialog({ draft: draftFromRow(lead) })}
            data-testid="categorize-new-rule"
          >
            <Icon name="wand-magic-sparkles" className="h-4 w-4" />
            {gettext('New rule')}
          </button>
        )}
      </div>
      {progress.total > 0 && (
        <div className="basis-full">
          <Progress {...progress} />
        </div>
      )}
      {exitArmed && (
        <div className="basis-full flex items-center gap-2 text-sm" role="status" data-testid="categorize-exit-hint">
          <Icon name="exclamation-triangle" className="h-4 w-4 text-warning shrink-0" />
          {gettext('Press Esc again to leave. Everything you filed is saved.')}
        </div>
      )}
    </div>
  );

  const dialogs = (
    <>
      <RuleBuilderDialog
        request={ruleDialog}
        bookBase={book.base}
        categories={allAccounts}
        canEdit={canEditRules}
        onClose={() => setRuleDialog(null)}
        onSaved={(saved, info = {}) => {
          setRuleDialog(null);
          setRuleOffer(null);
          if (!info.deleted) setSession((s) => ({ ...s, rules: s.rules + 1 }));
          setRuleNotice(
            info.deleted
              ? gettext('Rule deleted')
              : gettext('Rule saved. Transactions it matches now show its suggestion first.'),
          );
          // The rule's suggestions (or postings) change what is left.
          load(scope, { keepSession: true });
        }}
      />
      <Toast
        open={!!ruleNotice}
        message={ruleNotice}
        severity="success"
        onClose={clearRuleNotice}
        testId="categorize-rule-toast"
      />
      {showCreateAccount && (
        <CreateAccountModal
          allAccountGroups={allAccountGroups}
          onSave={handleCreateAccount}
          onCancel={() => setShowCreateAccount(false)}
        />
      )}
      {/* The feed's own editor, opened straight into split mode. */}
      <TransactionModal
        open={splitOpen}
        onClose={() => setSplitOpen(false)}
        transaction={splitTransaction}
        source={feedTransaction}
        allAccounts={localAccounts}
        allPayees={allPayees}
        book={book}
        onSave={handleSplitSave}
        onAccountCreated={(account) =>
          setLocalAccounts((prev) =>
            prev.some((a) => a.id === account.id)
              ? prev
              : [...prev, account].sort((a, b) => a.name.localeCompare(b.name)),
          )
        }
        startSplit
      />
      {ghost && <Ghost key={ghost.key} ghost={ghost} onDone={() => setGhost(null)} />}
    </>
  );

  const errorAlert = error && (
    <div className="alert alert-error w-full py-2" data-testid="categorize-error">
      <span className="text-sm">{error}</span>
      <button
        type="button"
        className="btn btn-ghost btn-xs"
        onClick={() => setError(null)}
        aria-label={gettext('Dismiss')}
      >
        ✕
      </button>
    </div>
  );

  if (phase === 'quickwins') {
    return (
      <div className={shell} data-testid="categorize-mode">
        {header}
        <div className="flex-1 p-4 sm:p-6 space-y-3">
          {errorAlert}
          <QuickWins
            units={quickUnits}
            rowsById={rowsById}
            accountsById={accountsById}
            busy={quickBusy}
            onFile={fileQuickWins}
            onSkip={() => setPhase('cards')}
          />
        </div>
        {dialogs}
      </div>
    );
  }

  if (!unit) {
    return (
      <div className={shell} data-testid="categorize-mode">
        {header}
        <div className="px-4 pt-4">{errorAlert}</div>
        {last && (
          <div className="px-4 pt-4 max-w-md w-full mx-auto">
            <AfterPick last={last} impact={null} undoing={undoing} onUndo={undo} />
          </div>
        )}
        <Summary
          session={session}
          pileCount={pile.length}
          scoped={isScoped(scope)}
          onReviewPile={() => {
            setUnits(pile);
            setPile([]);
          }}
          onExit={exit}
          exitLabel={exitLabel}
        />
        {dialogs}
      </div>
    );
  }

  const topSuggestion = suggestions[0] ? accountsById[suggestions[0].category_id] : null;
  const impact =
    last?.accountId && accountsById[last.accountId]
      ? { account: accountsById[last.accountId], month: last.month, figure: figures[last.month]?.[last.accountId] }
      : null;

  return (
    <div className={shell} data-testid="categorize-mode">
      {header}
      <div className="flex-1 flex flex-col lg:flex-row gap-6 p-4 sm:p-6 max-w-7xl mx-auto w-full">
        <div className="lg:w-2/5 flex flex-col items-center gap-3">
          {errorAlert}
          <div className="w-full max-w-md">
            <QueueCards
              units={units}
              topCardRef={topCardRef}
              reducedMotion={reducedMotion}
              topSuggestionName={topSuggestion?.name ?? null}
              onSwipeRight={() => topSuggestion && file(topSuggestion, null)}
              onSwipeLeft={skip}
              onSwipeUp={() => setEditing(true)}
              swipeDisabled={editing}
              unit={unit}
              rowsById={rowsById}
              excluded={excluded}
              onToggleExcluded={toggleExcluded}
              details={details}
              detailsDirty={detailsDirty}
              editing={editing}
              setEditing={setEditing}
              payeeOptions={payeeOptions}
              onDetailChange={handleDetailChange}
              onDetailsRevert={handleDetailsRevert}
              transferMatch={transferByRow[leadId] ?? null}
              onMatch={handleMatch}
              onDismissMatch={handleDismissMatch}
            />
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={skip}
              className="btn btn-ghost btn-sm gap-1 text-base-content/70 hover:text-base-content"
              data-testid="categorize-skip"
            >
              {gettext('Skip for now')}
              <kbd className="kbd kbd-xs hidden sm:inline-flex">→</kbd>
            </button>
          </div>
          <p className="text-sm text-base-content/70" data-testid="categorize-remaining">
            {interpolate(gettext('%s remaining'), [left])}
            {pile.length > 0 ? ` · ${interpolate(gettext('%s skipped'), [countOf(pile)])}` : ''}
          </p>
          <div className="w-full max-w-md">
            <AfterPick
              last={last}
              impact={impact}
              ruleOffer={ruleOffer}
              undoing={undoing}
              onUndo={undo}
              onCreateRule={createRule}
              onCustomizeRule={() => {
                setRuleDialog({ draft: ruleOffer.draft });
                setRuleOffer(null);
              }}
              onDeclineRule={declineRule}
            />
          </div>
        </div>

        <div className="lg:w-3/5 bg-base-100 rounded-2xl border border-base-300 shadow-lg p-4 sm:p-5 flex flex-col min-h-[400px] lg:min-h-0 lg:max-h-[calc(100vh-160px)] lg:sticky lg:top-28">
          <CategoryPicker
            accounts={localAccounts}
            usage={usage}
            row={lead}
            suggestions={suggestions}
            loading={false}
            figures={figures[monthOf(lead)]}
            searchRef={searchRef}
            commandsRef={commandsRef}
            autoFocus={finePointer}
            onSelect={file}
            onSplit={() => setSplitOpen(true)}
            onCreateNew={() => setShowCreateAccount(true)}
            onSkip={skip}
            onUndo={undo}
            onEscape={onEscape}
          />
        </div>
      </div>
      {dialogs}
    </div>
  );
}
