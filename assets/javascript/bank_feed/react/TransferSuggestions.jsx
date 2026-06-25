/* globals gettext */

import React, { useCallback, useEffect, useState } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
} from '@mui/material';
import { formatCurrency } from '../../utilities/currency';

/**
 * TransferSuggestions
 *
 * A notification button (with a count badge) that opens a modal for reviewing
 * likely-duplicate transfers — a single movement of money between two of the
 * user's own accounts that both banks reported, so it appears in the feed twice.
 *
 * In the modal the user reviews each pair and either archives one leg (keeping a
 * single journal entry, so balances aren't double-counted) or dismisses it as
 * not a duplicate. Nothing is auto-applied — the user is always in control.
 *
 * Props:
 *   batchApi     - object from getBatchOperationsApi (transferSuggestions/Resolve/Dismiss)
 *   onResolved   - optional callback fired after a pair is resolved/dismissed
 *   showSnackbar - optional (message, severity) => void
 */
const TransferSuggestions = ({ batchApi, onResolved, showSnackbar }) => {
  const [suggestions, setSuggestions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
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

  const count = suggestions.length;

  // Nothing to review and nothing in flight: render no button at all.
  if ((loading || count === 0) && !open) {
    return null;
  }

  const renderLeg = (leg, direction) => (
    <div className="rounded-lg border border-base-300 bg-base-100 p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-base-content/60">{leg.account?.name}</span>
        {leg.is_reconciled && (
          <span className="badge badge-info badge-sm" title={gettext('Reconciled')}>
            <i className="fa fa-lock mr-1"></i>
            {gettext('Reconciled')}
          </span>
        )}
      </div>
      <div className="font-medium">
        {direction === 'out'
          ? `- ${formatCurrency(leg.outflow)}`
          : `+ ${formatCurrency(leg.inflow)}`}
      </div>
      <div className="text-xs text-base-content/60">
        {leg.posted_date}
        {leg.journal_entry_id ? ` · ${gettext('categorized')}` : ''}
      </div>
      {leg.payee && (
        <div className="text-xs text-base-content/80 mt-1">
          <span className="text-base-content/50">{gettext('Payee:')}</span> {leg.payee}
        </div>
      )}
      {leg.description && (
        <div className="text-xs text-base-content/80 truncate" title={leg.description}>
          <span className="text-base-content/50">{gettext('Memo:')}</span> {leg.description}
        </div>
      )}
    </div>
  );

  return (
    <>
      <button
        type="button"
        className="btn btn-sm btn-outline btn-warning"
        onClick={() => setOpen(true)}
        data-testid="transfer-review-button"
        aria-label={gettext('Review possible duplicate transfers')}
      >
        <i className="fa fa-exchange mr-2"></i>
        {gettext('Review transfers')}
        <span className="badge badge-warning badge-sm ml-2">{count}</span>
      </button>

      <Dialog open={open} onClose={() => setOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>
          {gettext('Possible duplicate transfers')}
          {count > 0 ? ` (${count})` : ''}
        </DialogTitle>
        <DialogContent dividers>
          <p className="text-xs text-base-content/60 mb-4">
            {gettext(
              'These look like two sides of the same transfer between your accounts. Archive the duplicate to avoid double-counting, then categorize the one you keep as a transfer.',
            )}
          </p>

          {count === 0 ? (
            <div className="text-center text-base-content/60 py-8">
              <i className="fa fa-check-circle text-success text-2xl mb-2"></i>
              <p>{gettext('All transfers reviewed.')}</p>
            </div>
          ) : (
            <div className="space-y-3">
              {suggestions.map((pair) => {
                const busy = busyKey === pairKey(pair);
                const outReconciled = pair.outflow.is_reconciled;
                const inReconciled = pair.inflow.is_reconciled;
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

                    {(outReconciled || inReconciled) && (
                      <p className="text-xs text-info mt-2">
                        <i className="fa fa-lock mr-1"></i>
                        {gettext(
                          'A reconciled leg cannot be archived — unreconcile it first if it really is a duplicate.',
                        )}
                      </p>
                    )}

                    <div className="flex flex-wrap gap-2 mt-3 justify-end">
                      <button
                        className="btn btn-sm btn-outline btn-error"
                        disabled={busy || outReconciled}
                        title={outReconciled ? gettext('This leg is reconciled') : undefined}
                        onClick={() => handleArchive(pair, pair.outflow, pair.inflow)}
                      >
                        {gettext('Duplicate — archive')} {pair.outflow.account?.name}
                      </button>
                      <button
                        className="btn btn-sm btn-outline btn-error"
                        disabled={busy || inReconciled}
                        title={inReconciled ? gettext('This leg is reconciled') : undefined}
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
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>{gettext('Close')}</Button>
        </DialogActions>
      </Dialog>
    </>
  );
};

export default TransferSuggestions;
