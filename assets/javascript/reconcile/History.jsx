import React from 'react';

import { formatMoney } from '../common/amount';
import { formatDate } from './labels';

/* globals gettext */

/**
 * Every finished statement for the account. Any one of them can be undone
 * (plan D6): its transactions are unreconciled but keep their link, so the next
 * session's drift banner can say where they came from.
 */
const History = ({ history, onUndo, busyId }) => (
  <section className="app-card" data-testid="reconcile-history">
    <h2 className="text-lg font-semibold mb-2">{gettext('Statement history')}</h2>
    {history.length === 0 ? (
      <p className="text-sm text-base-content/70">{gettext('No statements reconciled yet.')}</p>
    ) : (
      <div className="overflow-x-auto">
        <table className="table table-sm table-quiet">
          <thead>
            <tr>
              <th>{gettext('Statement date')}</th>
              <th className="text-right">{gettext('Balance')}</th>
              <th className="text-right">{gettext('Adjustment')}</th>
              <th>{gettext('Status')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {history.map((rec) => (
              <tr key={rec.id} data-testid="history-row" data-status={rec.status}>
                <td>
                  <a className="link link-primary" href={rec.url}>
                    {formatDate(rec.statement_date)}
                  </a>
                </td>
                <td className="text-right money">{formatMoney(rec.statement_balance)}</td>
                <td className="text-right money">
                  {Number(rec.adjustment_amount) ? formatMoney(rec.adjustment_amount) : '—'}
                </td>
                <td data-testid="history-status">
                  {rec.status === 'undone' ? (
                    <span className="badge badge-ghost badge-sm">{gettext('Undone')}</span>
                  ) : rec.intact ? (
                    <span className="badge badge-soft badge-success badge-sm">{gettext('Intact')}</span>
                  ) : (
                    <span className="badge badge-soft badge-warning badge-sm">{gettext('Changed')}</span>
                  )}
                </td>
                <td className="text-right">
                  {rec.status === 'completed' && (
                    <button
                      type="button"
                      className="btn btn-ghost btn-xs"
                      onClick={() => onUndo(rec)}
                      disabled={busyId === rec.id}
                      data-testid="history-undo"
                    >
                      {gettext('Undo')}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )}
  </section>
);

export default History;
