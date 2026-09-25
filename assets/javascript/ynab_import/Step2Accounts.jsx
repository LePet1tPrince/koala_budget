/* globals gettext */

import React, { useMemo } from 'react';

import Icon from '../common/Icon';
import ChipSelect from './ChipSelect';
import NameBank from './NameBank';
import {
  editsAfterAdd,
  editsAfterRemove,
  editsAfterRename,
  EMPTY_EDITS,
  listNames,
  resolveNewName,
  resolveRename,
} from './names';

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

const TYPES = [
  { key: 'asset', label: gettext('Things you own') },
  { key: 'liability', label: gettext('Things you owe') },
];

const TAKEN_BY_OTHER_TYPE = {
  asset: gettext('That name is already a group for things you owe.'),
  liability: gettext('That name is already a group for things you own.'),
};

const otherType = (type) => (type === 'asset' ? 'liability' : 'asset');

const Step2Accounts = ({ accounts, groups, choices, onChange, groupEdits, onGroupEditsChange }) => {
  const choiceFor = (account) => choices[account.name] || {};
  const typeOf = (account) => choiceFor(account).account_type ?? account.account_type;
  const groupOf = (account) => choiceFor(account).group ?? account.group;

  const update = (account, patch) => onChange({ ...choices, [account.name]: { ...choiceFor(account), ...patch } });

  const editsFor = (type) => groupEdits[type] || EMPTY_EDITS;
  const setEdits = (type, edits) => onGroupEditsChange({ ...groupEdits, [type]: edits });

  // A group holds one type of account, as it does in the app, so each type has its
  // own list: the suggested groups first (as renamed), then the ones the user
  // added, then any other a row is in.
  const groupsByType = useMemo(() => {
    const byType = {};
    TYPES.forEach(({ key }) => {
      const suggested = groups.filter((group) => group.account_type === key).map((group) => group.name);
      const inUse = accounts.filter((account) => typeOf(account) === key).map(groupOf);
      byType[key] = listNames(suggested, inUse, editsFor(key));
    });
    return byType;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groups, accounts, choices, groupEdits]);

  // Counted over the accounts being imported; an unticked row still holds its
  // group, so it keeps a group the user added from being removed under it.
  const { counts, held } = useMemo(() => {
    const tally = { asset: {}, liability: {} };
    const inUse = new Set();
    accounts.forEach((account) => {
      inUse.add(groupOf(account));
      if (choiceFor(account).skip) return;
      const bucket = tally[typeOf(account)];
      bucket[groupOf(account)] = (bucket[groupOf(account)] || 0) + 1;
    });
    return { counts: tally, held: inUse };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accounts, choices]);

  const createGroup = (type, raw) => {
    const result = resolveNewName(groupsByType[type], raw, {
      taken: groupsByType[otherType(type)],
      takenMessage: TAKEN_BY_OTHER_TYPE[type],
    });
    if (result.created) setEdits(type, editsAfterAdd(editsFor(type), result.name));
    return result;
  };

  // Every account of `type` in group `from` -- skipped ones too, so a group
  // renamed or emptied is not held by a row that is not being imported.
  const moveAccounts = (type, from, to) => {
    const next = { ...choices };
    accounts.forEach((account) => {
      if (typeOf(account) === type && groupOf(account) === from) {
        next[account.name] = { ...choiceFor(account), group: to };
      }
    });
    onChange(next);
  };

  const renameGroup = (type, from, raw) => {
    const result = resolveRename(groupsByType[type], from, raw, {
      taken: groupsByType[otherType(type)],
      takenMessage: TAKEN_BY_OTHER_TYPE[type],
    });
    if (result.error) return result.error;
    if (result.unchanged) return null;
    moveAccounts(type, from, result.name);
    setEdits(type, editsAfterRename(editsFor(type), from, result.name, result.merged));
    return null;
  };

  // Retyping an account moves it out of a group that no longer fits: back to the
  // group we suggested if it is returning to its suggested type, otherwise into
  // the first group of the new type.
  const setType = (account, type) => {
    const group = account.account_type === type ? account.group : groupsByType[type][0];
    update(account, { account_type: type, group });
  };

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

      <section className="space-y-3 rounded-box border border-base-300 p-4" data-testid="ynab-group-bank">
        <div>
          <h3 className="font-semibold">{gettext('Account groups')}</h3>
          <p className="mt-1 text-sm text-base-content/70">
            {gettext(
              'Every account goes in one of these. Add a group with + here or from any row’s group menu, and it is offered on every row. Click a group to rename it or move all its accounts to another.',
            )}
          </p>
        </div>
        {TYPES.map((type) => (
          <NameBank
            key={type.key}
            label={type.label}
            names={groupsByType[type.key]}
            counts={counts[type.key]}
            removable={groupsByType[type.key].filter((name) => !held.has(name))}
            onRemove={(name) => setEdits(type.key, editsAfterRemove(editsFor(type.key), name))}
            onAdd={(raw) => createGroup(type.key, raw).error}
            onRename={(name, raw) => renameGroup(type.key, name, raw)}
            onReassign={(name, target) => moveAccounts(type.key, name, target)}
            addLabel={gettext('New group')}
            addPlaceholder={gettext('Group name')}
            testId={`ynab-groups-${type.key}`}
          />
        ))}
      </section>

      <div className="app-surface overflow-x-auto">
        <table className="table table-sm table-quiet" data-testid="ynab-accounts-table">
          <thead>
            <tr>
              <th>{gettext('Account')}</th>
              <th>{gettext('Type')}</th>
              <th>{gettext('Group')}</th>
              <th className="text-right">{gettext('Transactions')}</th>
              <th className="text-right">{gettext('Balance')}</th>
              <th className="text-center">{gettext('In Inbox')}</th>
              <th className="text-center">{gettext('Import')}</th>
            </tr>
          </thead>
          <tbody>
            {accounts.map((account) => {
              const choice = choiceFor(account);
              const skip = Boolean(choice.skip);
              const hasFeed = choice.has_feed ?? account.has_feed;
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
                      className="select select-bordered select-sm w-48"
                      value={typeOf(account)}
                      onChange={(e) => setType(account, e.target.value)}
                      aria-label={gettext('Account type')}
                    >
                      <option value="asset">{gettext('Something you own')}</option>
                      <option value="liability">{gettext('Something you owe')}</option>
                    </select>
                  </td>
                  <td>
                    <ChipSelect
                      value={groupOf(account)}
                      options={groupsByType[typeOf(account)]}
                      onChange={(group) => update(account, { group })}
                      onCreate={(raw) => createGroup(typeOf(account), raw)}
                      createLabel={gettext('New group')}
                      createPlaceholder={gettext('Group name')}
                      ariaLabel={gettext('Account group')}
                      testId="ynab-account-group"
                    />
                  </td>
                  <td className="money text-right">{account.rows.toLocaleString()}</td>
                  <td className="money text-right">{money(account.closing_balance)}</td>
                  <td className="text-center">
                    <input
                      type="checkbox"
                      className="checkbox checkbox-sm rounded-sm"
                      checked={hasFeed && !skip}
                      disabled={skip}
                      onChange={(e) => update(account, { has_feed: e.target.checked })}
                      aria-label={gettext('Show this account’s transactions in the Inbox')}
                      data-testid="ynab-account-feed"
                    />
                  </td>
                  <td className="text-center">
                    <input
                      type="checkbox"
                      className="checkbox checkbox-sm rounded-sm"
                      checked={!skip}
                      onChange={(e) => update(account, { skip: !e.target.checked })}
                      aria-label={gettext('Import this account')}
                      data-testid="ynab-account-import"
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="flex items-start gap-2 text-sm text-base-content/70">
        <Icon name="info" className="mt-0.5 h-4 w-4 shrink-0" />
        {gettext(
          'An account in the Inbox gets its own feed with every transaction from YNAB, ready to reconcile against your statements. Tracking accounts and accounts emptied over a year ago start without one.',
        )}
      </p>

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
