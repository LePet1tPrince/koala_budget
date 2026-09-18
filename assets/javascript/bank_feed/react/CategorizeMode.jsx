import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { getApiHeaders } from '../../api';
import { createConfetti } from '../../common/confetti';
import { getUploadApiHelpers } from '../bank_feed';
import CreateAccountModal from './CSVUploadWizard/CreateAccountModal';

const ACCOUNT_TYPE_ORDER = ['expense', 'income', 'asset', 'liability', 'goal'];

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

function TransactionCard({ transaction, index, total, allTransactions, isExiting, isSkipping }) {
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
      <div className={`card bg-base-100 shadow-xl border border-base-300 ${isTop ? 'ring-2 ring-primary/30' : ''}`}>
        <div className="card-body p-5">
          {isTop && (
            <div className="absolute top-3 right-3">
              <SimilarTransactionsTooltip transaction={transaction} allTransactions={allTransactions} />
            </div>
          )}
          <div className="flex items-start justify-between">
            <div className="flex-1 min-w-0">
              <p className="text-xs text-base-content/70 mb-1">
                {transaction.account?.name || 'Unknown Account'}
              </p>
              <h3 className="font-bold text-lg truncate">
                {transaction.merchant_name || transaction.description || 'No description'}
              </h3>
              {transaction.merchant_name && transaction.description && (
                <p className="text-sm text-base-content/70 truncate">{transaction.description}</p>
              )}
            </div>
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

function AccountHierarchy({ allAccounts, allAccountGroups, categorySuggestions, currentTransaction, onSelect, onCreateNew }) {
  const [searchQuery, setSearchQuery] = useState('');
  const [activeTopFilter, setActiveTopFilter] = useState(null); // TOP_LEVEL_FILTERS key
  const [filterGroupId, setFilterGroupId] = useState(null);
  const [filterInstitution, setFilterInstitution] = useState(null);
  const searchRef = useRef(null);

  const activeTopGroup = useMemo(
    () => TOP_LEVEL_FILTERS.find(f => f.key === activeTopFilter) || null,
    [activeTopFilter]
  );
  const activeTypes = activeTopGroup?.types || null;

  const suggestedAccountId = useMemo(() => {
    if (!currentTransaction) return null;
    // The account this transaction is already sitting in — never suggest it
    // as the category, or categorizing would make it a transfer to itself.
    const feedAccountId = currentTransaction.account?.id ?? null;

    // Rule: an account name (or a whole word from one) named verbatim in the
    // memo/payee is the strongest signal — it's often literally naming the
    // other side of a transfer — so it wins over the merchant-history guess.
    const memoText = [currentTransaction.description, currentTransaction.merchant_name]
      .filter(Boolean).join(' ');
    const namedAccount = findAccountNamedInText(memoText, allAccounts, feedAccountId);
    if (namedAccount) return namedAccount.id;

    // Fallback: most recently used category for this exact merchant.
    const merchant = (currentTransaction.merchant_name || '').toLowerCase();
    if (!merchant) return null;
    const suggestion = categorySuggestions.find(s =>
      s.merchant_name?.toLowerCase() === merchant
    );
    if (!suggestion?.category_id || suggestion.category_id === feedAccountId) return null;
    return suggestion.category_id;
  }, [currentTransaction, categorySuggestions, allAccounts]);

  const suggestedAccount = useMemo(() => {
    if (!suggestedAccountId) return null;
    return allAccounts.find(a => a.id === suggestedAccountId) || null;
  }, [suggestedAccountId, allAccounts]);

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

  const clearFilters = () => {
    setActiveTopFilter(null);
    setFilterGroupId(null);
    setFilterInstitution(null);
    setSearchQuery('');
  };

  useEffect(() => { searchRef.current?.focus(); }, []);

  useEffect(() => {
    setActiveTopFilter(null);
    setFilterGroupId(null);
    setFilterInstitution(null);
    setSearchQuery('');
    searchRef.current?.focus();
  }, [currentTransaction?.id]);

  return (
    <div className="flex flex-col h-full">
      {/* Search bar */}
      <div className="relative mb-3">
        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-base-content/40">🔍</span>
        <input
          ref={searchRef}
          type="text"
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
          placeholder="Search accounts..."
          className="input input-bordered input-sm w-full pl-9 pr-8"
        />
        {searchQuery && (
          <button
            onClick={() => { setSearchQuery(''); searchRef.current?.focus(); }}
            className="absolute right-2 top-1/2 -translate-y-1/2 btn btn-ghost btn-xs btn-circle"
          >
            ✕
          </button>
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

      {/* Suggested account — always at top */}
      {suggestedAccount && (
        <div className="mb-3 animate-pulse-subtle">
          <p className="text-xs font-semibold text-success mb-1.5">✨ Suggested</p>
          <button
            onClick={() => onSelect(suggestedAccount)}
            className="btn btn-outline btn-success w-full justify-start gap-2 text-left"
          >
            <span className="font-bold">{suggestedAccount.name}</span>
            <span className="text-xs opacity-60 ml-auto">{suggestedAccount.account_group_name}</span>
          </button>
        </div>
      )}

      {/* Account list grouped by account group */}
      <div className="flex-1 overflow-y-auto pr-1 custom-scrollbar">
        {groupedAccounts.length === 0 && (
          <div className="text-center py-8 text-base-content/40">
            <p className="text-lg mb-1">No matching accounts</p>
            <p className="text-sm">Try a different search or clear filters</p>
          </div>
        )}
        {groupedAccounts.map(group => (
          <div key={group.name} className="mb-3">
            <div className="text-xs font-semibold text-base-content/70 uppercase tracking-wider px-1 mb-1.5 sticky top-0 bg-base-100 py-1 z-10">
              {group.name}
            </div>
            <div className="space-y-1">
              {group.accounts.map(account => (
                <button
                  key={account.id}
                  onClick={() => onSelect(account)}
                  className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg border transition-all hover:shadow-md active:scale-[0.98] ${
                    account.id === suggestedAccountId
                      ? 'border-success bg-success/10 hover:bg-success/20'
                      : 'border-base-300 hover:border-primary hover:bg-primary/5'
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
                  {account.id === suggestedAccountId && (
                    <span className="badge badge-success badge-sm shrink-0">Suggested</span>
                  )}
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

export default function CategorizeMode({
  teamSlug,
  allAccounts,
  allAccountGroups,
  categorySuggestions: initialSuggestions,
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
  const [categorySuggestions, setCategorySuggestions] = useState(initialSuggestions || []);
  const [localAccounts, setLocalAccounts] = useState(allAccounts);
  const [showCreateAccountModal, setShowCreateAccountModal] = useState(false);
  const headers = getApiHeaders();
  const uploadApi = useMemo(() => getUploadApiHelpers(teamSlug), [teamSlug]);

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

  const fetchSuggestions = useCallback(async () => {
    try {
      const resp = await fetch(`/a/${teamSlug}/bankfeed/api/feed/category_suggestions/`, {
        credentials: 'include',
        headers,
      });
      if (resp.ok) setCategorySuggestions(await resp.json());
    } catch (err) { /* ignore */ }
  }, [teamSlug]);

  useEffect(() => {
    fetchUncategorized();
    if (!initialSuggestions?.length) fetchSuggestions();
  }, []);

  const categorizeTransaction = useCallback(async (account) => {
    const tx = transactions[0];
    if (!tx) return;

    setIsExiting(true);

    try {
      await fetch(`/a/${teamSlug}/bankfeed/api/feed/categorize/`, {
        method: 'POST',
        credentials: 'include',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ rows: [{ id: tx.imported_transaction_id || tx.id }], category_id: account.id }),
      });

      const newCategorized = categorized + 1;
      const newStreak = streak + 1;

      setUndoStack(prev => [...prev, { transaction: tx, account }]);

      setTimeout(() => {
        setTransactions(prev => prev.slice(1));
        setCategorized(newCategorized);
        setStreak(newStreak);
        setIsExiting(false);

        if (newCategorized % 10 === 0 && newCategorized > 0) {
          setShowConfetti(true);
          setTimeout(() => setShowConfetti(false), 3000);
        }
      }, 300);
    } catch (err) {
      console.error('Failed to categorize:', err);
      setIsExiting(false);
    }
  }, [transactions, categorized, streak, teamSlug, headers]);

  const handleCreateAccount = useCallback(async (name, accountGroupId) => {
    const newAccount = await uploadApi.createAccount(name, accountGroupId);
    setLocalAccounts(prev => [...prev, newAccount].sort((a, b) => a.name.localeCompare(b.name)));
    setShowCreateAccountModal(false);
    categorizeTransaction(newAccount);
    return newAccount;
  }, [uploadApi, categorizeTransaction]);

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
      if (e.key === 'Escape') window.location.href = backUrl;
      if (e.key === 's' && !e.ctrlKey && !e.metaKey && !['INPUT', 'TEXTAREA'].includes(e.target.tagName)) skipTransaction();
      if (e.key === 'z' && (e.ctrlKey || e.metaKey) && undoStack.length > 0) {
        e.preventDefault();
        // Undo not implemented on backend — just visual feedback
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [backUrl, undoStack]);

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
          <div className="relative w-full max-w-md" style={{ minHeight: '220px' }}>
            {transactions.slice(0, 5).map((tx, i) => (
              <TransactionCard
                key={tx.id}
                transaction={tx}
                index={i}
                total={Math.min(transactions.length, 5)}
                allTransactions={transactions}
                isExiting={isExiting}
                isSkipping={isSkipping}
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
          <h2 className="text-lg font-bold mb-3">Choose a Category</h2>
          <AccountHierarchy
            allAccounts={localAccounts}
            allAccountGroups={allAccountGroups}
            categorySuggestions={categorySuggestions}
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
