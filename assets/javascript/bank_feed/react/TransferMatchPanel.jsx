/* globals gettext, ngettext, interpolate */

import React, { useEffect, useRef, useState } from 'react';

import Icon from '../../common/Icon';
import { formatCurrency } from '../../utilities/currency';
import { formatDate } from '../utils';

/**
 * Inline review of a possible duplicate transfer, rendered under its feed row.
 *
 * A transfer between two of the user's own accounts is reported by both banks,
 * so it lands in the feed twice. This shows the other side of the pair and what
 * Match will do -- which leg it keeps and archives is decided by the server
 * (`proposal`), so the sentence here is what the click does.
 *
 * Props:
 *   match      - {pair, self, other}: the suggestion and its two legs (snake_case rows)
 *   onMatch    - (match) => Promise; keep one leg, archive the other
 *   onDismiss  - (match) => Promise; not the same transfer
 *   onGoTo     - (match) => void; open the other leg in its own feed
 *   onClose    - () => void
 */
const TransferMatchPanel = ({ id, match, onMatch, onDismiss, onGoTo, onClose }) => {
  const [busy, setBusy] = useState(false);
  const panelRef = useRef(null);
  const { pair, self, other } = match;
  const proposal = pair.proposal || {};
  const ready = proposal.status === 'ready';
  const keepsThis = proposal.keep_id === self.imported_transaction_id;
  const otherAccount = other.account?.name || gettext('the other account');

  // Opening the panel puts focus in it, so a keyboard user lands on Match (or,
  // when Match is unavailable, on the first thing they can do instead).
  useEffect(() => {
    const panel = panelRef.current;
    (panel?.querySelector('[data-testid="transfer-match-btn"]:not([disabled])') ||
      panel?.querySelector('button:not([disabled])'))?.focus({ preventScroll: true });
  }, []);

  const run = async (action) => {
    setBusy(true);
    try {
      await action(match);
    } finally {
      // The panel unmounts once the pair is gone; only reset if it is still here.
      if (panelRef.current) setBusy(false);
    }
  };

  const outcome = keepsThis
    ? interpolate(gettext('Match keeps this transaction and archives the one in %s'), [otherAccount])
    : interpolate(gettext('Match keeps the one in %s and archives this transaction'), [otherAccount]);

  return (
    <div
      id={id}
      ref={panelRef}
      role="region"
      aria-label={gettext('Possible transfer')}
      className="rounded-box border border-warning/40 bg-warning/5 p-3 space-y-3 whitespace-normal"
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          e.stopPropagation();
          onClose();
        }
      }}
      data-testid="transfer-match-panel"
    >
      <p className="text-sm">
        {gettext('Both banks seem to have reported the same transfer. Matching keeps one copy so it is counted once.')}
      </p>

      <Comparison
        self={self}
        other={other}
        dateGap={pair.date_gap_days}
        keep={ready ? (keepsThis ? 'self' : 'other') : null}
      />

      {ready ? (
        <p className="text-sm" data-testid="transfer-match-outcome">
          {outcome} — {proposal.message}
        </p>
      ) : (
        <p className="text-sm text-warning flex items-start gap-1" data-testid="transfer-match-blocked">
          <Icon name="lock" className="inline-block shrink-0 w-4 h-4 mt-0.5" />
          <span>{proposal.message}</span>
        </p>
      )}

      <div className="flex flex-wrap gap-2 justify-end">
        <button type="button" className="btn btn-sm btn-ghost" disabled={busy} onClick={() => onGoTo(match)}>
          <Icon name="arrow-right-left" className="w-4 h-4" />
          {gettext('Go to other side')}
        </button>
        <button
          type="button"
          className="btn btn-sm btn-outline"
          disabled={busy}
          onClick={() => run(onDismiss)}
          data-testid="transfer-dismiss-btn"
        >
          {gettext('Not a match')}
        </button>
        <button
          type="button"
          className="btn btn-sm btn-primary"
          disabled={busy || !ready}
          onClick={() => run(onMatch)}
          data-testid="transfer-match-btn"
        >
          {busy && <span className="loading loading-spinner loading-xs" />}
          {gettext('Match')}
        </button>
      </div>
    </div>
  );
};

/**
 * What a leg's category says, read from this pair's point of view: a leg already
 * categorized to the other leg's account is that transfer, so it says so
 * ("Transfer to Savings") rather than just naming the account.
 */
const categoryText = (leg, counterpart) => {
  if (leg.is_split) return interpolate(gettext('Split (%s)'), [leg.split_count]);
  if (!leg.category) return gettext('Uncategorized');
  if (leg.category.id === counterpart.account?.id) {
    const outflow = Number(leg.outflow) > 0;
    return interpolate(outflow ? gettext('Transfer to %s') : gettext('Transfer from %s'), [leg.category.name]);
  }
  return leg.category.name;
};

