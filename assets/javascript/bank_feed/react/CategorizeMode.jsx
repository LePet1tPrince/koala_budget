import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { getApiHeaders } from '../../api';

const CATEGORY_GROUPS = [
  {
    key: 'income_expense',
    label: 'Income / Expense',
    icon: '💸',
    gradient: 'from-green-500 to-orange-500',
    types: ['income', 'expense'],
  },
  {
    key: 'transfer',
    label: 'Transfer',
    icon: '🔄',
    gradient: 'from-blue-500 to-purple-500',
    types: ['asset', 'liability'],
  },
  {
    key: 'goal',
    label: 'Goals',
    icon: '🎯',
    gradient: 'from-amber-500 to-yellow-500',
    types: ['goal'],
  },
];

function formatCurrency(amount) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(amount);
}

function Confetti({ active }) {
  const canvasRef = useRef(null);
  const animRef = useRef(null);

  useEffect(() => {
    if (!active || !canvasRef.current) return;
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;

    const colors = ['#ff6b6b', '#feca57', '#48dbfb', '#ff9ff3', '#54a0ff', '#5f27cd', '#01a3a4', '#f368e0'];
    const particles = Array.from({ length: 150 }, () => ({
      x: Math.random() * canvas.width,
      y: Math.random() * canvas.height - canvas.height,
      w: Math.random() * 10 + 5,
      h: Math.random() * 6 + 3,
      color: colors[Math.floor(Math.random() * colors.length)],
      vx: (Math.random() - 0.5) * 6,
      vy: Math.random() * 3 + 2,
      rot: Math.random() * 360,
      rotV: (Math.random() - 0.5) * 10,
      opacity: 1,
    }));

    let frame = 0;
    const animate = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      frame++;
      let alive = false;
      particles.forEach(p => {
        p.x += p.vx;
        p.y += p.vy;
        p.vy += 0.05;
        p.rot += p.rotV;
        if (frame > 60) p.opacity -= 0.01;
        if (p.opacity <= 0) return;
        alive = true;
        ctx.save();
        ctx.translate(p.x, p.y);
        ctx.rotate((p.rot * Math.PI) / 180);
        ctx.globalAlpha = Math.max(0, p.opacity);
        ctx.fillStyle = p.color;
        ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h);
        ctx.restore();
      });
      if (alive) animRef.current = requestAnimationFrame(animate);
    };
    animRef.current = requestAnimationFrame(animate);
    return () => { if (animRef.current) cancelAnimationFrame(animRef.current); };
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
        className="btn btn-ghost btn-xs btn-circle text-base-content/50 hover:text-primary"
        title="Similar transactions"
      >
        🔍
      </button>
      {open && (
        <div className="absolute right-0 top-8 z-50 bg-base-100 border border-base-300 rounded-xl shadow-2xl p-3 w-72 animate-in">
          <p className="text-xs font-semibold text-base-content/60 mb-2">Similar transactions</p>
          {similar.map(t => (
            <div key={t.id} className="flex justify-between items-center py-1.5 border-b border-base-200 last:border-0 text-xs">
              <div>
                <div className="font-medium">{t.merchant_name || t.description}</div>
                <div className="text-base-content/50">{t.posted_date}</div>
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
              <p className="text-xs text-base-content/50 mb-1">
                {transaction.account?.name || 'Unknown Account'}
              </p>
              <h3 className="font-bold text-lg truncate">
                {transaction.merchant_name || transaction.description || 'No description'}
              </h3>
              {transaction.merchant_name && transaction.description && (
                <p className="text-sm text-base-content/60 truncate">{transaction.description}</p>
              )}
            </div>
          </div>
          <div className="flex items-center justify-between mt-3">
            <span className="text-sm text-base-content/60">{transaction.posted_date}</span>
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

function AccountHierarchy({ allAccounts, allAccountGroups, categorySuggestions, currentTransaction, onSelect }) {
  const [activeCategoryGroup, setActiveCategoryGroup] = useState(null);
  const [activeAccountGroup, setActiveAccountGroup] = useState(null);

  const suggestedAccountId = useMemo(() => {
    if (!currentTransaction) return null;
    const merchant = (currentTransaction.merchant_name || '').toLowerCase();
    if (!merchant) return null;
    const suggestion = categorySuggestions.find(s =>
      s.merchant_name?.toLowerCase() === merchant
    );
    return suggestion?.category_id || null;
  }, [currentTransaction, categorySuggestions]);

  const groupedHierarchy = useMemo(() => {
    return CATEGORY_GROUPS.map(cg => {
      const accountGroups = allAccountGroups
        .filter(g => cg.types.includes(g.account_type))
        .map(g => ({
          ...g,
          accounts: allAccounts.filter(a => a.account_group === g.id),
        }))
        .filter(g => g.accounts.length > 0);
      const totalAccounts = accountGroups.reduce((sum, g) => sum + g.accounts.length, 0);
      return { ...cg, accountGroups, totalAccounts };
    }).filter(cg => cg.totalAccounts > 0);
  }, [allAccounts, allAccountGroups]);

  const resetNav = () => { setActiveCategoryGroup(null); setActiveAccountGroup(null); };

  return (
    <div className="flex flex-col h-full">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 mb-4 min-h-[32px]">
        <button
          onClick={resetNav}
          className={`btn btn-xs ${!activeCategoryGroup ? 'btn-primary' : 'btn-ghost'}`}
        >
          All
        </button>
        {activeCategoryGroup && (
          <>
            <span className="text-base-content/30">›</span>
            <button
              onClick={() => setActiveAccountGroup(null)}
              className={`btn btn-xs ${!activeAccountGroup ? 'btn-primary' : 'btn-ghost'}`}
            >
              {activeCategoryGroup.icon} {activeCategoryGroup.label}
            </button>
          </>
        )}
        {activeAccountGroup && (
          <>
            <span className="text-base-content/30">›</span>
            <span className="btn btn-xs btn-primary">{activeAccountGroup.name}</span>
          </>
        )}
      </div>

      {/* Suggested account */}
      {suggestedAccountId && !activeCategoryGroup && (
        <div className="mb-4 animate-pulse-subtle">
          <p className="text-xs font-semibold text-success mb-2">✨ Suggested</p>
          {(() => {
            const acct = allAccounts.find(a => a.id === suggestedAccountId);
            if (!acct) return null;
            return (
              <button
                onClick={() => onSelect(acct)}
                className="btn btn-outline btn-success w-full justify-start gap-2 text-left"
              >
                <span className="font-bold">{acct.name}</span>
                <span className="text-xs opacity-60 ml-auto">{acct.account_group_name}</span>
              </button>
            );
          })()}
        </div>
      )}

      {/* Hierarchy browser */}
      <div className="flex-1 overflow-y-auto space-y-2 pr-1 custom-scrollbar">
        {!activeCategoryGroup && !activeAccountGroup && (
          groupedHierarchy.map(cg => (
            <button
              key={cg.key}
              onClick={() => setActiveCategoryGroup(cg)}
              className={`w-full flex items-center gap-3 p-4 rounded-xl border border-base-300 hover:border-primary hover:shadow-md transition-all bg-gradient-to-r ${cg.gradient} bg-opacity-5 hover:bg-opacity-10 group`}
            >
              <span className="text-2xl">{cg.icon}</span>
              <div className="flex-1 text-left">
                <div className="font-bold text-base-content">{cg.label}</div>
                <div className="text-xs text-base-content/50">
                  {cg.totalAccounts} accounts
                </div>
              </div>
              <span className="text-base-content/30 group-hover:text-primary transition-colors">›</span>
            </button>
          ))
        )}

        {activeCategoryGroup && !activeAccountGroup && (
          activeCategoryGroup.accountGroups.map(group => (
            <button
              key={group.id}
              onClick={() => setActiveAccountGroup(group)}
              className="w-full flex items-center gap-3 p-3 rounded-xl border border-base-300 hover:border-primary hover:shadow-md transition-all group"
            >
              <div className="flex-1 text-left">
                <div className="font-semibold">{group.name}</div>
                <div className="text-xs text-base-content/50">{group.accounts.length} accounts</div>
              </div>
              <span className="text-base-content/30 group-hover:text-primary transition-colors">›</span>
            </button>
          ))
        )}

        {activeCategoryGroup && activeAccountGroup && (
          activeAccountGroup.accounts.map(account => (
            <button
              key={account.id}
              onClick={() => onSelect(account)}
              className={`w-full flex items-center gap-3 p-3 rounded-xl border transition-all hover:shadow-lg active:scale-95 ${
                account.id === suggestedAccountId
                  ? 'border-success bg-success/10 hover:bg-success/20'
                  : 'border-base-300 hover:border-primary hover:bg-primary/5'
              }`}
            >
              <div className="flex-1 text-left">
                <div className="font-medium">{account.name}</div>
                {account.institution_name && (
                  <div className="text-xs text-base-content/50">{account.institution_name}</div>
                )}
              </div>
              {account.id === suggestedAccountId && (
                <span className="badge badge-success badge-sm">Suggested</span>
              )}
            </button>
          ))
        )}
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
        <span className="text-base-content/50">{total - done} remaining</span>
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
  const headers = getApiHeaders();

  const fetchUncategorized = useCallback(async () => {
    setLoading(true);
    try {
      let allRows = [];
      let url = `/a/${teamSlug}/bankfeed/api/feed/`;
      while (url) {
        const resp = await fetch(url, { credentials: 'include', headers });
        const data = await resp.json();
        const rows = (data.results || []).filter(r => !r.is_categorized && !r.is_archived);
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
      if (e.key === 's' && !e.ctrlKey && !e.metaKey) skipTransaction();
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
          <p className="mt-4 text-base-content/60">Loading transactions...</p>
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
          <p className="text-base-content/60 mb-2">
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
              className="btn btn-ghost btn-sm gap-1 text-base-content/50 hover:text-base-content"
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
            allAccounts={allAccounts}
            allAccountGroups={allAccountGroups}
            categorySuggestions={categorySuggestions}
            currentTransaction={transactions[0]}
            onSelect={categorizeTransaction}
          />
        </div>
      </div>

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
