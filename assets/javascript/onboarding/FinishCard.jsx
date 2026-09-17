/* globals gettext */

import React, { useEffect } from 'react';

import { fireConfetti } from '../common/confetti';

/**
 * Phase E: the walkthrough is done.
 *
 * Shows the user their own numbers rather than a slogan — the accounts they
 * built, the transactions they imported, the net worth they anchored. That is
 * the whole argument for having done this.
 *
 * Reuses the shared confetti module the Goals page already fires, so the app has
 * one celebration rather than two that look slightly different.
 */

const money = (value) => {
  const amount = Number(value) || 0;
  const sign = amount < 0 ? '-' : '';
  return `${sign}$${Math.abs(amount).toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  })}`;
};

const FinishCard = ({ summary, onClose }) => {
  useEffect(() => {
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    if (!reduced) {
      // 'cannons' — two streams from the bottom corners. The shared module's
      // only other named origin is 'sky'; anything else is read as a {x, y}
      // point, so a made-up string would silently produce NaN positions.
      fireConfetti({ origin: 'cannons' });
    }
  }, []);

  return (
    <div className="onboarding-backdrop is-open" data-testid="onboarding-finish">
      <div className="onboarding-panel app-card" role="dialog" aria-modal="true">
        <h2 className="text-[1.75rem] font-semibold tracking-tight">{gettext('Your books are set up')}</h2>
        <p className="mt-2 text-base-content/70">
          {gettext(
            'Everything from here is just keeping it current — import, categorize, and the reports look after themselves.',
          )}
        </p>

        {summary && (
          <div className="finish-stats">
            <div>
              <p className="finish-stat">{summary.accounts}</p>
              <p className="finish-stat-label">{gettext('accounts')}</p>
            </div>
            <div>
              <p className="finish-stat">{summary.transactions}</p>
              <p className="finish-stat-label">{gettext('transactions')}</p>
            </div>
            <div>
              <p className="finish-stat money">{money(summary.net_worth)}</p>
              <p className="finish-stat-label">{gettext('net worth')}</p>
            </div>
          </div>
        )}

        <div className="mt-7 flex justify-end">
          <button type="button" className="btn btn-primary" onClick={onClose} data-testid="finish-close">
            {gettext('Done')}
          </button>
        </div>
      </div>
    </div>
  );
};

export default FinishCard;
