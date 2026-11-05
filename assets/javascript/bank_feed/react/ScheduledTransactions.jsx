import React, { useCallback, useEffect, useState } from 'react';
import Icon from '../../common/Icon';
import { formatCurrency } from '../../utilities/currency';
import { formatDate as formatDateUtc } from '../utils';
import MakeRecurringModal from './MakeRecurringModal';

/* globals gettext, interpolate */

const STORAGE_KEY = 'bankFeed.scheduledOpen';

const readOpen = () => {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === '1';
  } catch {
    return false;
  }
};

const writeOpen = (open) => {
  try {
    window.localStorage.setItem(STORAGE_KEY, open ? '1' : '0');
  } catch {
    // Storage blocked (private window): the panel just forgets.
  }
};

const money = (value) => (parseFloat(value) > 0 ? formatCurrency(value) : '');

const CategoryCell = ({ row }) => {
  if (row.isSplit) return gettext('Split');
  if (row.category) return row.category.name;
  return <span className="text-base-content/70">{gettext('Uncategorized')}</span>;
};

/**
 * "See scheduled transactions": a collapsible strip above the feed table for the
 * accounts on show. It lists their recurring schedules by next occurrence, and
 * the runs of transactions that look recurring but have none ("Possible
 * recurring"), each with Make recurring (a popup, `MakeRecurringModal`) and
 * Not recurring.
 *
 * Hidden when there is neither. `refreshKey` changes when the caller adds a
 * recurring transaction; `onScheduleCreated(rule)` tells it one was made here.
 */
