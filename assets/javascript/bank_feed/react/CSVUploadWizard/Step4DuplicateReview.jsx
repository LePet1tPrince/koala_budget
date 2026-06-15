/* globals gettext */

import React, { useState } from 'react';

/**
 * Step4DuplicateReview - Let the user decide which potential duplicates to include
 *
 * Props:
 * - duplicates: Array of transactions flagged as potential duplicates
 * - excludedRows: Set of row_numbers the user has chosen to exclude
 * - onExcludedRowsChange: Callback(newSet) when exclusions change
 * - onContinue: Callback to proceed to next step
 * - onBack: Callback to go back
 * - onCancel: Callback when user cancels
 */
const Step4DuplicateReview = ({
  duplicates,
  excludedRows,
  onExcludedRowsChange,
  onContinue,
  onBack,
  onCancel,
}) => {
  const toggleRow = (rowNumber) => {
    const next = new Set(excludedRows);
    if (next.has(rowNumber)) {
      next.delete(rowNumber);
    } else {
      next.add(rowNumber);
    }
    onExcludedRowsChange(next);
  };

  const includeAll = () => onExcludedRowsChange(new Set());
  const excludeAll = () => onExcludedRowsChange(new Set(duplicates.map((tx) => tx.row_number)));

  const includedCount = duplicates.length - excludedRows.size;

  const formatAmount = (amount) => {
    if (amount === null || amount === undefined) return '-';
    const num = parseFloat(amount);
    const formatted = Math.abs(num).toFixed(2);
    if (num < 0) {
      return <span className="text-success">+${formatted}</span>;
    }
    return <span className="text-error">-${formatted}</span>;
  };

  return (
    <div className="space-y-4">
      <div className="alert alert-warning">
        <i className="fa fa-exclamation-triangle"></i>
        <div>
          <p className="font-semibold">
            {duplicates.length} {gettext('potential duplicate(s) found')}
          </p>
          <p className="text-sm">
            {gettext(
              'These transactions match existing records by date, amount, and description. Review each one and uncheck any you want to skip. All are included by default.'
            )}
          </p>
        </div>
      </div>

      {/* Bulk actions */}
      <div className="flex gap-2 justify-end">
        <button className="btn btn-xs btn-ghost" onClick={includeAll}>
          {gettext('Include all')}
        </button>
        <button className="btn btn-xs btn-ghost" onClick={excludeAll}>
          {gettext('Exclude all')}
        </button>
      </div>

      <div className="overflow-x-auto max-h-80">
        <table className="table table-xs table-zebra table-pin-rows">
          <thead>
            <tr>
              <th className="w-12">{gettext('Include')}</th>
              <th>{gettext('Date')}</th>
              <th>{gettext('Description')}</th>
              <th>{gettext('Amount')}</th>
              <th>{gettext('Category')}</th>
            </tr>
          </thead>
          <tbody>
            {duplicates.map((tx) => {
              const excluded = excludedRows.has(tx.row_number);
              return (
                <tr
                  key={tx.row_number}
                  className={excluded ? 'opacity-40' : ''}
                >
                  <td>
                    <input
                      type="checkbox"
                      className="checkbox checkbox-sm checkbox-warning"
                      checked={!excluded}
                      onChange={() => toggleRow(tx.row_number)}
                    />
                  </td>
                  <td>{tx.date || '-'}</td>
                  <td className="max-w-64 truncate">{tx.description || '-'}</td>
                  <td>{formatAmount(tx.amount)}</td>
                  <td>
                    {tx.matched_category_id ? (
                      <span className="badge badge-success badge-xs">{tx.category}</span>
                    ) : tx.category ? (
                      <span className="badge badge-warning badge-xs">{tx.category}</span>
                    ) : (
                      <span className="text-base-content/50">-</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="text-sm text-base-content/70">
        <i className="fa fa-info-circle mr-1"></i>
        {includedCount} {gettext('of')} {duplicates.length}{' '}
        {gettext('potential duplicate(s) will be imported')}
      </p>

      <div className="modal-action">
        <button className="btn btn-ghost" onClick={onCancel}>
          {gettext('Cancel')}
        </button>
        <button className="btn btn-ghost" onClick={onBack}>
          {gettext('Back')}
        </button>
        <button className="btn btn-primary" onClick={onContinue}>
          {gettext('Continue')}
          <i className="fa fa-arrow-right ml-2"></i>
        </button>
      </div>
    </div>
  );
};

export default Step4DuplicateReview;
