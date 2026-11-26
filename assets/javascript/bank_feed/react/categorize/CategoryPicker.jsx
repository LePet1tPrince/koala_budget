/* globals gettext, interpolate */
import React, { useEffect, useMemo, useRef, useState } from 'react';

import Icon from '../../../common/Icon';
import { ACCOUNT_KIND_LABELS, accountKind, goalLeftLabel } from '../../../common/accountKind';
import { formatMoney } from '../../../common/amount';
import { directionOf, orderCategories } from '../../categoryOrder';
import { matchScore, suggestionBadge, suggestionNote } from './matching';
import { chipsFor } from './queue';

const TYPE_TABS = [
  { key: 'all', label: () => gettext('All'), kinds: null },
  { key: 'income_expense', label: () => gettext('Spending & income'), kinds: ['income', 'expense'] },
  { key: 'transfer', label: () => gettext('Transfers'), kinds: ['asset', 'liability'] },
  { key: 'goal', label: () => gettext('Goals'), kinds: ['goal', 'equity'] },
];

/** "$45 left" / "$12 over" for an expense this month, or what a goal has left; null otherwise. */
export function leftLabel(account, figure) {
  const kind = accountKind(account);
  if (kind === 'goal') return goalLeftLabel(account);
  // A category with no budget and nothing left over has nothing worth saying.
  if (kind !== 'expense' || !figure || (figure.budgeted === 0 && figure.available === 0)) return null;
  return figure.available < 0
    ? interpolate(gettext('%s over'), [formatMoney(-figure.available)])
    : interpolate(gettext('%s left'), [formatMoney(figure.available)]);
}

// Undo's modifier as the keyboard in front of the user labels it.
export const UNDO_KEY = /Mac|iPhone|iPad/.test(globalThis.navigator?.platform || '') ? '⌘' : 'ctrl';

const isPrintable = (e) => e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey;

/**
 * Where a category is chosen: the search box (always focused), the shortcut
 * chips (keys 1-9: the suggestions, then the categories used most this way) and
 * every category below, ordered for the transaction (`categoryOrder.js`).
 *
 * The search box carries the queue's keyboard. With it empty, keys that would
 * otherwise do nothing in an empty box are commands: Enter files the first
 * suggestion, 1-9 a chip, → skips, Ctrl/⌘+Z undoes, Escape asks to leave. With
 * text in it they edit the text, ↑/↓ walk the results and Enter takes the
 * highlighted one.
 */
