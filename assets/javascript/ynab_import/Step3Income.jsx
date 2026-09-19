/* globals gettext */

import React, { useMemo } from 'react';

import Icon from '../common/Icon';

/**
 * Where each inflow came from.
 *
 * YNAB gives every deposit the one category `Inflow: Ready to Assign`, so the only
 * thing in the export that says what money *was* is who paid it. This screen turns
 * that into income accounts: the counts and totals are shown because they are the
 * evidence -- a payee seen 351 times is a salary, one seen once is not.
 */
const money = (value) =>
  `$${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const Step3Income = ({ income, suggestions, choices, onChange }) => {
  const choiceFor = (row) => choices[row.payee] || {};
  const update = (row, patch) => onChange({ ...choices, [row.payee]: { ...choiceFor(row), ...patch } });

  const accounts = useMemo(() => {
    const names = new Set(suggestions);
    income.forEach((row) => {
      const chosen = (choices[row.payee] || {}).account;
      if (chosen) names.add(chosen);
    });
    return [...names].sort();
  }, [income, suggestions, choices]);

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-semibold tracking-tight">{gettext('Where your money came from')}</h2>
        <p className="mt-2 max-w-prose text-base-content/70">
          {gettext(
            'YNAB does not categorise income, so we grouped your deposits by who paid you. Give two payees the same account name to merge them, or mark a payee as “not income” if it was a correction rather than earnings.',
          )}
        </p>
      </div>

      <div className="app-surface overflow-x-auto">
        <table className="table table-sm table-quiet" data-testid="ynab-income-table">
          <thead>
            <tr>
              <th>{gettext('Paid by')}</th>
              <th className="text-right">{gettext('Deposits')}</th>
              <th className="text-right">{gettext('Total')}</th>
              <th>{gettext('Counts as')}</th>
              <th>{gettext('Income account')}</th>
            </tr>
          </thead>
          <tbody>
            {income.map((row) => {
              const choice = choiceFor(row);
              const kind = choice.kind ?? row.kind;
              return (
                <tr key={row.payee} data-testid="ynab-income-row" data-payee={row.payee}>
                  <td className="whitespace-nowrap">{row.label}</td>
                  <td className="money text-right">{row.count.toLocaleString()}</td>
                  <td className="money text-right">{money(row.total)}</td>
                  <td>
                    <select
                      className="select select-bordered select-sm"
                      value={kind}
                      onChange={(e) => update(row, { kind: e.target.value })}
                      aria-label={gettext('Counts as')}
                    >
                      <option value="income">{gettext('Income')}</option>
                      <option value="not_income">{gettext('Not income')}</option>
                    </select>
                  </td>
                  <td>
                    {kind === 'income' ? (
                      <input
                        type="text"
                        className="input input-bordered input-sm w-52"
                        list="ynab-income-accounts"
                        value={choice.account ?? row.account}
                        onChange={(e) => update(row, { account: e.target.value })}
                        aria-label={gettext('Income account')}
                      />
                    ) : (
                      <span className="text-sm text-base-content/70">{gettext('Bookkeeping adjustment')}</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <datalist id="ynab-income-accounts">
          {accounts.map((name) => (
            <option key={name} value={name} />
          ))}
        </datalist>
      </div>

      <p className="flex items-start gap-2 text-sm text-base-content/70">
        <Icon name="info" className="mt-0.5 h-4 w-4 shrink-0" />
        {gettext('Each income account gets a budget equal to what it actually earned, month by month.')}
      </p>
    </div>
  );
};

export default Step3Income;