const amountText = (leg) =>
  Number(leg.inflow) > 0
    ? interpolate(gettext('%s in'), [formatCurrency(leg.inflow)])
    : interpolate(gettext('%s out'), [formatCurrency(leg.outflow)]);

/**
 * The two legs side by side, one row per attribute, so a difference (dates two
 * days apart, one side categorized and the other not) reads across a single line.
 * The first column is the row the panel opened under; the second the other bank's.
 */
const Comparison = ({ self, other, dateGap, keep }) => {
  const sides = [
    { key: 'self', leg: self, counterpart: other },
    { key: 'other', leg: other, counterpart: self },
  ];
  const gapNote =
    dateGap > 0
      ? interpolate(ngettext('%s day later', '%s days later', dateGap), [dateGap])
      : gettext('same day');
  // The later of the two dates carries the gap ("2 days later"); on the same day
  // the other side says so.
  const laterKey = other.posted_date > self.posted_date ? 'other' : 'self';

  const rows = [
    {
      label: gettext('Date'),
      render: (s) => (
        <>
          <span className="tabular-nums whitespace-nowrap">{formatDate(s.leg.posted_date)}</span>
          {(dateGap > 0 ? s.key === laterKey : s.key === 'other') && (
            <span className="block text-xs text-base-content/70">{gapNote}</span>
          )}
        </>
      ),
    },
    { label: gettext('Amount'), render: (s) => <span className="money">{amountText(s.leg)}</span> },
    {
      label: gettext('Category'),
      render: (s) => {
        const uncategorized = !s.leg.category && !s.leg.is_split;
        return (
          <span className={uncategorized ? 'italic text-base-content/70' : ''}>
            {categoryText(s.leg, s.counterpart)}
          </span>
        );
      },
    },
    { label: gettext('Payee'), render: (s) => s.leg.payee || <span className="text-base-content/70">—</span> },
    {
      label: gettext('Description'),
      render: (s) => <span className="break-words">{s.leg.description || '—'}</span>,
    },
    {
      label: gettext('Reconciled'),
      render: (s) =>
        s.leg.is_reconciled ? (
          <span className="inline-flex items-center gap-1 text-info">
            <Icon name="lock" className="w-3.5 h-3.5" />
            {gettext('Yes')}
          </span>
        ) : (
          <span className="text-base-content/70">{gettext('No')}</span>
        ),
    },
  ];

  return (
    <div className="rounded-lg border border-base-300 bg-base-100 overflow-hidden">
      <table className="w-full table-fixed text-xs sm:text-sm" data-testid="transfer-match-comparison">
        <caption className="sr-only">{gettext('The two transactions compared')}</caption>
        <colgroup>
          <col className="w-[4.75rem] sm:w-28" />
          <col />
          <col />
        </colgroup>
        <thead>
          <tr className="border-b border-base-300">
            <td />
            {sides.map((s) => (
              <th
                key={s.key}
                scope="col"
                // Explicit colour and size: this table sits inside a feed-table cell,
                // whose header styles would otherwise reach these cells and grey them.
                className="px-1.5 sm:px-3 py-2 text-left align-top font-semibold text-sm text-base-content normal-case whitespace-normal"
                data-testid={s.key === 'other' ? 'transfer-match-counterpart' : undefined}
              >
                <span className="block break-words">{s.leg.account?.name}</span>
                <span className="flex flex-wrap items-center gap-1 mt-0.5 font-normal">
                  {s.key === 'self' && (
                    <span className="text-xs text-base-content/70">{gettext('This row')}</span>
                  )}
                  {keep === s.key && (
                    <span className="badge badge-success badge-soft badge-xs">{gettext('Kept')}</span>
                  )}
                  {keep && keep !== s.key && (
                    <span className="badge badge-ghost badge-xs">{gettext('Archived')}</span>
                  )}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label} className="border-b border-base-300 last:border-b-0">
              <th
                scope="row"
                className="px-1.5 sm:px-3 py-1.5 text-left align-top text-xs font-medium text-base-content/70 normal-case whitespace-normal"
              >
                {row.label}
              </th>
              {sides.map((s) => (
                <td
                  key={s.key}
                  className="px-1.5 sm:px-3 py-1.5 align-top break-words whitespace-normal"
                  data-testid={s.key === 'other' ? 'transfer-match-counterpart' : undefined}
                >
                  {row.render(s)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

export default TransferMatchPanel;
