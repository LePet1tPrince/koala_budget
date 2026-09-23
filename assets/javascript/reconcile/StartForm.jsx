import React, { useState } from 'react';

import DateField from '../common/DateField';
import { formatMoney, sanitizeAmount } from '../common/amount';
import { formatDate, labelsFor } from './labels';

/* globals gettext, interpolate */

/**
 * Step one: which statement. The balance is typed exactly as printed; the
 * server converts it to ledger sign (a card's "owed" is a credit balance).
 */
const StartForm = ({ account, defaultDate, previous, reconciledBalance, preselectCount, onStart, busy, error }) => {
  const labels = labelsFor(account);
  const [statementDate, setStatementDate] = useState(defaultDate);
  const [balance, setBalance] = useState('');
  const parsed = sanitizeAmount(balance);

  const submit = (e) => {
    e.preventDefault();
    if (parsed === null || !statementDate) return;
    onStart(statementDate, parsed);
  };

  return (
    <form className="app-card max-w-xl" onSubmit={submit} data-testid="reconcile-start-form">
      <h2 className="text-lg font-semibold mb-1">{gettext('Start with your statement')}</h2>
      <p className="text-sm text-base-content/70 mb-4">
        {gettext('Enter the closing date and balance from the statement, then tick each transaction that appears on it.')}
      </p>

      <div className="space-y-4">
        <DateField
          label={gettext('Statement date')}
          value={statementDate}
          onChange={setStatementDate}
          testId="statement-date"
        />

        <label className="form-control w-full">
          <span className="label-text mb-1 block text-sm text-base-content/70">{labels.balance}</span>
          <input
            type="text"
            inputMode="decimal"
            className={`input input-bordered w-full money ${balance && parsed === null ? 'input-error' : ''}`}
            value={balance}
            onChange={(e) => setBalance(e.target.value)}
            placeholder="0.00"
            data-testid="statement-balance"
            autoFocus
          />
          <span className="mt-1 block text-xs text-base-content/70">{labels.balanceHelp}</span>
        </label>

        <p className="text-sm" data-testid="reconcile-starting-from">
          {previous
            ? interpolate(gettext('Starting from %s — your %s statement.'), [
                formatMoney(reconciledBalance),
                formatDate(previous.statement_date),
              ])
            : interpolate(gettext('Starting from %s — the transactions already marked reconciled.'), [
                formatMoney(reconciledBalance),
              ])}
        </p>

        {preselectCount > 0 && (
          <p className="text-sm text-base-content/70">
            {interpolate(gettext('%s transaction(s) you selected in the bank feed will start ticked.'), [
              preselectCount,
            ])}
          </p>
        )}

        {error && (
          <div role="alert" className="alert alert-error text-sm" data-testid="reconcile-start-error">
            {error}
          </div>
        )}

        <button
          type="submit"
          className="btn btn-primary"
          disabled={busy || parsed === null || !statementDate}
          data-testid="reconcile-start-btn"
        >
          {busy ? <span className="loading loading-spinner loading-sm" /> : null}
          {gettext('Start reconciling')}
        </button>
      </div>
    </form>
  );
};

export default StartForm;
