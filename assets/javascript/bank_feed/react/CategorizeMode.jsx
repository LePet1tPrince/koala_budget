import React, { useState, useEffect, useLayoutEffect, useCallback, useMemo, useRef } from 'react';
import { getApiHeaders } from '../../api';
import { createConfetti } from '../../common/confetti';
import { getBatchOperationsApi, getUploadApiHelpers } from '../bank_feed';
import CreateAccountModal from './CSVUploadWizard/CreateAccountModal';
import Combobox from '../../common/Combobox';
import Modal from '../../common/Modal';

const ACCOUNT_TYPE_ORDER = ['expense', 'income', 'asset', 'liability', 'goal'];

// How many cards ahead of the current one to look up similar-transaction
// suggestions for.
const SUGGESTION_PREFETCH = 8;

// A feed row's id is its BankTransaction id, which is what the suggestion
// endpoint keys on.
function transactionId(tx) {
  return tx?.imported_transaction_id ?? tx?.id ?? null;
}

// The feed row maps `merchant_name` onto `payee`, and either can be null — this
// is the pair the card lets you edit.
function detailsOf(tx) {
  return { payee: tx?.payee ?? tx?.merchant_name ?? '', description: tx?.description ?? '' };
}

// What a draft actually changes, shaped as a `batch_edit` payload. A field that
// matches what the bank sent is left out, since the endpoint updates only the
// fields it is given. `null` when nothing changed, so a plain categorization
// never takes the edit path.
function changedDetails(tx, draft) {
  if (!tx || !draft) return null;
  const original = detailsOf(tx);
  const changes = {};
  if (draft.payee.trim() !== original.payee.trim()) changes.payee = draft.payee.trim();
  if (draft.description.trim() !== original.description.trim()) changes.description = draft.description.trim();
  return Object.keys(changes).length > 0 ? changes : null;
}

// A rough "same merchant" key, used only to decide which cached suggestions a
// fresh categorization invalidates. The real matching happens on the server.
function lookalikeKey(tx) {
  return (tx?.payee || tx?.merchant_name || tx?.description || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}

const TOP_LEVEL_FILTERS = [
  { key: 'income_expense', label: 'Income / Expense', icon: '💸', types: ['income', 'expense'] },
  { key: 'transfer', label: 'Transfer', icon: '🔄', types: ['asset', 'liability'] },
  { key: 'goal', label: 'Goals', icon: '🎯', types: ['goal'] },
];

function formatCurrency(amount) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(amount);
}

function Confetti({ active }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    if (!active || !canvasRef.current) return;
    return createConfetti(canvasRef.current, { origin: 'sky' });
  }, [active]);

  if (!active) return null;
  return (
    <canvas
      ref={canvasRef}
      className="fixed inset-0 pointer-events-none"
      style={{ zIndex: 9999 }}
    />
  );
}

