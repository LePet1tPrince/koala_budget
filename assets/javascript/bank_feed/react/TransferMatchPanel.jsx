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
        {gettext(
          'This looks like one transfer between your accounts, reported by both banks. Matching keeps one copy so it is counted once.',
        )}
      </p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        <Leg leg={self} title={gettext('This transaction')} kept={ready && keepsThis} archived={ready && !keepsThis} />
        <Leg
          leg={other}
          title={interpolate(gettext('Other side in %s'), [otherAccount])}
          note={
            pair.date_gap_days > 0
              ? interpolate(
                  ngettext('%s day apart', '%s days apart', pair.date_gap_days),
                  [pair.date_gap_days],
                )
              : gettext('Same day')
          }
          kept={ready && !keepsThis}
          archived={ready && keepsThis}
          testId="transfer-match-counterpart"
        />
      </div>

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

/** One leg of the pair, as a compact card. */
const Leg = ({ leg, title, note, kept, archived, testId }) => {
  const inflow = Number(leg.inflow) > 0;
  const amount = inflow ? leg.inflow : leg.outflow;
  const category = leg.is_split
    ? interpolate(gettext('Split (%s)'), [leg.split_count])
    : leg.category?.name || gettext('Uncategorized');
  return (
    <div
      className={`rounded-lg border bg-base-100 p-2.5 text-sm ${archived ? 'border-base-300 opacity-70' : 'border-base-300'}`}
      data-testid={testId}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-base-content/70 truncate">{title}</span>
        {kept && <span className="badge badge-success badge-soft badge-xs">{gettext('Kept')}</span>}
        {archived && <span className="badge badge-ghost badge-xs">{gettext('Archived')}</span>}
      </div>
      <div className="flex items-baseline justify-between gap-2 mt-1">
        <span className="money font-semibold">
          {inflow ? '+' : '−'}
          {formatCurrency(amount)}
        </span>
        <span className="text-xs text-base-content/70 tabular-nums">
          {formatDate(leg.posted_date)}
          {note ? ` · ${note}` : ''}
        </span>
      </div>
      {leg.payee && <div className="truncate" title={leg.payee}>{leg.payee}</div>}
      {leg.description && (
        <div className="text-xs text-base-content/70 truncate" title={leg.description}>
          {leg.description}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-1 mt-1">
        <span className={`badge badge-xs ${leg.category || leg.is_split ? 'badge-ghost' : 'badge-outline'}`}>
          {category}
        </span>
        {leg.is_reconciled && (
          <span className="badge badge-info badge-soft badge-xs gap-1">
            <Icon name="lock" className="w-3 h-3" />
            {gettext('Reconciled')}
          </span>
        )}
      </div>
    </div>
  );
};

export default TransferMatchPanel;