export default function CategoryPicker({
  accounts,
  usage,
  row,
  suggestions,
  loading,
  figures,
  searchRef,
  commandsRef,
  autoFocus,
  onSelect,
  onSplit,
  onCreateNew,
  onSkip,
  onUndo,
  onEscape,
}) {
  const [query, setQuery] = useState('');
  const [tab, setTab] = useState('all');
  const [activeIndex, setActiveIndex] = useState(-1);
  const panelRef = useRef(null);
  const search = query.trim();

  const accountsById = useMemo(() => Object.fromEntries(accounts.map((a) => [a.id, a])), [accounts]);
  const feedAccountId = row?.account?.id ?? null;

  // A search means none of the suggestions was it: they leave the chips, and
  // turn up in the results instead.
  const chips = useMemo(
    () => (search ? [] : chipsFor(row, suggestions, accounts, usage)),
    [search, row, suggestions, accounts, usage],
  );
  const suggestedIds = useMemo(() => new Set(suggestions.map((s) => s.category_id)), [suggestions]);

  const groups = useMemo(() => {
    const kinds = TYPE_TABS.find((t) => t.key === tab)?.kinds;
    const inTab = accounts.filter((a) => !kinds || kinds.includes(accountKind(a)));
    if (search) {
      const ranked = inTab
        .filter((a) => a.id !== feedAccountId)
        .map((a) => ({ account: a, score: matchScore(a, search) }))
        .filter((r) => r.score !== null)
        .sort((a, b) => b.score - a.score || a.account.name.localeCompare(b.account.name))
        .map((r) => r.account);
      return ranked.length ? [{ name: gettext('Search results'), accounts: ranked }] : [];
    }
    const feedAccount = feedAccountId != null ? accountsById[feedAccountId] : null;
    return orderCategories(
      inTab.filter((a) => !suggestedIds.has(a.id)),
      {
        direction: directionOf(row),
        feedAccountId,
        feedKind: feedAccount ? accountKind(feedAccount) : 'asset',
        usage,
      },
    );
  }, [accounts, accountsById, tab, search, feedAccountId, suggestedIds, row, usage]);

  const navRows = useMemo(() => groups.flatMap((g) => g.accounts), [groups]);
  const activeIdx = navRows.length === 0 ? -1 : Math.min(activeIndex, navRows.length - 1);
  const activeId = activeIdx >= 0 ? navRows[activeIdx].id : null;

  // A new transaction starts with a clean slate and the cursor in the box --
  // with a keyboard: on a touch screen focusing it would raise the keyboard
  // over the card being swiped.
  useEffect(() => {
    setQuery('');
    setTab('all');
    setActiveIndex(-1);
    if (autoFocus) searchRef.current?.focus({ preventScroll: true });
  }, [row?.id, searchRef, autoFocus]);

  useEffect(() => setActiveIndex(-1), [tab]);

  // Gone with the picker: the end screen has no chips to press.
  useEffect(
    () => () => {
      if (commandsRef) commandsRef.current = null;
    },
    [commandsRef],
  );

  useEffect(() => {
    if (activeId == null) return;
    panelRef.current?.querySelector(`[data-nav-key="a:${activeId}"]`)?.scrollIntoView({ block: 'nearest' });
  }, [activeId]);

  const pick = (account, el) => {
    if (!account) return;
    onSelect(account, el ?? null);
  };

  const chipEl = (index) => panelRef.current?.querySelector(`[data-chip-index="${index}"]`);

  const handleKeyDown = (e) => {
    const empty = query === '';
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (navRows.length === 0) return;
      const step = e.key === 'ArrowDown' ? 1 : -1;
      setActiveIndex(
        activeIdx < 0 ? (step === 1 ? 0 : navRows.length - 1) : (activeIdx + step + navRows.length) % navRows.length,
      );
      return;
    }
    if (e.key === 'Enter') {
      e.preventDefault();
      if (activeIdx >= 0) {
        pick(navRows[activeIdx], panelRef.current?.querySelector(`[data-nav-key="a:${navRows[activeIdx].id}"]`));
      } else if (empty && chips[0]?.suggestion) {
        // Only a suggestion: a stray Enter never files to a merely frequent category.
        pick(chips[0].account, chipEl(0));
      }
      return;
    }
    if (empty && /^[1-9]$/.test(e.key) && isPrintable(e)) {
      const index = Number(e.key) - 1;
      if (chips[index]) {
        e.preventDefault();
        pick(chips[index].account, chipEl(index));
      }
      return;
    }
    if (empty && e.key === 'ArrowRight') {
      e.preventDefault();
      onSkip();
      return;
    }
    if (empty && e.key.toLowerCase() === 'z' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      onUndo();
      return;
    }
    if (e.key === 'Escape') {
      // Back out of the search first; only an empty box asks to leave.
      e.preventDefault();
      e.stopPropagation();
      if (!empty) {
        setQuery('');
        setActiveIndex(-1);
      } else {
        onEscape();
      }
    }
  };
  // The same commands when focus is elsewhere on the page (a chip just clicked).
  if (commandsRef) commandsRef.current = handleKeyDown;

  return (
    <div className="flex flex-col h-full min-h-0" ref={panelRef} data-testid="categorize-picker">
      <div className="relative">
        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-base-content/70" aria-hidden="true">
          🔍
        </span>
        <input
          ref={searchRef}
          type="text"
          value={query}
          onChange={(e) => {
            // Typing points the highlight at the best match, so Enter takes it.
            setQuery(e.target.value);
            setActiveIndex(e.target.value ? 0 : -1);
          }}
          onKeyDown={handleKeyDown}
          placeholder={gettext('Type a category…')}
          aria-label={gettext('Search categories')}
          data-testid="categorize-search"
          className="input input-bordered w-full pl-9 pr-8"
          autoComplete="off"
        />
        {query && (
          <button
            type="button"
            onClick={() => {
              setQuery('');
              setActiveIndex(-1);
              searchRef.current?.focus();
            }}
            className="absolute right-2 top-1/2 -translate-y-1/2 btn btn-ghost btn-xs btn-circle"
            aria-label={gettext('Clear search')}
          >
            ✕
          </button>
        )}
      </div>
      <KeyHints searching={query !== ''} hasSuggestion={Boolean(chips[0]?.suggestion)} />

      {loading && !search && (
        <div className="mb-2 flex items-center gap-2 text-xs text-base-content/70">
          <span className="loading loading-spinner loading-xs" />
          {gettext('Looking for similar transactions…')}
        </div>
      )}

      {chips.length > 0 && (
        <div
          className="grid grid-cols-2 sm:grid-cols-3 gap-2 mb-3"
          data-testid={suggestions.length ? 'category-suggestions' : 'category-chips'}
        >
          {chips.map((chip, i) => (
            <Chip
              key={chip.account.id}
              index={i}
              chip={chip}
              left={leftLabel(chip.account, figures?.[chip.account.id])}
              onPick={(el) => pick(chip.account, el)}
            />
          ))}
        </div>
      )}

      <div className="tabs tabs-box tabs-xs mb-2 self-start" role="tablist">
        {TYPE_TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            className={`tab ${tab === t.key ? 'tab-active' : ''}`}
            onClick={() => {
              setTab(t.key);
              searchRef.current?.focus();
            }}
            data-testid={`categorize-tab-${t.key}`}
          >
            {t.label()}
          </button>
        ))}
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto pr-1 pb-1 space-y-3" data-testid="categorize-list">
        {groups.length === 0 && (
          <div className="text-center py-6 text-base-content/70">
            <p className="mb-1">{gettext('No matching categories')}</p>
            <p className="text-sm">{gettext('Try other words, or create one below.')}</p>
          </div>
        )}
        {groups.map((group) => (
          <div key={group.name} data-testid="category-group">
            <div className="text-xs font-semibold text-base-content/70 uppercase tracking-wider px-1 mb-1 sticky top-0 bg-base-100 py-1 z-10">
              {group.name}
            </div>
            <div className="space-y-1">
              {group.accounts.map((account) => {
                const active = activeId === account.id;
                const left = leftLabel(account, figures?.[account.id]);
                return (
                  <button
                    key={account.id}
                    type="button"
                    onClick={(e) => pick(account, e.currentTarget)}
                    data-nav-key={`a:${account.id}`}
                    data-kind={accountKind(account)}
                    data-testid="category-row"
                    data-active={active ? 'true' : undefined}
                    className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg border border-base-300 transition-colors hover:border-primary hover:bg-primary/5 ${
                      active
                        ? 'ring-2 ring-primary ring-offset-2 ring-offset-base-100 border-primary bg-primary/10'
                        : ''
                    }`}
                  >
                    <div className="flex-1 text-left min-w-0">
                      <div className="font-medium truncate">{account.name}</div>
                      <div className="text-xs text-base-content/70 flex gap-2">
                        <span>{ACCOUNT_KIND_LABELS[accountKind(account)] || account.account_type}</span>
                        {left && (
                          <>
                            <span>·</span>
                            <span data-testid={accountKind(account) === 'goal' ? 'goal-left' : 'budget-left'}>
                              {left}
                            </span>
                          </>
                        )}
                        {account.institution_name && (
                          <>
                            <span>·</span>
                            <span>{account.institution_name}</span>
                          </>
                        )}
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        ))}

        {/* The two ways out of "none of these single categories is right". */}
        <div className="grid grid-cols-2 gap-2 pt-1">
          <button
            type="button"
            onClick={onSplit}
            className="flex items-center justify-center gap-2 px-3 py-2 rounded-lg border border-dashed border-base-300 text-base-content/70 hover:border-primary hover:text-primary"
            data-testid="categorize-split-btn"
          >
            <Icon name="split" className="h-4 w-4" />
            <span className="font-medium">{gettext('Split')}</span>
          </button>
          <button
            type="button"
            onClick={onCreateNew}
            className="flex items-center justify-center gap-2 px-3 py-2 rounded-lg border border-dashed border-base-300 text-base-content/70 hover:border-primary hover:text-primary"
            data-testid="categorize-create-btn"
          >
            <Icon name="plus" className="h-4 w-4" />
            <span className="font-medium">{gettext('New category')}</span>
          </button>
        </div>
      </div>
    </div>
  );
}

function Chip({ index, chip, left, onPick }) {
  const { account, suggestion } = chip;
  return (
    <button
      type="button"
      onClick={(e) => onPick(e.currentTarget)}
      data-chip-index={index}
      data-testid={suggestion ? 'category-suggestion' : 'category-chip'}
      title={suggestion ? suggestionNote(suggestion) : undefined}
      className={`relative flex items-start gap-2 px-2.5 py-2 rounded-lg border text-left transition-transform active:scale-95 ${
        suggestion
          ? 'border-success bg-success/10 hover:bg-success/20'
          : 'border-base-300 bg-base-100 hover:border-primary hover:bg-primary/5'
      }`}
    >
      <kbd className="kbd kbd-xs mt-0.5 shrink-0">{index + 1}</kbd>
      <span className="min-w-0 flex-1">
        <span className="block font-semibold truncate leading-tight">{account.name}</span>
        <span className="block text-xs text-base-content/70 truncate">
          {suggestion && <span data-testid="category-suggestion-note">{suggestionBadge(suggestion)}</span>}
          {suggestion && left && ' · '}
          {left && <span data-testid={accountKind(account) === 'goal' ? 'goal-left' : 'budget-left'}>{left}</span>}
          {!suggestion && !left && <span>{ACCOUNT_KIND_LABELS[accountKind(account)]}</span>}
        </span>
      </span>
      {suggestion && <span className="sr-only">{suggestionNote(suggestion)}</span>}
    </button>
  );
}

function KeyHints({ searching, hasSuggestion }) {
  const hint = (keys, label) => (
    <span className="inline-flex items-center gap-1">
      {keys.map((k) => (
        <kbd key={k} className="kbd kbd-xs">
          {k}
        </kbd>
      ))}
      <span>{label}</span>
    </span>
  );
  return (
    <div
      className="hidden sm:flex flex-wrap items-center gap-x-3 gap-y-1 my-2 text-xs text-base-content/70"
      data-testid="categorize-key-hints"
    >
      {searching ? (
        <>
          {hint(['↑', '↓'], gettext('move'))}
          {hint(['↵'], gettext('choose'))}
          {hint(['esc'], gettext('clear'))}
        </>
      ) : (
        <>
          {hasSuggestion && hint(['↵'], gettext('top suggestion'))}
          {hint(['1–9'], gettext('pick'))}
          {hint(['→'], gettext('skip'))}
          {hint([UNDO_KEY, 'z'], gettext('undo'))}
          {hint(['esc'], gettext('leave'))}
        </>
      )}
    </div>
  );
}
