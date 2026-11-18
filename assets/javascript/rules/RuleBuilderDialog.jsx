import React, { useEffect, useMemo, useState } from 'react';

import RuleBuilder from './RuleBuilder';
import { rulesApiForBook } from './api';

/* globals gettext */

/**
 * The rule builder as a dialog any page can open over itself -- the bank feed and
 * Categorize Mode -- so closing it puts the user straight back where they were.
 *
 * `request` is null (closed), `{ ruleId }` to edit a saved rule (loaded here), or
 * `{ draft }` for a new rule (`{}` for a blank one). `categories` are the page's
 * picker accounts; the feed accounts the rule may be limited to are taken from them.
 */
export default function RuleBuilderDialog({ request, onClose, onSaved, onDeleted, bookBase, categories, canEdit }) {
  const api = useMemo(() => rulesApiForBook(bookBase), [bookBase]);
  const [initial, setInitial] = useState(null);
  const [error, setError] = useState('');

  const feedAccounts = useMemo(
    () =>
      (categories || [])
        .filter((a) => (a.has_feed ?? a.hasFeed) && !(a.is_hidden ?? a.isHidden))
        .map((a) => ({ id: a.id, name: a.name, account_group_name: a.account_group_name ?? a.accountGroupName ?? '' }))
        .sort((x, y) => x.account_group_name.localeCompare(y.account_group_name) || x.name.localeCompare(y.name)),
    [categories],
  );

  useEffect(() => {
    setError('');
    if (!request) {
      setInitial(null);
      return;
    }
    if (request.ruleId == null) {
      setInitial(request.draft || {});
      return;
    }
    setInitial(null);
    api
      .get(request.ruleId)
      .then(setInitial)
      .catch((e) => setError(e.message || gettext('Could not load the rule.')));
  }, [request, api]);

  if (!request) return null;
  if (error) {
    return (
      <div className="toast toast-end z-50" data-testid="rule-dialog-error">
        <div className="alert alert-error">
          <span>{error}</span>
          <button type="button" className="btn btn-ghost btn-xs" onClick={onClose}>
            {gettext('Close')}
          </button>
        </div>
      </div>
    );
  }
  if (!initial) return null;

  return (
    <RuleBuilder
      open
      initial={initial}
      onClose={onClose}
      api={api}
      bookBase={bookBase}
      categories={categories}
      feedAccounts={feedAccounts}
      canEdit={canEdit}
      onSaved={onSaved}
      onDeleted={onDeleted || (() => onSaved(null, { deleted: true }))}
    />
  );
}

/** Words a bank sticks on every description, never worth matching on. */
const FILLER = new Set(['ach', 'pos', 'debit', 'credit', 'purchase', 'payment', 'card', 'pmt', 'web', 'id', 'ref']);

/**
 * A starting point for a rule from one feed row: its payee (or the distinctive
 * part of its description), its direction, and its category if it has one. The
 * builder's Test panel shows at once what that would catch; the user narrows it.
 */
export function draftFromRow(row) {
  if (!row) return {};
  const amount = Number(row.outflow) > 0 ? 1 : Number(row.inflow) > 0 ? -1 : Number(row.amount) || 0;
  const payee = (row.payee ?? row.merchant_name ?? '').trim();
  const words = (row.description || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
    .split(' ')
    .filter(Boolean);
  while (words.length && (/^\d+$/.test(words[0]) || FILLER.has(words[0]))) words.shift();
  while (words.length && (/^\d+$/.test(words[words.length - 1]) || FILLER.has(words[words.length - 1]))) words.pop();
  const text = payee || words.join(' ');
  const category = row.category?.id ?? null;
  return {
    name: text ? text.replace(/\b\w/g, (c) => c.toUpperCase()).slice(0, 100) : '',
    direction: amount > 0 ? 'out' : amount < 0 ? 'in' : 'any',
    conditions: text ? [{ field: payee ? 'payee' : 'description', op: 'contains', value: text }] : undefined,
    action: 'category',
    category,
  };
}
