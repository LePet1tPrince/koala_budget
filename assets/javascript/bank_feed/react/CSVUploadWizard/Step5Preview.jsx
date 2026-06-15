/* globals gettext */

import React, { useMemo, useState } from 'react';

/**
 * Step5Preview - Final preview and confirmation before import
 *
 * Props:
 * - transactions: Array of parsed transactions
 * - errorCount: Number of rows with errors
 * - excludedDuplicateRows: Set of row_numbers the user excluded in the duplicate review step
 * - onConfirm: Callback to confirm import
 * - onBack: Callback to go back
 * - onCancel: Callback when user cancels
 */
const Step5Preview = ({
  transactions,
  errorCount,
  excludedDuplicateRows,
  onConfirm,
  onBack,
  onCancel,
}) => {
  const [loading, setLoading] = useState(false);
  const [skippedRows, setSkippedRows] = useState(new Set());

  const isExcluded = (tx) =>
    excludedDuplicateRows.has(tx.row_number) || skippedRows.has(tx.row_number);

  // Calculate summary stats (all valid rows, ignoring exclusions)
  const { validCount, categorizedCount, uncategorizedCount } = useMemo(() => {
    let valid = 0;
    let categorized = 0;
    let uncategorized = 0;
    transactions.forEach((tx) => {
      if (!tx.error && tx.date && tx.amount !== null) {
        valid++;
        if (tx.matched_category_id) categorized++;
        else uncategorized++;
      }
    });
    return { validCount: valid, categorizedCount: categorized, uncategorizedCount: uncategorized };
  }, [transactions]);

  // Exact counts after applying all exclusions
  const { importCount, autoCategorizedCount } = useMemo(() => {
    let importable = 0;
    let categorized = 0;
    transactions.forEach((tx) => {
      if (tx.error || !tx.date || tx.amount === null) return;
      if (isExcluded(tx)) return;
      importable++;
      if (tx.matched_category_id) categorized++;
    });
    return { importCount: importable, autoCategorizedCount: categorized };
  }, [transactions, excludedDuplicateRows, skippedRows]);

  const toggleSkipRow = (rowNumber) => {
    setSkippedRows((prev) => {
      const next = new Set(prev);
      if (next.has(rowNumber)) next.delete(rowNumber);
      else next.add(rowNumber);
      return next;
    });
  };

  const handleConfirm = async () => {
    setLoading(true);

    const transactionsToImport = transactions
      .filter((tx) => {
        if (tx.error) return false;
        if (!tx.date || tx.amount === null) return false;
        if (isExcluded(tx)) return false;
        return true;
      })
      .map((tx) => ({
        date: tx.date,
        description: tx.description || '',
        payee: tx.payee,
        amount: tx.amount,
        category_id: tx.matched_category_id,
        skip: false,
      }));

    await onConfirm(transactionsToImport);
    setLoading(false);
  };

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
    <div className="space-y-6">
      {/* Summary Stats */}
      <div className="stats stats-horizontal shadow w-full">
        <div className="stat">
          <div className="stat-title">{gettext('Valid')}</div>
          <div className="stat-value text-primary">{validCount}</div>
        </div>
        <div className="stat">
          <div className="stat-title">{gettext('Categorized')}</div>
          <div className="stat-value text-success">{categorizedCount}</div>
        </div>
        <div className="stat">
          <div className="stat-title">{gettext('Uncategorized')}</div>
          <div className="stat-value text-warning">{uncategorizedCount}</div>
        </div>
        {errorCount > 0 && (
          <div className="stat">
            <div className="stat-title">{gettext('Errors')}</div>
            <div className="stat-value text-error">{errorCount}</div>
          </div>
        )}
      </div>

      {/* Error Summary */}
      {errorCount > 0 && (
        <div className="alert alert-error">
          <i className="fa fa-times-circle"></i>
          <span>
            {errorCount} {gettext('row(s) have errors and will be skipped')}
          </span>
        </div>
      )}

      {/* Transaction Preview Table */}
      <div className="overflow-x-auto max-h-64">
        <table className="table table-xs table-zebra table-pin-rows">
          <thead>
            <tr>
              <th className="w-12"></th>
              <th>{gettext('Row')}</th>
              <th>{gettext('Date')}</th>
              <th>{gettext('Description')}</th>
              <th>{gettext('Amount')}</th>
              <th>{gettext('Category')}</th>
              <th>{gettext('Status')}</th>
            </tr>
          </thead>
          <tbody>
            {transactions.map((tx) => {
              const manuallySkipped = skippedRows.has(tx.row_number);
              const dupExcluded = excludedDuplicateRows.has(tx.row_number);
              const hasError = !!tx.error;
              const isDuplicate = tx.is_potential_duplicate;
              const excluded = manuallySkipped || dupExcluded;

              return (
                <tr
                  key={tx.row_number}
                  className={`${hasError ? 'bg-error/10' : ''} ${excluded ? 'opacity-40' : ''}`}
                >
                  <td>
                    {!hasError && !dupExcluded && (
                      <input
                        type="checkbox"
                        className="checkbox checkbox-xs"
                        checked={!manuallySkipped}
                        onChange={() => toggleSkipRow(tx.row_number)}
                      />
                    )}
                  </td>
                  <td>{tx.row_number}</td>
                  <td>{tx.date || '-'}</td>
                  <td className="max-w-48 truncate">{tx.description || '-'}</td>
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
                  <td>
                    {hasError ? (
                      <span className="badge badge-error badge-xs" title={tx.error}>
                        {gettext('Error')}
                      </span>
                    ) : dupExcluded ? (
                      <span className="badge badge-ghost badge-xs">
                        {gettext('Excluded')}
                      </span>
                    ) : isDuplicate ? (
                      <span className="badge badge-warning badge-xs">
                        {gettext('Duplicate')}
                      </span>
                    ) : (
                      <span className="badge badge-success badge-xs">
                        {gettext('OK')}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Import Summary */}
      <div className="text-sm text-base-content/70">
        <i className="fa fa-info-circle mr-2"></i>
        {importCount}{' '}
        {gettext('transactions will be imported')}
        {autoCategorizedCount > 0 && (
          <span>
            {' ('}
            {autoCategorizedCount} {gettext('will be auto-categorized')}
            {')'}
          </span>
        )}
      </div>

      <div className="modal-action">
        <button
          className="btn btn-ghost"
          onClick={onCancel}
          disabled={loading}
        >
          {gettext('Cancel')}
        </button>
        <button
          className="btn btn-ghost"
          onClick={onBack}
          disabled={loading}
        >
          {gettext('Back')}
        </button>
        <button
          className="btn btn-primary"
          onClick={handleConfirm}
          disabled={loading || validCount === 0}
        >
          {loading ? (
            <>
              <span className="loading loading-spinner loading-sm"></span>
              {gettext('Importing...')}
            </>
          ) : (
            <>
              <i className="fa fa-upload mr-2"></i>
              {gettext('Import Transactions')}
            </>
          )}
        </button>
      </div>
    </div>
  );
};

export default Step5Preview;