const ScheduledTransactions = ({ client, book, accountIds, showAccount, refreshKey, onScheduleCreated }) => {
  const [rules, setRules] = useState([]);
  const [suggestions, setSuggestions] = useState([]);
  const [open, setOpen] = useState(readOpen);
  const [accepting, setAccepting] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  const accountParam = accountIds.join(',');

  useEffect(() => {
    let cancelled = false;
    const params = { ...book.params, ...(accountParam ? { account: accountParam } : {}) };
    client
      .bankFeedRecurringList(params)
      .then((data) => !cancelled && setRules(data))
      .catch((err) => console.error('Failed to load scheduled transactions:', err));
    client
      .bankFeedRecurringSuggestions(params)
      .then((data) => !cancelled && setSuggestions(data))
      .catch((err) => console.error('Failed to load recurring suggestions:', err));
    return () => {
      cancelled = true;
    };
  }, [client, book, accountParam, refreshKey, reloadKey]);

  const dismiss = useCallback(
    async (suggestion) => {
      setSuggestions((current) => current.filter((s) => s.key !== suggestion.key));
      try {
        await client.bankFeedRecurringDismissSuggestion({ ...book.params, dismissSuggestion: { key: suggestion.key } });
      } catch (err) {
        console.error('Failed to dismiss suggestion:', err);
        setReloadKey((n) => n + 1);
      }
    },
    [client, book],
  );

  const created = (rule) => {
    setAccepting(null);
    setReloadKey((n) => n + 1);
    onScheduleCreated?.(rule);
  };

  if (rules.length === 0 && suggestions.length === 0) return null;

  const toggle = () => {
    setOpen((current) => {
      writeOpen(!current);
      return !current;
    });
  };

  return (
    <div className="app-surface overflow-hidden" data-testid="scheduled-transactions">
      <button
        type="button"
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-base-200"
        onClick={toggle}
        aria-expanded={open}
        aria-controls="scheduled-transactions-panel"
        data-testid="scheduled-toggle"
      >
        <span className={`inline-block transition-transform ${open ? 'rotate-90' : ''}`}>
          <Icon name="chevron-right" className="inline-block h-3.5 w-3.5 shrink-0" />
        </span>
        <Icon name="repeat" className="inline-block h-4 w-4 shrink-0 text-base-content/70" />
        <span className="font-medium">
          {open ? gettext('Hide scheduled transactions') : gettext('See scheduled transactions')}
        </span>
        {rules.length > 0 && <span className="badge badge-ghost badge-sm">{rules.length}</span>}
        {suggestions.length > 0 && (
          <span className="badge badge-soft badge-info badge-sm" data-testid="suggestion-count">
            {interpolate(gettext('%s possible recurring'), [suggestions.length])}
          </span>
        )}
      </button>

      {open && (
        <div id="scheduled-transactions-panel" className="border-t border-base-300">
          {rules.length > 0 && (
            <div className="overflow-x-auto">
              <table className="table table-sm" data-testid="scheduled-table">
                <thead>
                  <tr>
                    <th>{gettext('Next')}</th>
                    {showAccount && <th>{gettext('Account')}</th>}
                    <th>{gettext('Payee')}</th>
                    <th>{gettext('Category')}</th>
                    <th>{gettext('Repeats')}</th>
                    <th className="text-right">{gettext('Inflow')}</th>
                    <th className="text-right">{gettext('Outflow')}</th>
                  </tr>
                </thead>
                <tbody>
                  {rules.map((rule) => (
                    <tr key={rule.id} data-testid="scheduled-row">
                      <td className="whitespace-nowrap">{formatDateUtc(rule.nextDate)}</td>
                      {showAccount && <td>{rule.account?.name}</td>}
                      <td>{rule.payee || rule.description || '—'}</td>
                      <td>
                        <CategoryCell row={rule} />
                      </td>
                      <td className="text-base-content/70">
                        {rule.schedule}
                        {rule.endDate && ` · ${interpolate(gettext('until %s'), [formatDateUtc(rule.endDate)])}`}
                      </td>
                      <td className="text-right money">{money(rule.inflow)}</td>
                      <td className="text-right money">{money(rule.outflow)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {suggestions.length > 0 && (
            <div className={rules.length > 0 ? 'border-t border-base-300' : ''} data-testid="suggestions">
              <div className="px-3 pt-3 text-sm font-medium">{gettext('Possible recurring transactions')}</div>
              <div className="px-3 text-xs text-base-content/70">
                {gettext('These repeat regularly but have no schedule yet.')}
              </div>
              <div className="overflow-x-auto">
                <table className="table table-sm" data-testid="suggestion-table">
                  <thead>
                    <tr>
                      <th>{gettext('Next expected')}</th>
                      {showAccount && <th>{gettext('Account')}</th>}
                      <th>{gettext('Payee')}</th>
                      <th>{gettext('Category')}</th>
                      <th>{gettext('Looks like')}</th>
                      <th className="text-right">{gettext('Inflow')}</th>
                      <th className="text-right">{gettext('Outflow')}</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {suggestions.map((s) => (
                      <tr key={s.key} data-testid="suggestion-row">
                        <td className="whitespace-nowrap">{formatDateUtc(s.nextDate)}</td>
                        {showAccount && <td>{s.account?.name}</td>}
                        <td>{s.payee}</td>
                        <td>
                          <CategoryCell row={s} />
                        </td>
                        <td className="text-base-content/70">
                          {s.schedule}
                          {' · '}
                          {interpolate(gettext('seen %s times'), [s.occurrences])}
                        </td>
                        <td className="text-right money">{money(s.inflow)}</td>
                        <td className="text-right money">{money(s.outflow)}</td>
                        <td className="whitespace-nowrap text-right">
                          <button
                            type="button"
                            className="btn btn-primary btn-xs"
                            onClick={() => setAccepting(s)}
                            data-testid="suggestion-accept"
                          >
                            {gettext('Make recurring')}
                          </button>{' '}
                          <button
                            type="button"
                            className="btn btn-ghost btn-xs"
                            onClick={() => dismiss(s)}
                            data-testid="suggestion-dismiss"
                          >
                            {gettext('Not recurring')}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div className="border-t border-base-300 px-3 py-2 text-xs text-base-content/70">
            {gettext('Each schedule adds its transaction to the feed on its date.')}{' '}
            <a className="link link-primary" href={`${book.base}bankfeed/recurring/`}>
              {gettext('Manage recurring transactions')}
            </a>
          </div>
        </div>
      )}

      <MakeRecurringModal
        suggestion={accepting}
        client={client}
        book={book}
        onClose={() => setAccepting(null)}
        onCreated={created}
      />
    </div>
  );
};

export default ScheduledTransactions;
