/* globals gettext, interpolate, ngettext */
import { ACCOUNT_KIND_LABELS, accountKind } from '../../../common/accountKind';

/**
 * Category search and the "named in the memo" suggestion, for Categorize Mode.
 * Pure: no React, no requests.
 */

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
 * Rank how well an account matches a search query, higher is better; `null`
 * means no match (the account is left out). The account's own name weighs far
 * more than its group/institution/type: every income account's type contains
 * "income", so searching "income" would otherwise rank them all alike.
 */
export function matchScore(account, query) {
  const q = query.toLowerCase().trim();
  if (!q) return 0;

  const name = (account.name || '').toLowerCase();
  const secondary = [account.account_group_name, account.institution_name, ACCOUNT_KIND_LABELS[accountKind(account)]]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
  const qWords = q.split(/\s+/).filter(Boolean);

  if (name === q) return 100;
  if (name.startsWith(q)) return 90;
  if (name.split(/\s+/).includes(q)) return 85;
  if (name.includes(q)) return 70;
  if (qWords.length > 1 && qWords.every((w) => name.includes(w))) return 60;
  if (secondary.includes(q)) return 40;
  if (qWords.length > 1 && qWords.every((w) => secondary.includes(w))) return 30;
  if (charSequenceMatch(name, q)) return 10;
  return null;
}

function escapeRegExp(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// Whether `needle` appears in `haystack` as a whole token -- an account named
// "BC" doesn't match inside "ABC", nor "AT" inside a memo of "ATM WD".
function containsWholeToken(haystack, needle) {
  if (!needle) return false;
  const re = new RegExp(`(?:^|[^a-z0-9])${escapeRegExp(needle.toLowerCase())}(?:$|[^a-z0-9])`, 'i');
  return re.test(` ${haystack} `);
}

/**
 * The account most clearly named in a transaction's memo/payee -- a transfer
 * memo that says "WS Joint Checking", or just "BBC". The transaction's own feed
 * account is never it: filing a row there would be a transfer to itself.
 */
export function findAccountNamedInText(text, accounts, excludeAccountId) {
  if (!text) return null;
  const candidates = accounts.filter((a) => a.name && a.id !== excludeAccountId);

  // The longest full account name that appears verbatim.
  let fullMatch = null;
  for (const account of candidates) {
    const name = account.name.trim();
    if (containsWholeToken(text, name) && (!fullMatch || name.length > fullMatch.name.trim().length)) {
      fullMatch = account;
    }
  }
  if (fullMatch) return fullMatch;

  // Otherwise the longest single word (3+ chars) of any account name.
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

/**
 * A row's suggestions as the picker shows them: the server's (a rule's, or from
 * similar transactions), with an account named in the memo merged in first, the
 * feed account and unknown accounts dropped, at most `max`.
 */
export function mergeSuggestions(suggestions, row, accounts, accountsById, max) {
  const feedAccountId = row?.account?.id ?? null;
  const known = (suggestions || []).filter((s) => accountsById[s.category_id] && s.category_id !== feedAccountId);
  if (!row || known.some((s) => s.match_type === 'rule')) return known.slice(0, max);

  const memo = [row.description, row.merchant_name].filter(Boolean).join(' ');
  const named = findAccountNamedInText(memo, accounts, feedAccountId);
  if (!named) return known.slice(0, max);
  const already = known.find((s) => s.category_id === named.id);
  return [
    {
      category_id: named.id,
      category_name: named.name,
      count: already ? already.count : null,
      match_type: 'named',
      payee: already ? already.payee : '',
    },
    ...known.filter((s) => s.category_id !== named.id),
  ].slice(0, max);
}

/** The sentence under a suggestion: why it is suggested. */
export function suggestionNote({ count, match_type: matchType, rule_name: ruleName }) {
  if (matchType === 'rule') return interpolate(gettext('Suggested by your rule “%s”'), [ruleName]);
  if (matchType === 'named') {
    return count != null
      ? interpolate(gettext('Named in the memo — also used %s× for this payee'), [count])
      : gettext('Named in the transaction memo');
  }
  if (matchType === 'payee') {
    return interpolate(
      ngettext(
        '%s transaction with this payee was categorized as this',
        '%s transactions with this payee were categorized as this',
        count,
      ),
      [count],
    );
  }
  if (matchType === 'description') {
    return interpolate(
      ngettext(
        '%s transaction with this description was categorized as this',
        '%s transactions with this description were categorized as this',
        count,
      ),
      [count],
    );
  }
  return interpolate(
    ngettext(
      '%s transaction like this one was categorized as this',
      '%s transactions like this one were categorized as this',
      count,
    ),
    [count],
  );
}

/** The few words a chip has room for: "Rule", "3× this payee", "In the memo". */
export function suggestionBadge({ count, match_type: matchType }) {
  if (matchType === 'rule') return gettext('Rule');
  if (matchType === 'named') return gettext('In the memo');
  if (matchType === 'payee') return interpolate(gettext('%s× this payee'), [count]);
  if (matchType === 'description') return interpolate(gettext('%s× this wording'), [count]);
  return interpolate(gettext('%s× similar'), [count]);
}
