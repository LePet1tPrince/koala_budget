import React, { useEffect, useState } from 'react';
import Icon from '../../common/Icon';
import { formatCurrency } from '../../utilities/currency';
import { formatDate as formatDateUtc } from '../utils';

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

/**
 * "See scheduled transactions": a collapsible strip above the feed table listing
 * the recurring schedules of the accounts on show, each by its next occurrence.
 *
 * Hidden when those accounts have none. `refreshKey` changes when the caller
 * adds a recurring transaction, so the list re-reads.
 */
const ScheduledTransactions = ({ client, book, accountIds, showAccount, refreshKey }) => {
  const [rules, setRules] = useState([]);
  const [open, setOpen] = useState(readOpen);
  const accountParam = accountIds.join(',');

  useEffect(() => {
    let cancelled = false;
    client
      .bankFeedRecurringList({ ...book.params, ...(accountParam ? { account: accountParam } : {}) })
      .then((data) => {
        if (!cancelled) setRules(data);
      })
      .catch((err) => console.error('Failed to load scheduled transactions:', err));
    return () => {
      cancelled = true;
    };
  }, [client, book, accountParam, refreshKey]);

  if (rules.length === 0) return null;

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
        <span className="badge badge-ghost badge-sm">{rules.length}</span>
      </button>

      {open && (
        <div id="scheduled-transactions-panel" className="border-t border-base-300">
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
                      {rule.isSplit ? (
                        gettext('Split')
                      ) : rule.category ? (
                        rule.category.name
                      ) : (
                        <span className="text-base-content/70">{gettext('Uncategorized')}</span>
                      )}
                    </td>
                    <td className="text-base-content/70">
                      {rule.schedule}
                      {rule.endDate && ` · ${interpolate(gettext('until %s'), [formatDateUtc(rule.endDate)])}`}
                    </td>
                    <td className="text-right money">
                      {parseFloat(rule.inflow) > 0 ? formatCurrency(rule.inflow) : ''}
                    </td>
                    <td className="text-right money">
                      {parseFloat(rule.outflow) > 0 ? formatCurrency(rule.outflow) : ''}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="border-t border-base-300 px-3 py-2 text-xs text-base-content/70">
            {gettext('Each is added to the feed on its date.')}{' '}
            <a className="link link-primary" href={`${book.base}bankfeed/recurring/`}>
              {gettext('Manage recurring transactions')}
            </a>
          </div>
        </div>
      )}
    </div>
  );
};

export default ScheduledTransactions;
