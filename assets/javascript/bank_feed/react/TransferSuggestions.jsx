/* globals gettext */

import React, { useCallback, useEffect, useState } from 'react';
import { formatCurrency } from '../../utilities/currency';

/**
 * TransferSuggestions
 *
 * Surfaces likely-duplicate transfers — a single movement of money between two
 * of the user's own accounts that both banks reported, so it appears in the feed
 * twice. The user reviews each pair and either archives one leg (keeping a single
 * journal entry, so balances aren't double-counted) or dismisses it as not a
 * duplicate. Nothing is auto-applied — the user is always in control.
 *
 * Props:
 *   batchApi     - object from getBatchOperationsApi (transferSuggestions/Resolve/Dismiss)
 *   onResolved   - optional callback fired after a pair is resolved/dismissed
 *   showSnackbar - optional (message, severity) => void
 */
const TransferSuggestions = ({ batchApi, onResolved, showSnackbar }) => {
  const [suggestions, setSuggestions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busyKey, setBusyKey] = useState(null);

  const pairKey = (pair) =>
    `${pair.outflow.imported_transaction_id}-${pair.inflow.imported_transaction_id}`;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await batchApi.transferSuggestions();
      setSuggestions(Array.isArray(data) ? data : []);
    } catch (e) {
      // A failed load shouldn't break the page; just show nothing.
      setSuggestions([]);
    } finally {
      setLoading(false);
    }
  }, [batchApi]);

  useEffect(() => {
    load();
  }, [load]);

  const notify = (message, severity) => {
    if (showSnackbar) showSnackbar(message, severity);
  };

  const afterChange = (pair) => {
    setSuggestions((prev) => prev.filter((p) => pairKey(p) !== pairKey(pair)));
    if (onResolved) onResolved();
  };

  const handleArchive = async (pair, archiveLeg, keepLeg) => {
    setBusyKey(pairKey(pair));
    try {
      await batchApi.transferResolve(
        archiveLeg.imported_transaction_id,
        keepLeg.imported_transaction_id,
      );
      notify(gettext('Duplicate transfer archived.'), 'success');
      afterChange(pair);
    } catch (e) {
      notify(e.message || gettext('Could not archive transaction.'), 'error');
    } finally {
      setBusyKey(null);
    }
  };

  const handleDismiss = async (pair) => {
    setBusyKey(pairKey(pair));
    try {
      await batchApi.transferDismiss(
        pair.outflow.imported_transaction_id,
        pair.inflow.imported_transaction_id,
      );
      notify(gettext('Marked as not a duplicate.'), 'info');
      afterChange(pair);
    } catch (e) {
      notify(e.message || gettext('Could not dismiss suggestion.'), 'error');
    } finally {
      setBusyKey(null);
    }
  };

  // Hide the panel entirely when there's nothing to review.
  if (loading || suggestions.length === 0) {
    return null;
  }

  const renderLeg = (leg, direction) => (
    <div className="rounded-lg border border-base-300 bg-base-100 p-3">
      <div className="text-xs text-base-content/60">{leg.account?.name}</div>
      <div className="font-medium">
        {direction === 'out'
          ? `- ${formatCurrency(leg.outflow)}`
          : `+ ${formatCurrency(leg.inflow)}`}
      </div>
      <div className="text-xs text-base-content/60">
        {leg.posted_date}
        {leg.journal_entry_id ? ` · ${gettext('categorized')}` : ''}
      </div>
    </div>
  );

  return (
    <section className="app-card border-l-4 border-warning">
      <div className="flex items-center gap-2 mb-1">
        <i className="fa fa-exchange text-warning"></i>
        <h2 className="pg-subtitle">{gettext('Possible duplicate transfers')}</h2>
        <span className="badge badge-warning badge-sm">{suggestions.length}</span>
      </div>
      <p className="text-xs text-base-content/60 mb-4">
        {gettext(
          'These look like two sides of the same transfer between your accounts. Archive the duplicate to avoid double-counting, then categorize the one you keep as a transfer.',
        )}
      </p>

      <div className="space-y-3">
        {suggestions.map((pair) => {
          const busy = busyKey === pairKey(pair);
          return (
            <div
              key={pairKey(pair)}
              className="rounded-lg bg-base-200 p-3"
              data-testid={`transfer-suggestion-${pairKey(pair)}`}
            >
              <div className="grid grid-cols-1 md:grid-cols-[1fr_auto_1fr] gap-3 items-center">
                {renderLeg(pair.outflow, 'out')}
                <div className="text-center text-base-content/40">
                  <i className="fa fa-arrow-right"></i>
                </div>
                {renderLeg(pair.inflow, 'in')}
              </div>

              <div className="flex flex-wrap gap-2 mt-3 justify-end">
                <button
                  className="btn btn-sm btn-outline btn-error"
                  disabled={busy}
                  onClick={() => handleArchive(pair, pair.outflow, pair.inflow)}
                >
                  {gettext('Duplicate — archive')} {pair.outflow.account?.name}
                </button>
                <button
                  className="btn btn-sm btn-outline btn-error"
                  disabled={busy}
                  onClick={() => handleArchive(pair, pair.inflow, pair.outflow)}
                >
                  {gettext('Duplicate — archive')} {pair.inflow.account?.name}
                </button>
                <button
                  className="btn btn-sm btn-ghost"
                  disabled={busy}
                  onClick={() => handleDismiss(pair)}
                >
                  {gettext('Not a duplicate')}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
};

export default TransferSuggestions;
