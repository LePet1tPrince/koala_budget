/* globals gettext */

import React from 'react';

import Icon from '../common/Icon';

/**
 * The accounts, with the type we inferred and the evidence for it.
 *
 * A YNAB export says nothing about whether an account is something you own or
 * something you owe, so every type here is a guess -- a good one, measured on a
 * real export, but a guess. Showing the reason next to it is what makes the guess
 * checkable rather than something the user has to take on trust.
 */
const money = (value) =>
  `$${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const Step2Accounts = ({ accounts, groups, choices, onChange }) => {
  const choiceFor = (account) => choices[account.name] || {};

  const update = (account, patch) => onChange({ ...choices, [account.name]: { ...choiceFor(account), ...patch } });

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-semibold tracking-tight">{gettext('Your accounts')}</h2>
        <p className="mt-2 max-w-prose text-base-content/70">
          {gettext(
            'YNAB does not export whether an account is an asset or a debt, so we worked it out from the balances. Change anything that looks wrong, and untick anything you would rather not bring over.',
          )}
        </p>
      </div>

      <div className="app-surface overflow-x-auto">
        <table className="table table-sm table-quiet" data-testid="ynab-accounts-table">
          <thead>
            <tr>
              <th>{gettext('Account')}</th>
              <th>{gettext('Type')}</th>
              <th>{gettext('Group')}</th>
              <th className="text-right">{gettext('Transactions')}</th>
              <th className="text-right">{gettext('Balance')}</th>
              <th className="text-center">{gettext('Import')}</th>
            </tr>
          </thead>
          <tbody>
            {accounts.map((account) => {
              const choice = choiceFor(account);
              const skip = Boolean(choice.skip);
              return (
                <tr
                  key={account.name}
                  className={skip ? 'opacity-50' : ''}
                  data-testid="ynab-account-row"
                  // The name is in an input's value, which no text locator can see.
                  data-account={account.name}
                >
                  <td className="whitespace-nowrap">
                    <input
                      type="text"
                      className="input input-bordered input-sm w-48"
                      value={choice.name ?? account.name}
                      onChange={(e) => update(account, { name: e.target.value })}
                      aria-label={gettext('Account name')}
                    />
                    <div className="mt-1 text-xs text-base-content/70">
                      {account.on_budget ? gettext('Everyday account') : gettext('Tracking account')}
                      {' · '}
                      {account.reason}
                    </div>
                  </td>
                  <td>
                    <select
                      className="select select-bordered select-sm"
                      value={choice.account_type ?? account.account_type}
                      onChange={(e) => update(account, { account_type: e.target.value })}
                      aria-label={gettext('Account type')}
                    >
                      <option value="asset">{gettext('Something you own')}</option>
                      <option value="liability">{gettext('Something you owe')}</option>
                    </select>
                  </td>
                  <td>
                    <input
                      type="text"
                      className="input input-bordered input-sm w-40"
                      list="ynab-groups"
                      value={choice.group ?? account.group}
                      onChange={(e) => update(account, { group: e.target.value })}
                      aria-label={gettext('Account group')}
                    />
                  </td>
                  <td className="money text-right">{account.rows.toLocaleString()}</td>
                  <td className="money text-right">{money(account.closing_balance)}</td>
                  <td className="text-center">
                    <input
                      type="checkbox"
                      className="checkbox checkbox-sm rounded-sm"
                      checked={!skip}
                      onChange={(e) => update(account, { skip: !e.target.checked })}
                      aria-label={gettext('Import this account')}
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <datalist id="ynab-groups">
          {groups.map((group) => (
            <option key={group} value={group} />
          ))}
        </datalist>
      </div>

      <p className="flex items-start gap-2 text-sm text-base-content/70">
        <Icon name="info" className="mt-0.5 h-4 w-4 shrink-0" />
        {gettext(
          'Dropping an account also drops its transactions. Anything that was transferred to it will still be recorded, against a bookkeeping account.',
        )}
      </p>
    </div>
  );
};

export default Step2Accounts;
