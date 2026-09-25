/* globals gettext */

import React, { useMemo } from 'react';

import Icon from '../common/Icon';
import ChipSelect from './ChipSelect';
import NameBank from './NameBank';
import { resolveNewName, withName } from './names';

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

const Step3Income = ({ income, suggestions, otherIncome, choices, onChange, extraAccounts, onExtraAccountsChange }) => {
  const choiceFor = (row) => choices[row.payee] || {};
  const update = (row, patch) => onChange({ ...choices, [row.payee]: { ...choiceFor(row), ...patch } });
  const kindOf = (row) => choiceFor(row).kind ?? row.kind;
  // A payee we suggested as "not income" has no account; switched back to income
  // it lands where the server would put it.
  const accountOf = (row) => choiceFor(row).account || row.account || otherIncome;

  // The suggested accounts, then any a row is in, then the ones the user added.
  const accounts = useMemo(() => {
    let names = [];
    suggestions.forEach((name) => {
      names = withName(names, name);
    });
    income.forEach((row) => {
      if (kindOf(row) === 'income') names = withName(names, accountOf(row));
    });
    extraAccounts.forEach((name) => {
      names = withName(names, name);
    });
    return names;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [income, suggestions, choices, extraAccounts]);

  const counts = useMemo(() => {
    const tally = {};
    income.forEach((row) => {
      if (kindOf(row) !== 'income') return;
      tally[accountOf(row)] = (tally[accountOf(row)] || 0) + 1;
    });
    return tally;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [income, choices]);

  const createAccount = (raw) => {
    const result = resolveNewName(accounts, raw);
    if (result.created) onExtraAccountsChange([...extraAccounts, result.name]);
    return result;
  };

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-semibold tracking-tight">{gettext('Where your money came from')}</h2>
        <p className="mt-2 max-w-prose text-base-content/70">
          {gettext(
            'YNAB does not categorise income, so we grouped your deposits by who paid you. Pick the same income account for two payees to merge them, or mark a payee as “not income” if it was a correction rather than earnings.',
          )}
        </p>
      </div>

      <section className="space-y-3 rounded-box border border-base-300 p-4" data-testid="ynab-income-bank">
        <div>
          <h3 className="font-semibold">{gettext('Income accounts')}</h3>
          <p className="mt-1 text-sm text-base-content/70">
            {gettext(
              'Each payee below goes into one of these. Add an account with + here or from any row’s menu, and it is offered on every row.',
            )}
          </p>
        </div>
        <NameBank
          names={accounts}
          counts={counts}
          removable={extraAccounts.filter((name) => !counts[name])}
          onRemove={(name) => onExtraAccountsChange(extraAccounts.filter((item) => item !== name))}
          onAdd={(raw) => createAccount(raw).error}
          addLabel={gettext('New income account')}
          addPlaceholder={gettext('Account name')}
          testId="ynab-income-accounts"
        />
      </section>

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
              const kind = kindOf(row);
              return (
                <tr key={row.payee} data-testid="ynab-income-row" data-payee={row.payee}>
                  <td className="whitespace-nowrap">{row.label}</td>
                  <td className="money text-right">{row.count.toLocaleString()}</td>
                  <td className="money text-right">{money(row.total)}</td>
                  <td>
                    <select
                      className="select select-bordered select-sm w-36"
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
                      <ChipSelect
                        value={accountOf(row)}
                        options={accounts}
                        onChange={(account) => update(row, { account })}
                        onCreate={createAccount}
                        createLabel={gettext('New income account')}
                        createPlaceholder={gettext('Account name')}
                        ariaLabel={gettext('Income account')}
                        testId="ynab-income-account"
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
      </div>

      <p className="flex items-start gap-2 text-sm text-base-content/70">
        <Icon name="info" className="mt-0.5 h-4 w-4 shrink-0" />
        {gettext('Each income account gets a budget equal to what it actually earned, month by month.')}
      </p>
    </div>
  );
};

export default Step3Income;
