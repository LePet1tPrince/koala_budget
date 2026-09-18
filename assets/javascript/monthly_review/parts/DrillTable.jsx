import React, { useState } from 'react';

import { currency } from '../format';

/**
 * The budget breakdown, grouped, with a click-to-unfold transaction list per
 * category. Per the reference implementation note (§4.6 of the plan): the
 * drill-down is a real `<tr><td colSpan>` sibling row, never innerHTML on the
 * row itself (that would parse in row context and mis-nest the inner table).
 */
const DrillTable = ({ groups, catTxns, catAvg, baselineLabel }) => {
  const [openId, setOpenId] = useState(null);
  const colSpan = catAvg ? 7 : 6;

  return (
    <div className="overflow-x-auto">
      <table className="table table-sm table-quiet" data-testid="budget-breakdown-table">
        <thead>
          <tr>
            <th>Group / Category</th>
            <th className="text-right">Assigned</th>
            <th className="text-right">Spent</th>
            <th className="text-right">Last month</th>
            {catAvg && <th className="text-right">vs {baselineLabel}</th>}
            <th className="text-right">Available</th>
            <th className="text-right">Items</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => (
            <React.Fragment key={group.name}>
              <tr className="font-medium bg-base-200/40">
                <td>{group.name}</td>
                <td className="text-right">{currency(group.assigned)}</td>
                <td className="text-right">{currency(group.spent)}</td>
                <td className="text-right">{currency(group.prev)}</td>
                {catAvg && <td />}
                <td className="text-right">{currency(group.available)}</td>
                <td className="text-right">{group.count}</td>
              </tr>
              {group.categories.map((cat) => {
                const isOpen = openId === cat.id;
                const avg = catAvg ? catAvg[cat.id] : null;
                const vsAvg = avg !== null && avg !== undefined ? cat.spent - avg : null;
                const rows = catTxns[cat.id] || [];
                return (
                  <React.Fragment key={cat.id}>
                    <tr
                      className="cursor-pointer hover:bg-base-200/60"
                      onClick={() => setOpenId(isOpen ? null : cat.id)}
                      data-testid={`budget-row-${cat.id}`}
                    >
                      <td className="pl-6">
                        {cat.name}
                        {cat.unbudgeted && <span className="badge badge-ghost badge-sm ml-2">unbudgeted</span>}
                      </td>
                      <td className="text-right">{currency(cat.assigned)}</td>
                      <td className="text-right">{currency(cat.spent)}</td>
                      <td className="text-right">{currency(cat.prev)}</td>
                      {catAvg && (
                        <td className={`text-right ${vsAvg > 0 ? 'text-error' : vsAvg < 0 ? 'text-success' : ''}`}>
                          {vsAvg === null ? '—' : currency(vsAvg)}
                        </td>
                      )}
                      <td className="text-right">{currency(cat.available)}</td>
                      <td className="text-right">{cat.count}</td>
                    </tr>
                    {isOpen && (
                      <tr data-testid={`budget-row-${cat.id}-drill`}>
                        <td colSpan={colSpan} className="bg-base-200/30 p-0">
                          <table className="table table-xs w-full">
                            <thead>
                              <tr>
                                <th>Date</th>
                                <th>Payee</th>
                                <th>Memo</th>
                                <th>Account</th>
                                <th className="text-right">Amount</th>
                              </tr>
                            </thead>
                            <tbody>
                              {rows.map((tx, i) => (
                                <tr key={i}>
                                  <td>{tx.date}</td>
                                  <td>{tx.payee}</td>
                                  <td>{tx.memo}</td>
                                  <td>{tx.account}</td>
                                  <td className="text-right">{currency(tx.amount)}</td>
                                </tr>
                              ))}
                              {!rows.length && (
                                <tr>
                                  <td colSpan={5} className="text-base-content/60">
                                    No transactions this month.
                                  </td>
                                </tr>
                              )}
                            </tbody>
                          </table>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </React.Fragment>
          ))}
          {!groups.length && (
            <tr>
              <td colSpan={colSpan} className="text-base-content/60">
                Nothing budgeted or spent this month.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
};

export default DrillTable;
