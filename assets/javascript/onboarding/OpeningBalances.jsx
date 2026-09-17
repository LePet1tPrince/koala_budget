/* globals gettext */

import React, { useCallback, useEffect, useState } from 'react';

/**
 * The opening-balance step, and the net-worth reveal that follows it.
 *
 * Net worth is derived from journal activity, so a ledger holding only an imported
 * window reports the *change* over that window rather than what the user has. This
 * is where that gap gets closed — and the before/after pair is the point: the
 * number they have been squinting at moves to the one they recognise.
 *
 * Asked here rather than during the questionnaire because "what is the balance of
 * each of these accounts" is a wall of numbers before anything has been seen to
 * work. After importing and categorizing, it is the obvious answer to "why does
 * this say I'm worth $42?".
 */

/*
  Matches the `currency` template filter the rest of the app formats with:
  "$1,234.50", "-$3.00". `Intl` with `style: 'currency'` renders CAD as "CA$" in
  most locales, which would make this one number look foreign on a page where
  every other figure says "$".
*/
const money = (value) => {
  const amount = Number(value) || 0;
  const sign = amount < 0 ? '-' : '';
  return `${sign}$${Math.abs(amount).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
};

const useCountUp = (from, to, ms = 700) => {
  const [value, setValue] = useState(from);

  useEffect(() => {
    if (from === null || to === null) return undefined;

    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    if (reduced) {
      setValue(to);
      return undefined;
    }

    let raf;
    const start = performance.now();
    const step = (now) => {
      const t = Math.min(1, (now - start) / ms);
      // Ease-out, so it decelerates into the final figure rather than stopping dead.
      setValue(from + (to - from) * (1 - (1 - t) ** 3));
      if (t < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [from, to, ms]);

  return value;
};

const Reveal = ({ before, after, onClose, reportUrl }) => {
  const shown = useCountUp(before, after);

  return (
    <div data-testid="net-worth-reveal">
      <h3 className="text-xl font-semibold tracking-tight">{gettext('There it is')}</h3>
      <p className="mt-1 text-sm text-base-content/70">
        {gettext('Your net worth — everything you own, minus everything you owe.')}
      </p>

      <p className="money mt-6 text-center text-[2.5rem] font-semibold tracking-tight" data-testid="net-worth-figure">
        {money(shown)}
      </p>
      <p className="mt-1 text-center text-sm text-base-content/70">
        {gettext('was {before}').replace('{before}', money(before))}
      </p>

      <div className="mt-7 flex flex-wrap justify-end gap-2">
        <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>
          {gettext('Close')}
        </button>
        <a href={reportUrl} className="btn btn-primary btn-sm">
          {gettext('See it over time')}
        </a>
      </div>
    </div>
  );
};

const OpeningBalances = ({ url, reportUrl, csrf, onClose, onSaved }) => {
  const [accounts, setAccounts] = useState(null);
  const [amounts, setAmounts] = useState({});
  const [before, setBefore] = useState(null);
  const [after, setAfter] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch(url, { headers: { Accept: 'application/json' } })
      .then((r) => r.json())
      .then((data) => {
        if (!data.allowed) {
          setError(data.error);
          setAccounts([]);
          return;
        }
        setAccounts(data.accounts);
        setBefore(Number(data.net_worth));
      })
      .catch(() => setError(gettext('Could not load your accounts.')));
  }, [url]);

  const save = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
        body: JSON.stringify({
          rows: Object.entries(amounts).map(([id, amount]) => ({ account_id: Number(id), amount })),
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        setError(data.error || gettext('Could not save those balances.'));
        return;
      }
      setBefore(Number(data.net_worth_before));
      setAfter(Number(data.net_worth));
      onSaved?.();
    } catch {
      setError(gettext('Could not save those balances.'));
    } finally {
      setBusy(false);
    }
  }, [url, csrf, amounts, onSaved]);

  const assets = (accounts || []).filter((a) => a.type === 'asset');
  const debts = (accounts || []).filter((a) => a.type === 'liability');

  const row = (account) => (
    <label key={account.id} className="opening-row">
      <span className="min-w-0">
        <span className="block truncate text-sm">{account.name}</span>
        <span className="block text-xs text-base-content/70">{account.group}</span>
      </span>
      {account.has_opening_balance ? (
        <span className="text-xs text-base-content/70">{gettext('already set')}</span>
      ) : (
        <span className="flex items-center gap-1">
          <span className="text-base-content/70">$</span>
          <input
            type="number"
            inputMode="decimal"
            min="0"
            step="0.01"
            className="input input-bordered input-sm money w-28 text-right"
            placeholder="0"
            value={amounts[account.id] ?? ''}
            onChange={(e) => setAmounts((prev) => ({ ...prev, [account.id]: e.target.value }))}
            data-testid={`opening-${account.id}`}
          />
        </span>
      )}
    </label>
  );

  return (
    <div className="onboarding-backdrop is-open" data-testid="opening-balances">
      <div className="onboarding-panel app-card" role="dialog" aria-modal="true">
        {after !== null ? (
          <Reveal before={before} after={after} onClose={onClose} reportUrl={reportUrl} />
        ) : (
          <>
            <h3 className="text-xl font-semibold tracking-tight">{gettext('What do you already have?')}</h3>
            <p className="mt-1 text-sm text-base-content/70">
              {gettext(
                'Koala only knows about what you imported. Fill in today’s balances and your net worth will be the real one. Skip anything you’re not sure about.',
              )}
            </p>

            {error && (
              <div className="alert alert-error mt-4" data-testid="opening-error">
                <span>{error}</span>
              </div>
            )}

            {accounts === null ? (
              <div className="mt-5 space-y-2">
                <div className="skeleton h-10 w-full"></div>
                <div className="skeleton h-10 w-full"></div>
              </div>
            ) : (
              <div className="opening-scroll mt-5">
                {assets.length > 0 && (
                  <section>
                    <h4 className="opening-heading">{gettext('What you own')}</h4>
                    {assets.map(row)}
                  </section>
                )}
                {debts.length > 0 && (
                  <section className="mt-4">
                    <h4 className="opening-heading">{gettext('What you owe')}</h4>
                    <p className="mb-1 text-xs text-base-content/70">
                      {gettext('Enter what you owe as a positive number.')}
                    </p>
                    {debts.map(row)}
                  </section>
                )}
              </div>
            )}

            <div className="onboarding-actions">
              <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>
                {gettext('I’ll do this later')}
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={save}
                disabled={busy || accounts === null}
                data-testid="opening-save"
              >
                {busy && <span className="loading loading-spinner loading-xs"></span>}
                {gettext('Save and see my net worth')}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default OpeningBalances;
