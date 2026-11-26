/* globals gettext, interpolate, ngettext */
import React, { useEffect, useRef } from 'react';

import { createConfetti } from '../../../common/confetti';
import { formatMoney } from '../../../common/amount';

function Confetti() {
  const canvasRef = useRef(null);
  useEffect(() => {
    if (!canvasRef.current) return undefined;
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return undefined;
    return createConfetti(canvasRef.current, { origin: 'sky' });
  }, []);
  return <canvas ref={canvasRef} className="fixed inset-0 pointer-events-none" style={{ zIndex: 9999 }} />;
}

const duration = (ms) => {
  const s = Math.max(0, Math.round(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
};

/**
 * The end of the queue: what this session did, the skipped pile if there is
 * one, and the way back. Nothing to file: says so (the header's scope bar widens it).
 */
export default function Summary({ session, pileCount, scoped, onReviewPile, onExit, exitLabel }) {
  const did = session.filed > 0;
  return (
    <div className="min-h-[60vh] flex items-center justify-center p-4">
      {did && pileCount === 0 && <Confetti />}
      <div className="card bg-base-100 shadow-xl p-8 text-center max-w-md w-full" data-testid="categorize-summary">
        <div className="text-6xl mb-3" aria-hidden="true">
          {pileCount > 0 ? '🗂️' : did ? '🎉' : '✅'}
        </div>
        <h2 className="text-2xl font-black mb-2">
          {pileCount > 0 ? gettext('Almost there') : did ? gettext('All sorted!') : gettext('Nothing to categorize')}
        </h2>
        {did ? (
          <dl className="grid grid-cols-3 gap-2 my-3" data-testid="categorize-summary-stats">
            <div>
              <dt className="text-xs text-base-content/70">{gettext('Sorted')}</dt>
              <dd className="text-xl font-black" data-testid="categorize-summary-count">
                {session.filed}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-base-content/70">{gettext('Worth')}</dt>
              <dd className="text-xl font-black">{formatMoney(session.amount)}</dd>
            </div>
            <div>
              <dt className="text-xs text-base-content/70">{gettext('Time')}</dt>
              <dd className="text-xl font-black">{duration(session.lastAt - session.startedAt)}</dd>
            </div>
          </dl>
        ) : pileCount > 0 ? null : (
          <p className="text-base-content/70 mb-2" data-testid="categorize-empty-message">
            {scoped
              ? gettext('No uncategorized transactions in this account and date range.')
              : gettext('All your transactions are already categorized.')}
          </p>
        )}
        {session.rules > 0 && (
          <p className="text-sm text-base-content/70 mb-2" data-testid="categorize-summary-rules">
            {interpolate(
              ngettext(
                '%s new rule will suggest these next time.',
                '%s new rules will suggest these next time.',
                session.rules,
              ),
              [session.rules],
            )}
          </p>
        )}
        {!did && pileCount === 0 && scoped && (
          <p className="text-sm text-base-content/70 mb-4">
            {gettext('Widen the account or dates above to see more.')}
          </p>
        )}
        {pileCount > 0 && (
          <button
            type="button"
            className="btn btn-primary mb-2"
            onClick={onReviewPile}
            data-testid="categorize-review-pile"
          >
            {interpolate(ngettext('Review %s skipped', 'Review %s skipped', pileCount), [pileCount])}
          </button>
        )}
        <button
          type="button"
          className={`btn ${pileCount > 0 ? 'btn-ghost' : 'btn-primary'}`}
          onClick={onExit}
          data-testid="categorize-exit"
        >
          ← {exitLabel}
        </button>
      </div>
    </div>
  );
}