function SimilarTransactionsTooltip({ transaction, allTransactions }) {
  const [open, setOpen] = useState(false);
  const similar = useMemo(() => {
    if (!transaction.merchant_name && !transaction.description) return [];
    const needle = (transaction.merchant_name || transaction.description || '').toLowerCase();
    return allTransactions
      .filter(t => t.id !== transaction.id && (
        (t.merchant_name || t.description || '').toLowerCase().includes(needle) ||
        needle.includes((t.merchant_name || t.description || '').toLowerCase())
      ))
      .slice(0, 5);
  }, [transaction, allTransactions]);

  if (similar.length === 0) return null;

  return (
    <div className="relative">
      <button
        onClick={(e) => { e.stopPropagation(); setOpen(!open); }}
        className="btn btn-ghost btn-xs btn-circle text-base-content/70 hover:text-primary"
        title="Similar transactions"
      >
        🔍
      </button>
      {open && (
        <div className="absolute right-0 top-8 z-50 bg-base-100 border border-base-300 rounded-xl shadow-2xl p-3 w-72 animate-in">
          <p className="text-xs font-semibold text-base-content/70 mb-2">Similar transactions</p>
          {similar.map(t => (
            <div key={t.id} className="flex justify-between items-center py-1.5 border-b border-base-200 last:border-0 text-xs">
              <div>
                <div className="font-medium">{t.merchant_name || t.description}</div>
                <div className="text-base-content/70">{t.posted_date}</div>
              </div>
              <div className={t.outflow > 0 ? 'text-error font-semibold' : 'text-success font-semibold'}>
                {t.outflow > 0 ? `-${formatCurrency(t.outflow)}` : `+${formatCurrency(t.inflow)}`}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * The payee and description of the card on top of the stack, editable in place.
 *
 * Nothing is written while you type: the draft is held by the parent, keyed by
 * transaction id, and saved in the same request that files the transaction —
 * so a card is never left renamed but uncategorized, and a draft survives a
 * skip, since the card comes back around.
 */
function TransactionDetailsEditor({ values, dirty, payeeOptions, onChange, onRevert }) {
  const handleKeyDown = (e) => {
    if (e.key === 'Escape') {
      // Escape backs out of the edit, never out of categorize mode. The window
      // handler that navigates back to the feed is stopped here whatever the
      // field holds, because being thrown out of the queue mid-word costs far
      // more than having to press Escape a second time. (The payee combobox
      // stops it first when its list is open, closing just the list.)
      e.stopPropagation();
      if (dirty) onRevert();
      else e.target.blur();
      return;
    }
    if (e.key === 'Enter' && e.target.tagName === 'INPUT') {
      // There's no form to submit — Enter just finishes the field. Buttons in
      // here (Revert) are left alone, or preventDefault would swallow the
      // keyboard press that activates them.
      e.preventDefault();
      e.target.blur();
    }
  };

  return (
    <div className="space-y-2" onKeyDown={handleKeyDown} data-testid="categorize-details-editor">
      <Combobox
        label="Payee"
        value={values.payee}
        onChange={v => onChange('payee', v)}
        options={payeeOptions}
        freeText
        placeholder="Who was this with?"
        testId="categorize-payee"
      />
      <label className="form-control w-full">
        <span className="label-text mb-1 block text-sm text-base-content/70">Description</span>
        <input
          type="text"
          className="input input-bordered w-full"
          value={values.description}
          placeholder="What was it for?"
          onChange={e => onChange('description', e.target.value)}
          data-testid="categorize-description"
        />
      </label>
      <div className="flex items-center justify-between gap-2 min-h-6">
        {dirty && (
          <>
            <span className="text-xs text-warning font-medium" data-testid="categorize-details-dirty">
              Saved when you pick a category
            </span>
            <button onClick={onRevert} className="btn btn-ghost btn-xs" data-testid="categorize-details-revert">
              Revert
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function TransactionCard({
  transaction,
  index,
  total,
  allTransactions,
  isExiting,
  isSkipping,
  details,
  detailsDirty,
  payeeOptions,
  onDetailChange,
  onDetailsRevert,
  cardRef,
}) {
  const isTop = index === 0;
  const offset = Math.min(index, 4);
  const scale = 1 - offset * 0.03;
  const translateY = offset * 8;
  const opacity = index > 4 ? 0 : 1 - offset * 0.15;
  const isOutflow = parseFloat(transaction.outflow) > 0;

  return (
    <div
      className={`absolute w-full transition-all duration-500 ease-out ${isExiting && isTop ? 'card-exit' : ''} ${isSkipping && isTop ? 'card-skip' : ''}`}
      style={{
        transform: `translateY(${translateY}px) scale(${scale})`,
        opacity,
        zIndex: total - index,
      }}
    >
      <div
        ref={isTop ? cardRef : null}
        className={`card bg-base-100 shadow-xl border border-base-300 ${isTop ? 'ring-2 ring-primary/30' : ''}`}
      >
        <div className="card-body p-5">
          {/* The lookalike button shares a row with the account name rather than
              floating over the corner, or it would sit on top of the payee
              field below it. */}
          <div className="flex items-start justify-between gap-2">
            <p className="text-xs text-base-content/70 truncate">
              {transaction.account?.name || 'Unknown Account'}
            </p>
            {isTop && (
              <div className="-mt-1.5 -mr-1.5 shrink-0">
                <SimilarTransactionsTooltip transaction={transaction} allTransactions={allTransactions} />
              </div>
            )}
          </div>
          <div className="mt-1">
            {isTop ? (
              <TransactionDetailsEditor
                values={details}
                dirty={detailsDirty}
                payeeOptions={payeeOptions}
                onChange={onDetailChange}
                onRevert={onDetailsRevert}
              />
            ) : (
              <>
                <h3 className="font-bold text-lg truncate">
                  {transaction.merchant_name || transaction.description || 'No description'}
                </h3>
                {transaction.merchant_name && transaction.description && (
                  <p className="text-sm text-base-content/70 truncate">{transaction.description}</p>
                )}
              </>
            )}
          </div>
          <div className="flex items-center justify-between mt-3">
            <span className="text-sm text-base-content/70">{transaction.posted_date}</span>
            <span className={`text-2xl font-black ${isOutflow ? 'text-error' : 'text-success'}`}>
              {isOutflow ? `-${formatCurrency(transaction.outflow)}` : `+${formatCurrency(transaction.inflow)}`}
            </span>
          </div>
          {isTop && (
            <div className="mt-2 text-xs text-base-content/40 text-center">
              Select a category on the right →
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

const ACCOUNT_TYPE_LABELS = {
  expense: 'Expense',
  income: 'Income',
  asset: 'Asset',
  liability: 'Liability',
  goal: 'Goal',
};

function charSequenceMatch(text, query) {
  // Letters of the query appear in order in text, not necessarily adjacent.
  let ti = 0;
  for (let qi = 0; qi < query.length; qi++) {
    if (query[qi] === ' ') continue;
    while (ti < text.length && text[ti] !== query[qi]) ti++;
    if (ti >= text.length) return false;
    ti++;
  }
  return true;
}

/**
 * Rank how well an account matches a search query, higher is better.
 * `null` means no match at all (the account is excluded from results).
 * Matches on the account's own name are weighted far above matches on its
 * group/institution/type — otherwise, e.g., every income account's
 * `account_type` literally contains "income", so searching "income" (or
 * any string containing it) would rank an unrelated income account the
 * same as an account actually named "Income".
 */
function matchScore(account, query) {
  const q = query.toLowerCase().trim();
  if (!q) return 0;

  const name = (account.name || '').toLowerCase();
  const secondary = [account.account_group_name, account.institution_name, ACCOUNT_TYPE_LABELS[account.account_type]]
    .filter(Boolean).join(' ').toLowerCase();
  const qWords = q.split(/\s+/).filter(Boolean);

  if (name === q) return 100;
  if (name.startsWith(q)) return 90;
  if (name.split(/\s+/).includes(q)) return 85;
  if (name.includes(q)) return 70;
  if (qWords.length > 1 && qWords.every(w => name.includes(w))) return 60;
  if (secondary.includes(q)) return 40;
  if (qWords.length > 1 && qWords.every(w => secondary.includes(w))) return 30;
  if (charSequenceMatch(name, q)) return 10;
  return null;
}

function escapeRegExp(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// Whether `needle` appears in `haystack` as a whole token — not as part of a
// longer word — so an account named "BC" doesn't match inside "ABC" and a
// memo of "ATM WD" doesn't match an account named "AT".
function containsWholeToken(haystack, needle) {
  if (!needle) return false;
  const re = new RegExp(`(?:^|[^a-z0-9])${escapeRegExp(needle.toLowerCase())}(?:$|[^a-z0-9])`, 'i');
  return re.test(` ${haystack} `);
}

/**
 * Find the account whose name is most clearly named in a transaction's
 * memo/payee text — e.g. a transfer memo that literally says "WS Joint
 * Checking" or just "BBC" should suggest that account. `excludeAccountId`
 * keeps the transaction's own (feed) account from ever being suggested,
 * since categorizing a transaction to the account it's already in would
 * make it a transfer to itself.
 */
function findAccountNamedInText(text, accounts, excludeAccountId) {
  if (!text) return null;
  const candidates = accounts.filter(a => a.name && a.id !== excludeAccountId);

  // Prefer the longest full account name that appears verbatim in the text.
  let fullMatch = null;
  for (const account of candidates) {
    const name = account.name.trim();
    if (containsWholeToken(text, name) && (!fullMatch || name.length > fullMatch.name.trim().length)) {
      fullMatch = account;
    }
  }
  if (fullMatch) return fullMatch;

  // Otherwise, the longest single word (3+ chars, to skip noise like "of")
  // from any account name that appears as a whole word in the text.
  let wordMatch = null;
  let wordMatchLength = 0;
  for (const account of candidates) {
    for (const word of account.name.split(/\s+/)) {
      if (word.length < 3) continue;
      if (word.length > wordMatchLength && containsWholeToken(text, word)) {
        wordMatch = account;
        wordMatchLength = word.length;
      }
    }
  }
  return wordMatch;
}

// The note under a suggestion, explaining why it's suggested. A "named" match
// (an account named verbatim in the memo/payee) needs no history to justify
// itself, but still says so when history backs it up too.
function suggestionNote({ count, match_type }) {
  if (match_type === 'named') {
    return count != null
      ? `Named in the memo — also used ${count}× for this payee`
      : 'Named in the transaction memo';
  }
  const n = `${count} transaction${count === 1 ? '' : 's'}`;
  const verb = count === 1 ? 'was' : 'were';
  if (match_type === 'payee') return `${n} with this payee ${verb} categorized as this`;
  if (match_type === 'description') return `${n} with this description ${verb} categorized as this`;
  return `${n} like this one ${verb} categorized as this`;
}

function SuggestedCategories({ suggestions, accountsById, loading, activeKey, onSelect }) {
  if (loading) {
    return (
      <div className="mb-3 flex items-center gap-2 text-xs text-base-content/70">
        <span className="loading loading-spinner loading-xs" />
        Looking for similar transactions...
      </div>
    );
  }
  if (suggestions.length === 0) return null;

  return (
    <div className="mb-3" data-testid="category-suggestions">
      <p className="text-xs font-semibold text-success mb-1.5">
        ✨ Suggested from similar transactions
      </p>
      <div className="space-y-1">
        {suggestions.map(s => (
          <button
            key={s.category_id}
            onClick={() => onSelect(accountsById[s.category_id])}
            data-nav-key={`s:${s.category_id}`}
            data-active={activeKey === `s:${s.category_id}` ? 'true' : undefined}
            className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg border border-success bg-success/10 hover:bg-success/20 transition-all hover:shadow-md active:scale-[0.98] ${
              activeKey === `s:${s.category_id}` ? 'ring-2 ring-primary ring-offset-2 ring-offset-base-100 bg-success/20' : ''
            }`}
            data-testid="category-suggestion"
          >
            <div className="flex-1 text-left min-w-0">
              <div className="font-bold truncate">{s.category_name}</div>
              <div className="text-xs text-base-content/70 truncate">{suggestionNote(s)}</div>
            </div>
            {s.count != null && (
              <span className="badge badge-success badge-sm shrink-0">{s.count}×</span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}

function AccountHierarchy({
  allAccounts,
  allAccountGroups,
  suggestions,
  suggestionsLoading,
  currentTransaction,
  onSelect,
  onCreateNew,
}) {
  const [searchQuery, setSearchQuery] = useState('');
  const [activeTopFilter, setActiveTopFilter] = useState(null); // TOP_LEVEL_FILTERS key
  const [filterGroupId, setFilterGroupId] = useState(null);
  const [filterInstitution, setFilterInstitution] = useState(null);
  const [activeIndex, setActiveIndex] = useState(-1); // keyboard highlight; -1 = nothing
  const searchRef = useRef(null);
  const panelRef = useRef(null);

  const activeTopGroup = useMemo(
    () => TOP_LEVEL_FILTERS.find(f => f.key === activeTopFilter) || null,
    [activeTopFilter]
  );
  const activeTypes = activeTopGroup?.types || null;

  const accountsById = useMemo(() => {
    const byId = {};
    allAccounts.forEach(a => { byId[a.id] = a; });
    return byId;
  }, [allAccounts]);

  // Two independent signals can each suggest a category: the server's
  // history-based matches (payee/description/similar-wording), and an
  // account named verbatim in this transaction's own memo/payee — often the
  // strongest signal there is, since a transfer memo may literally name the
  // other side. Merged into one ranked, deduped list (the same account is
  // never shown twice), and the transaction's own feed account is never
  // suggested, or categorizing it would make it a transfer to itself.
  const usableSuggestions = useMemo(() => {
    const feedAccountId = currentTransaction?.account?.id ?? null;
    const fromHistory = (suggestions || []).filter(
      s => accountsById[s.category_id] && s.category_id !== feedAccountId
    );

    if (!currentTransaction) return fromHistory;

    const memoText = [currentTransaction.description, currentTransaction.merchant_name]
      .filter(Boolean).join(' ');
    const namedAccount = findAccountNamedInText(memoText, allAccounts, feedAccountId);
    if (!namedAccount) return fromHistory;

    const already = fromHistory.find(s => s.category_id === namedAccount.id);
    const named = {
      category_id: namedAccount.id,
      category_name: namedAccount.name,
      count: already ? already.count : null,
      match_type: 'named',
      payee: already ? already.payee : '',
    };
    return [named, ...fromHistory.filter(s => s.category_id !== namedAccount.id)];
  }, [suggestions, accountsById, currentTransaction, allAccounts]);

  const suggestedAccountIds = useMemo(
    () => new Set(usableSuggestions.map(s => s.category_id)),
    [usableSuggestions]
  );

  // Second-level filters: only shown when a top-level filter is active
  const relevantGroups = useMemo(() => {
    if (!activeTypes) return [];
    return allAccountGroups
      .filter(g => activeTypes.includes(g.account_type))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [allAccountGroups, activeTypes]);

  const relevantInstitutions = useMemo(() => {
    if (!activeTypes) return [];
    const names = new Set(
      allAccounts
        .filter(a => activeTypes.includes(a.account_type) && a.institution_name)
        .map(a => a.institution_name)
    );
    return [...names].sort();
  }, [allAccounts, activeTypes]);

  const trimmedSearch = searchQuery.trim();

  const filteredAccounts = useMemo(() => {
    const results = [];
    for (const a of allAccounts) {
      if (activeTypes && !activeTypes.includes(a.account_type)) continue;
      if (filterGroupId && a.account_group !== filterGroupId) continue;
      if (filterInstitution && a.institution_name !== filterInstitution) continue;
      if (trimmedSearch) {
        const score = matchScore(a, trimmedSearch);
        if (score === null) continue;
        results.push({ account: a, score });
      } else {
        results.push({ account: a, score: 0 });
      }
    }
    return results;
  }, [allAccounts, activeTypes, filterGroupId, filterInstitution, trimmedSearch]);

  const groupedAccounts = useMemo(() => {
    // While searching, relevance beats grouping — an exact-name match must
    // land at the very top of the list rather than wherever its account
    // group happens to sort alphabetically.
    if (trimmedSearch) {
      const sorted = [...filteredAccounts]
        .sort((a, b) => b.score - a.score || a.account.name.localeCompare(b.account.name))
        .map(r => r.account);
      return sorted.length ? [{ name: 'Search results', accounts: sorted }] : [];
    }

    const groups = {};
    filteredAccounts.forEach(({ account: a }) => {
      const key = a.account_group_name || 'Other';
      if (!groups[key]) groups[key] = [];
      groups[key].push(a);
    });
    return Object.entries(groups)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([name, accounts]) => ({ name, accounts: accounts.sort((a, b) => a.name.localeCompare(b.name)) }));
  }, [filteredAccounts]);

  // Accounts already offered in the Suggested section above are dropped
  // here so nothing appears twice; a group left with nothing to show is
  // dropped too, rather than rendering an empty header.
  const visibleGroupedAccounts = useMemo(() => {
    return groupedAccounts
      .map(group => ({ ...group, accounts: group.accounts.filter(a => !suggestedAccountIds.has(a.id)) }))
      .filter(group => group.accounts.length > 0);
  }, [groupedAccounts, suggestedAccountIds]);

  // Everything the arrow keys walk, in the order it is drawn: the suggestions
  // first, then the account list. Suggested accounts are excluded from the
  // list below, so every row has exactly one key.
  const navRows = useMemo(() => {
    const rows = usableSuggestions.map(s => ({ key: `s:${s.category_id}`, account: accountsById[s.category_id] }));
    visibleGroupedAccounts.forEach(group => {
      group.accounts.forEach(account => rows.push({ key: `a:${account.id}`, account }));
    });
    return rows;
  }, [usableSuggestions, accountsById, visibleGroupedAccounts]);

  // Typing narrows the list under a highlight that was pointing at a row which
  // may no longer exist, so the index is clamped where it is read rather than
  // chased with an effect.
  const activeIdx = navRows.length === 0 ? -1 : Math.min(activeIndex, navRows.length - 1);
  const activeKey = activeIdx >= 0 ? navRows[activeIdx].key : null;

  const clearFilters = () => {
    setActiveTopFilter(null);
    setFilterGroupId(null);
    setFilterInstitution(null);
    setSearchQuery('');
    setActiveIndex(-1);
  };

  const handleSearchKeyDown = (e) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (navRows.length === 0) return;
      const step = e.key === 'ArrowDown' ? 1 : -1;
      setActiveIndex(
        activeIdx < 0
          ? (step === 1 ? 0 : navRows.length - 1)
          : (activeIdx + step + navRows.length) % navRows.length
      );
      return;
    }
    if (e.key === 'Enter') {
      e.preventDefault();
      if (activeIdx >= 0) onSelect(navRows[activeIdx].account);
      return;
    }
    if (e.key === 'Escape' && searchQuery) {
      // Escape backs out of the search rather than out of categorize mode — the
      // window handler that exits is stopped here, and only while there is a
      // search to clear.
      e.preventDefault();
      e.stopPropagation();
      setSearchQuery('');
      setActiveIndex(-1);
    }
  };

  // Keep the highlighted row on screen as it walks past the fold.
  useEffect(() => {
    if (!activeKey) return;
    panelRef.current
      ?.querySelector(`[data-nav-key="${activeKey}"]`)
      ?.scrollIntoView({ block: 'nearest' });
  }, [activeKey]);

  // A filter change rebuilds the list under the highlight, so it starts over.
  useEffect(() => {
    setActiveIndex(-1);
  }, [activeTopFilter, filterGroupId, filterInstitution]);

  useEffect(() => { searchRef.current?.focus(); }, []);

  useEffect(() => {
    setActiveTopFilter(null);
    setFilterGroupId(null);
    setFilterInstitution(null);
    setSearchQuery('');
    setActiveIndex(-1);
    searchRef.current?.focus();
  }, [currentTransaction?.id]);

  return (
    <div className="flex flex-col h-full min-h-0" ref={panelRef}>
      {/* Search bar */}
      <div className="relative mb-1">
        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-base-content/40">🔍</span>
        <input
          ref={searchRef}
          type="text"
          value={searchQuery}
          onChange={e => {
            // Typing points the highlight at the best match, so Enter takes it
            // without a trip through the arrow keys; an empty box highlights
            // nothing, so a stray Enter categorizes nothing.
            setSearchQuery(e.target.value);
            setActiveIndex(e.target.value ? 0 : -1);
          }}
          onKeyDown={handleSearchKeyDown}
          placeholder="Search accounts..."
          className="input input-bordered input-sm w-full pl-9 pr-8"
        />
        {searchQuery && (
          <button
            onClick={() => { setSearchQuery(''); setActiveIndex(-1); searchRef.current?.focus(); }}
            className="absolute right-2 top-1/2 -translate-y-1/2 btn btn-ghost btn-xs btn-circle"
          >
            ✕
          </button>
        )}
      </div>
      <div className="h-5 mb-2 text-xs text-base-content/70 flex items-center gap-1.5">
        {searchQuery && (
          <>
            <kbd className="kbd kbd-xs">↑</kbd>
            <kbd className="kbd kbd-xs">↓</kbd>
            <span>to move</span>
            <kbd className="kbd kbd-xs">↵</kbd>
            <span>to choose</span>
            <kbd className="kbd kbd-xs">esc</kbd>
            <span>to clear</span>
          </>
        )}
      </div>

      {/* Filter tiles — progressive disclosure */}
      <div className="flex flex-wrap gap-1.5 mb-3">
        {/* Top level: Transfer / Income-Expense / Goals */}
        {TOP_LEVEL_FILTERS.map(f => (
          <button
            key={f.key}
            onClick={() => {
              if (activeTopFilter === f.key) {
                setActiveTopFilter(null);
              } else {
                setActiveTopFilter(f.key);
              }
              setFilterGroupId(null);
              setFilterInstitution(null);
            }}
            className={`badge badge-lg cursor-pointer transition-all hover:shadow gap-1 ${
              activeTopFilter === f.key ? 'badge-primary' : 'badge-outline'
            }`}
          >
            {f.icon} {f.label}
          </button>
        ))}

        {/* Second level: account groups + institutions (only when a top filter is active) */}
        {activeTopGroup && relevantGroups.length > 0 && (
          <>
            <span className="w-px h-6 bg-base-300 self-center mx-0.5" />
            {relevantGroups.map(g => (
              <button
                key={g.id}
                onClick={() => setFilterGroupId(filterGroupId === g.id ? null : g.id)}
                className={`badge badge-lg cursor-pointer transition-all hover:shadow ${
                  filterGroupId === g.id ? 'badge-secondary' : 'badge-outline'
                }`}
              >
                {g.name}
              </button>
            ))}
          </>
        )}
        {activeTopGroup && relevantInstitutions.length > 0 && (
          <>
            <span className="w-px h-6 bg-base-300 self-center mx-0.5" />
            {relevantInstitutions.map(inst => (
              <button
                key={inst}
                onClick={() => setFilterInstitution(filterInstitution === inst ? null : inst)}
                className={`badge badge-lg cursor-pointer transition-all hover:shadow ${
                  filterInstitution === inst ? 'badge-accent' : 'badge-outline'
                }`}
              >
                🏦 {inst}
              </button>
            ))}
          </>
        )}
        {(activeTopFilter || filterGroupId || filterInstitution) && (
          <button onClick={clearFilters} className="badge badge-lg badge-ghost cursor-pointer">
            ✕ Clear
          </button>
        )}
      </div>

      {/* Categories suggested from history + memo/payee name matches — always at top */}
      <SuggestedCategories
        suggestions={usableSuggestions}
        accountsById={accountsById}
        loading={suggestionsLoading && usableSuggestions.length === 0}
        activeKey={activeKey}
        onSelect={onSelect}
      />

      {/* Account list grouped by account group */}
      <div className="flex-1 min-h-0 overflow-y-auto pr-1 pb-1 custom-scrollbar space-y-3">
        {visibleGroupedAccounts.length === 0 && usableSuggestions.length === 0 && (
          <div className="text-center py-8 text-base-content/40">
            <p className="text-lg mb-1">No matching accounts</p>
            <p className="text-sm">Try a different search or clear filters</p>
          </div>
        )}
        {visibleGroupedAccounts.map(group => (
          <div key={group.name}>
            <div className="text-xs font-semibold text-base-content/70 uppercase tracking-wider px-1 mb-1.5 sticky top-0 bg-base-100 py-1 z-10">
              {group.name}
            </div>
            <div className="space-y-1">
              {group.accounts.map(account => (
                <button
                  key={account.id}
                  onClick={() => onSelect(account)}
                  data-nav-key={`a:${account.id}`}
                  data-active={activeKey === `a:${account.id}` ? 'true' : undefined}
                  className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg border border-base-300 transition-all hover:border-primary hover:bg-primary/5 hover:shadow-md active:scale-[0.98] ${
                    activeKey === `a:${account.id}` ? 'ring-2 ring-primary ring-offset-2 ring-offset-base-100 border-primary bg-primary/10' : ''
                  }`}
                >
                  <div className="flex-1 text-left min-w-0">
                    <div className="font-medium truncate">{account.name}</div>
                    <div className="text-xs text-base-content/40 flex gap-2">
                      <span>{ACCOUNT_TYPE_LABELS[account.account_type] || account.account_type}</span>
                      {account.institution_name && (
                        <>
                          <span>·</span>
                          <span>{account.institution_name}</span>
                        </>
                      )}
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </div>
        ))}

        {/* Create a new account when nothing above is a good match */}
        <button
          onClick={onCreateNew}
          className="w-full flex items-center justify-center gap-2 px-3 py-2.5 mt-1 rounded-lg border border-dashed border-base-300 text-base-content/70 transition-all hover:border-primary hover:bg-primary/5 hover:text-primary"
        >
          <span className="text-lg leading-none">+</span>
          <span className="font-medium">Create new account</span>
        </button>
      </div>
    </div>
  );
}

function ProgressBar({ done, total }) {
  const pct = total > 0 ? (done / total) * 100 : 0;
  return (
    <div className="w-full">
      <div className="flex justify-between text-sm mb-1">
        <span className="font-semibold text-primary">{done} categorized</span>
        <span className="text-base-content/70">{total - done} remaining</span>
      </div>
      <div className="w-full bg-base-300 rounded-full h-3 overflow-hidden">
        <div
          className="bg-gradient-to-r from-primary to-secondary h-full rounded-full transition-all duration-700 ease-out"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function StreakCounter({ streak }) {
  if (streak < 2) return null;
  const flames = streak >= 10 ? '🔥🔥🔥' : streak >= 5 ? '🔥🔥' : '🔥';
  return (
    <div className="flex items-center gap-2 text-sm font-bold text-warning animate-bounce-subtle">
      {flames} {streak} streak!
    </div>
  );
}

// Same feed (home) account and the same description — the two signals that
// most reliably mean "this is the same recurring charge/deposit" without
// being so loose it pulls in unrelated transactions.
function findSimilarTransactions(transactions, reference) {
  const accountId = reference.account?.id;
  const description = (reference.description || '').trim().toLowerCase();
  if (!accountId || !description) return [];
  return transactions.filter(t =>
    t.id !== reference.id &&
    t.account?.id === accountId &&
    (t.description || '').trim().toLowerCase() === description
  );
}

function SimilarTransactionRow({ transaction, checked, onToggle, locked }) {
  const isOutflow = parseFloat(transaction.outflow) > 0;
  return (
    <label
      className={`flex items-center gap-3 px-3 py-2 rounded-lg border transition-colors ${
        locked ? 'border-success bg-success/5' : 'border-base-300 hover:bg-base-200 cursor-pointer'
      }`}
    >
      <input
        type="checkbox"
        className="checkbox checkbox-sm checkbox-success"
        checked={checked}
        disabled={locked}
        onChange={onToggle}
      />
      <div className="flex-1 min-w-0">
        <div className="font-medium truncate">{transaction.merchant_name || transaction.description}</div>
        <div className="text-xs text-base-content/70">{transaction.posted_date}</div>
      </div>
      <div className={`text-sm font-semibold shrink-0 ${isOutflow ? 'text-error' : 'text-success'}`}>
        {isOutflow ? `-${formatCurrency(transaction.outflow)}` : `+${formatCurrency(transaction.inflow)}`}
      </div>
    </label>
  );
}

function SimilarTransactionsModal({ pendingBatch, onConfirm, onSkip, onCancel }) {
  const [checkedIds, setCheckedIds] = useState(new Set());

  useEffect(() => {
    if (pendingBatch) setCheckedIds(new Set(pendingBatch.matches.map(m => m.id)));
  }, [pendingBatch]);

  const matches = pendingBatch?.matches || [];
  const selectedMatches = matches.filter(m => checkedIds.has(m.id));
  const totalCount = selectedMatches.length + (pendingBatch ? 1 : 0);

  const toggle = (id) => {
    setCheckedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  return (
    <Modal
      open={!!pendingBatch}
      onClose={onCancel}
      title="Categorize similar transactions?"
      size="md"
      testId="similar-transactions-modal"
      actions={
        <>
          <button className="btn btn-ghost" onClick={onCancel}>Cancel</button>
          <button className="btn btn-ghost" onClick={onSkip}>Just this one</button>
          <button className="btn btn-primary" onClick={() => onConfirm(selectedMatches)}>
            Categorize {totalCount}
          </button>
        </>
      }
    >
      {pendingBatch && (
        <>
          <p className="text-sm text-base-content/70 mb-3">
            These have the same account and description as the transaction you just categorized as{' '}
            <span className="font-semibold text-base-content">{pendingBatch.account.name}</span>. Uncheck any you don't want.
          </p>
          <div className="max-h-72 overflow-y-auto space-y-1.5 pr-1">
            <SimilarTransactionRow transaction={pendingBatch.tx} checked locked />
            {matches.map(m => (
              <SimilarTransactionRow
                key={m.id}
                transaction={m}
                checked={checkedIds.has(m.id)}
                onToggle={() => toggle(m.id)}
              />
            ))}
          </div>
        </>
      )}
    </Modal>
  );
}

export default function CategorizeMode({
  teamSlug,
  allAccounts,
  allAccountGroups,
  allPayees = [],
  backUrl,
}) {
  const [transactions, setTransactions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [categorized, setCategorized] = useState(0);
  const [totalCount, setTotalCount] = useState(0);
  const [streak, setStreak] = useState(0);
  const [showConfetti, setShowConfetti] = useState(false);
  const [isExiting, setIsExiting] = useState(false);
  const [undoStack, setUndoStack] = useState([]);
  const [isSkipping, setIsSkipping] = useState(false);
  const [skippedCount, setSkippedCount] = useState(0);
  const [suggestionsByTransaction, setSuggestionsByTransaction] = useState({});
  const suggestionsInFlight = useRef(new Set());
  const [localAccounts, setLocalAccounts] = useState(allAccounts);
  const [showCreateAccountModal, setShowCreateAccountModal] = useState(false);
  const [pendingBatch, setPendingBatch] = useState(null); // { account, tx, matches } awaiting the similar-transactions modal
  const [drafts, setDrafts] = useState({}); // transaction id -> { payee, description } edited but not yet filed
  const [error, setError] = useState(null);
  const [cardHeight, setCardHeight] = useState(220);
  const topCardRef = useRef(null);
  const headers = getApiHeaders();
  const uploadApi = useMemo(() => getUploadApiHelpers(teamSlug), [teamSlug]);
  const batchApi = useMemo(() => getBatchOperationsApi(teamSlug), [teamSlug]);
  const payeeOptions = useMemo(() => allPayees.map(p => p.name).filter(Boolean), [allPayees]);

  const fetchUncategorized = useCallback(async () => {
    setLoading(true);
    try {
      let allRows = [];
      let url = `/a/${teamSlug}/bankfeed/api/feed/`;
      while (url) {
        const resp = await fetch(url, { credentials: 'include', headers });
        const data = await resp.json();
        const rows = (data.results || []).filter(r => r.category === null && !r.is_archived);
        allRows = allRows.concat(rows);
        url = data.next || null;
      }
      setTransactions(allRows);
      if (totalCount === 0) setTotalCount(allRows.length);
    } catch (err) {
      console.error('Failed to fetch transactions:', err);
    } finally {
      setLoading(false);
    }
  }, [teamSlug]);

  // Ask the server which categories were used on transactions similar to these.
  // An id that comes back with nothing is cached as an empty list, so a
  // transaction with no lookalikes is asked about once rather than every render.
  const fetchSuggestions = useCallback(async (ids) => {
    const grouped = {};
    ids.forEach(id => { grouped[id] = []; });
    try {
      const resp = await fetch(
        `/a/${teamSlug}/bankfeed/api/feed/similar_categories/?ids=${ids.join(',')}`,
        { credentials: 'include', headers }
      );
      if (resp.ok) {
        (await resp.json()).forEach(row => {
          if (grouped[row.transaction_id]) grouped[row.transaction_id].push(row);
          else grouped[row.transaction_id] = [row];
        });
      }
    } catch (err) {
      // Suggestions are a shortcut, not the feature — a failed lookup leaves the
      // full category list, and the empty cache entries keep it from retrying in
      // a loop.
      console.error('Failed to load category suggestions:', err);
    } finally {
      setSuggestionsByTransaction(prev => ({ ...prev, ...grouped }));
      ids.forEach(id => suggestionsInFlight.current.delete(id));
    }
  }, [teamSlug]);

  // Only the cards about to be seen are looked up, so a queue of a thousand
  // transactions still costs one small request at a time.
  useEffect(() => {
    const wanted = transactions
      .slice(0, SUGGESTION_PREFETCH)
      .map(transactionId)
      .filter(id => id != null && !(id in suggestionsByTransaction) && !suggestionsInFlight.current.has(id));
    if (wanted.length === 0) return;
    wanted.forEach(id => suggestionsInFlight.current.add(id));
    fetchSuggestions(wanted);
  }, [transactions, suggestionsByTransaction, fetchSuggestions]);

  useEffect(() => {
    fetchUncategorized();
  }, []);

  // Categorizes one or more transactions to `account` in a single batched
  // request. `txList` always includes the top-of-stack transaction when
  // it's part of the batch, which drives the card-exit animation.
  const commitCategorize = useCallback(async (txList, account) => {
    if (!txList.length) return;
    const includesTop = txList.some(t => t.id === transactions[0]?.id);
    if (includesTop) setIsExiting(true);
    setError(null);

    // A card whose payee/description was edited goes through `batch_edit`,
    // which applies the edits and the category in one atomic request, so the
    // transaction is never left renamed but uncategorized. Anything untouched
    // takes the plain categorize path in a single batched call. Drafts belong
    // to individual cards, so a transaction swept into a batch still carries
    // its own edits rather than the edited card's.
    const edited = txList.map(t => ({ tx: t, changes: changedDetails(t, drafts[t.id]) })).filter(e => e.changes);
    const editedIds = new Set(edited.map(e => e.tx.id));
    const plain = txList.filter(t => !editedIds.has(t.id));

    try {
      await Promise.all([
        ...edited.map(({ tx, changes }) =>
          batchApi.batchEdit([transactionId(tx)], { category_id: account.id, ...changes })
        ),
        ...(plain.length
          ? [
              fetch(`/a/${teamSlug}/bankfeed/api/feed/categorize/`, {
                method: 'POST',
                credentials: 'include',
                headers: { ...headers, 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  rows: plain.map(t => ({ id: transactionId(t) })),
                  category_id: account.id,
                }),
              }).then(resp => {
                // A refusal must not let the card slide away as though it had
                // been filed.
                if (!resp.ok) throw new Error('Could not categorize that transaction.');
              }),
            ]
          : []),
      ]);

      const committedIds = new Set(txList.map(t => t.id));
      const newCategorized = categorized + txList.length;
      const newStreak = streak + 1;

      setUndoStack(prev => [...prev, { transactions: txList, account }]);

      // The decision(s) just made are evidence about every queued transaction
      // that looks like one of them, so those cached suggestions are now out
      // of date and are dropped for the prefetch to pick up again.
      const staleKeys = new Set(txList.map(lookalikeKey).filter(Boolean));
      const staleIds = staleKeys.size
        ? transactions
            .filter(t => !committedIds.has(t.id) && staleKeys.has(lookalikeKey(t)))
            .map(transactionId)
        : [];

      setTimeout(() => {
        setTransactions(prev => prev.filter(t => !committedIds.has(t.id)));
        // Dropped with the card rather than on the response, or the top card
        // would visibly snap back to the bank's wording mid-flight.
        if (editedIds.size > 0) {
          setDrafts(prev => {
            const next = { ...prev };
            editedIds.forEach(id => delete next[id]);
            return next;
          });
        }
        if (staleIds.length > 0) {
          setSuggestionsByTransaction(cached => {
            const next = { ...cached };
            staleIds.forEach(id => delete next[id]);
            return next;
          });
        }
        setCategorized(newCategorized);
        setStreak(newStreak);
        setIsExiting(false);

        if (Math.floor(newCategorized / 10) > Math.floor(categorized / 10)) {
          setShowConfetti(true);
          setTimeout(() => setShowConfetti(false), 3000);
        }
      }, includesTop ? 300 : 0);
    } catch (err) {
      console.error('Failed to categorize:', err);
      setError(err.message || 'Could not categorize that transaction.');
      setIsExiting(false);
    }
  }, [transactions, categorized, streak, teamSlug, headers, drafts, batchApi]);

  // Categorizing the top transaction: if other uncategorized transactions
  // share its home account and description, offer to categorize them the
  // same way instead of committing immediately.
  const categorizeTransaction = useCallback((account) => {
    const tx = transactions[0];
    if (!tx) return;

    const matches = findSimilarTransactions(transactions.slice(1), tx);
    if (matches.length > 0) {
      setPendingBatch({ account, tx, matches });
      return;
    }
    commitCategorize([tx], account);
  }, [transactions, commitCategorize]);

  const handleBatchConfirm = useCallback((selectedMatches) => {
    if (!pendingBatch) return;
    commitCategorize([pendingBatch.tx, ...selectedMatches], pendingBatch.account);
    setPendingBatch(null);
  }, [pendingBatch, commitCategorize]);

  const handleBatchSkip = useCallback(() => {
    if (!pendingBatch) return;
    commitCategorize([pendingBatch.tx], pendingBatch.account);
    setPendingBatch(null);
  }, [pendingBatch, commitCategorize]);

  const handleBatchCancel = useCallback(() => setPendingBatch(null), []);

  const handleCreateAccount = useCallback(async (name, accountGroupId) => {
    const newAccount = await uploadApi.createAccount(name, accountGroupId);
    setLocalAccounts(prev => [...prev, newAccount].sort((a, b) => a.name.localeCompare(b.name)));
    setShowCreateAccountModal(false);
    categorizeTransaction(newAccount);
    return newAccount;
  }, [uploadApi, categorizeTransaction]);

  // --- Payee/description drafts for the card on top of the stack ---

  const topTransaction = transactions[0] || null;

  const topDetails = useMemo(
    () => (topTransaction ? (drafts[topTransaction.id] ?? detailsOf(topTransaction)) : null),
    [topTransaction, drafts]
  );

  const topDetailsDirty = useMemo(
    () => (topTransaction ? changedDetails(topTransaction, drafts[topTransaction.id]) !== null : false),
    [topTransaction, drafts]
  );

  const handleDetailChange = useCallback((field, value) => {
    if (!topTransaction) return;
    setDrafts(prev => ({
      ...prev,
      [topTransaction.id]: { ...(prev[topTransaction.id] ?? detailsOf(topTransaction)), [field]: value },
    }));
  }, [topTransaction]);

  const handleDetailsRevert = useCallback(() => {
    if (!topTransaction) return;
    setDrafts(prev => {
      const next = { ...prev };
      delete next[topTransaction.id];
      return next;
    });
  }, [topTransaction]);

  // The cards are absolutely positioned, so the stack has no height of its own
  // and the container's minimum is the only thing holding the layout open. The
  // top card is the tall one (it carries the editor), so it is measured rather
  // than guessed at. The effect re-runs per card because React replaces the
  // DOM node when the top of the queue changes. Measured before paint, or the
  // stack visibly resettles on every card.
  useLayoutEffect(() => {
    const el = topCardRef.current;
    if (!el) return undefined;
    setCardHeight(el.offsetHeight);
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(() => setCardHeight(el.offsetHeight));
    observer.observe(el);
    return () => observer.disconnect();
  }, [topTransaction?.id]);

  const skipTransaction = useCallback(() => {
    const tx = transactions[0];
    if (!tx) return;
    setIsSkipping(true);
    setTimeout(() => {
      setTransactions(prev => [...prev.slice(1), prev[0]]);
      setSkippedCount(s => s + 1);
      setStreak(0);
      setIsSkipping(false);
    }, 300);
  }, [transactions]);

  useEffect(() => {
    const handler = (e) => {
      // The similar-transactions modal handles its own Escape (via the
      // dialog's `cancel` event) — don't also navigate away or skip under it.
      if (pendingBatch) return;
      if (e.key === 'Escape') window.location.href = backUrl;
      if (e.key === 's' && !e.ctrlKey && !e.metaKey && !['INPUT', 'TEXTAREA'].includes(e.target.tagName)) skipTransaction();
      if (e.key === 'z' && (e.ctrlKey || e.metaKey) && undoStack.length > 0) {
        e.preventDefault();
        // Undo not implemented on backend — just visual feedback
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [backUrl, undoStack, pendingBatch]);

  const currentId = transactionId(transactions[0]);
  const currentSuggestions = (currentId != null && suggestionsByTransaction[currentId]) || [];
  const suggestionsLoading = currentId != null && !(currentId in suggestionsByTransaction);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-base-200">
        <div className="text-center">
          <span className="loading loading-spinner loading-lg text-primary"></span>
          <p className="mt-4 text-base-content/70">Loading transactions...</p>
        </div>
      </div>
    );
  }

  if (transactions.length === 0) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-base-200">
        <Confetti active={categorized > 0} />
        <div className="card bg-base-100 shadow-xl p-8 text-center max-w-md">
          <div className="text-6xl mb-4">{categorized > 0 ? '🎉' : '✅'}</div>
          <h2 className="text-2xl font-black mb-2">
            {categorized > 0 ? 'All Done!' : 'Nothing to categorize'}
          </h2>
          <p className="text-base-content/70 mb-2">
            {categorized > 0
              ? `You categorized ${categorized} transactions!`
              : 'All your transactions are already categorized.'}
          </p>
          {categorized > 0 && (
            <div className="stats stats-horizontal shadow mb-4">
              <div className="stat py-3 px-4">
                <div className="stat-title text-xs">Categorized</div>
                <div className="stat-value text-primary text-2xl">{categorized}</div>
              </div>
              <div className="stat py-3 px-4">
                <div className="stat-title text-xs">Best Streak</div>
                <div className="stat-value text-warning text-2xl">{streak}</div>
              </div>
            </div>
          )}
          <a href={backUrl} className="btn btn-primary">
            ← Back to Bank Feed
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-base-200 flex flex-col">
      <Confetti active={showConfetti} />

      {/* Header */}
      <div className="bg-base-100 border-b border-base-300 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <a href={backUrl} className="btn btn-ghost btn-sm gap-1">
            ← Back
          </a>
          <h1 className="text-xl font-black tracking-tight">⚡ Categorize Mode</h1>
        </div>
        <div className="flex items-center gap-4">
          <StreakCounter streak={streak} />
          <div className="hidden sm:block w-48">
            <ProgressBar done={categorized} total={totalCount} />
          </div>
          <kbd className="kbd kbd-sm hidden lg:inline-flex">Esc to exit</kbd>
        </div>
      </div>

      {/* Mobile progress */}
      <div className="sm:hidden px-4 pt-3">
        <ProgressBar done={categorized} total={totalCount} />
      </div>

      {/* Main content */}
      <div className="flex-1 flex flex-col lg:flex-row gap-6 p-6 max-w-7xl mx-auto w-full">
        {/* Left: Card stack */}
        <div className="lg:w-2/5 flex flex-col items-center">
          {error && (
            <div className="alert alert-error mb-3 w-full max-w-md py-2" data-testid="categorize-error">
              <span className="text-sm">{error}</span>
              <button className="btn btn-ghost btn-xs" onClick={() => setError(null)}>✕</button>
            </div>
          )}
          {/* Cards behind the top one are pushed down by `offset * 8px` (see
              TransactionCard), so the stack's real bottom edge sits below the
              measured card — pad the container for the deepest card's offset
              or its shadow pokes out past this box. */}
          <div
            className="relative w-full max-w-md"
            style={{ minHeight: `${cardHeight + (Math.min(transactions.length, 5) - 1) * 8}px` }}
          >
            {transactions.slice(0, 5).map((tx, i) => (
              <TransactionCard
                key={tx.id}
                transaction={tx}
                index={i}
                total={Math.min(transactions.length, 5)}
                allTransactions={transactions}
                isExiting={isExiting}
                isSkipping={isSkipping}
                cardRef={topCardRef}
                details={topDetails}
                detailsDirty={topDetailsDirty}
                payeeOptions={payeeOptions}
                onDetailChange={handleDetailChange}
                onDetailsRevert={handleDetailsRevert}
              />
            ))}
          </div>
          <div className="mt-4 flex flex-col items-center gap-2">
            <button
              onClick={skipTransaction}
              disabled={isExiting || isSkipping}
              className="btn btn-ghost btn-sm gap-1 text-base-content/70 hover:text-base-content"
            >
              ⏭ Skip for now
              <kbd className="kbd kbd-xs ml-1">S</kbd>
            </button>
            <p className="text-sm text-base-content/40">
              {transactions.length} remaining{skippedCount > 0 ? ` · ${skippedCount} skipped` : ''}
            </p>
          </div>
        </div>

        {/* Right: Account hierarchy */}
        <div className="lg:w-3/5 bg-base-100 rounded-2xl border border-base-300 shadow-lg p-5 flex flex-col min-h-[400px] lg:min-h-0 lg:max-h-[calc(100vh-140px)]">
          <h2 className="text-lg font-bold mb-3 shrink-0">Choose a Category</h2>
          <AccountHierarchy
            allAccounts={localAccounts}
            allAccountGroups={allAccountGroups}
            suggestions={currentSuggestions}
            suggestionsLoading={suggestionsLoading}
            currentTransaction={transactions[0]}
            onSelect={categorizeTransaction}
            onCreateNew={() => setShowCreateAccountModal(true)}
          />
        </div>
      </div>

      {showCreateAccountModal && (
        <CreateAccountModal
          allAccountGroups={allAccountGroups}
          onSave={handleCreateAccount}
          onCancel={() => setShowCreateAccountModal(false)}
        />
      )}

      <SimilarTransactionsModal
        pendingBatch={pendingBatch}
        onConfirm={handleBatchConfirm}
        onSkip={handleBatchSkip}
        onCancel={handleBatchCancel}
      />

      <style>{`
        .card-exit {
          animation: cardExit 0.3s ease-in forwards;
        }
        @keyframes cardExit {
          0% { transform: translateX(0) rotate(0deg); opacity: 1; }
          100% { transform: translateX(120%) rotate(15deg); opacity: 0; }
        }
        .card-skip {
          animation: cardSkip 0.3s ease-in forwards;
        }
        @keyframes cardSkip {
          0% { transform: translateY(0); opacity: 1; }
          100% { transform: translateY(120%) scale(0.8); opacity: 0; }
        }
        .animate-in {
          animation: fadeIn 0.2s ease-out;
        }
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(-8px); }
          to { opacity: 1; transform: translateY(0); }
        }
        .animate-bounce-subtle {
          animation: bounceSoft 0.6s ease-out;
        }
        @keyframes bounceSoft {
          0%, 100% { transform: scale(1); }
          50% { transform: scale(1.15); }
        }
        .animate-pulse-subtle {
          animation: pulseSoft 2s ease-in-out infinite;
        }
        @keyframes pulseSoft {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.7; }
        }
        .custom-scrollbar::-webkit-scrollbar { width: 6px; }
        .custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
        .custom-scrollbar::-webkit-scrollbar-thumb { background: oklch(var(--bc) / 0.2); border-radius: 3px; }
      `}</style>
    </div>
  );
}
