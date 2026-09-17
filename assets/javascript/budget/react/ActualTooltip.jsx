import React, { useState, useMemo, useEffect } from 'react';
import PickerPopover from '../../common/PickerPopover';
import Spinner from '../../common/Spinner';
import { Toast } from '../../common/Toast';
import Cookies from 'js-cookie';
import { formatCurrency } from '../../utilities/currency';
import { buildCategoryOptions } from '../../common/categoryOptions';

/* globals gettext */

/**
 * ActualTooltip component - displays transaction details for a budget category
 * When clicked, shows a popover with a table of transactions and recategorize options.
 */
const ActualTooltip = ({
  categoryId,
  categoryName,
  amount,
  month,
  allAccounts,
  apiUrls,
  teamSlug,
}) => {
  const [transactions, setTransactions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [snackbar, setSnackbar] = useState({ open: false, message: '', severity: 'info' });
  const [currentAmount, setCurrentAmount] = useState(parseFloat(amount));
  const [undoInfo, setUndoInfo] = useState(null);

  // Listen for transactions moved from other categories to this one
  useEffect(() => {
    const handleTransactionMoved = (event) => {
      const { toCategoryId, amount: movedAmount } = event.detail;
      if (parseInt(categoryId) === toCategoryId) {
        setCurrentAmount(prev => prev + movedAmount);
      }
    };

    window.addEventListener('transaction-moved', handleTransactionMoved);
    return () => window.removeEventListener('transaction-moved', handleTransactionMoved);
  }, [categoryId]);

  // Filter accounts to show only expense/income categories (exclude current category)
  const categoryOptions = useMemo(() => {
    return buildCategoryOptions(allAccounts, {
      excludeId: parseInt(categoryId),
      filterTypes: ['expense', 'income'],
    });
  }, [allAccounts, categoryId]);

  const fetchTransactions = async () => {
    setLoading(true);
    try {
      const response = await fetch(
        `${apiUrls.lines}?account=${categoryId}&month=${month}`,
        {
          credentials: 'same-origin',
        }
      );
      if (!response.ok) {
        throw new Error(`Failed to load transactions (${response.status})`);
      }
      const data = await response.json();
      // Handle both paginated and non-paginated responses
      const rows = Array.isArray(data) ? data : data.results;
      setTransactions(Array.isArray(rows) ? rows : []);
    } catch (error) {
      console.error('Failed to fetch transactions:', error);
      setSnackbar({ open: true, message: gettext('Failed to load transactions'), severity: 'error' });
    } finally {
      setLoading(false);
    }
  };

  const handleRecategorize = async (lineId, newCategoryId) => {
    try {
      const response = await fetch(`${apiUrls.lines}${lineId}/recategorize/`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': Cookies.get('csrftoken'),
        },
        body: JSON.stringify({ new_category_id: newCategoryId }),
      });

      if (response.ok) {
        // Update the displayed amount by subtracting the moved transaction
        const removedTx = transactions.find(t => (t.line_id || t.lineId) === lineId);
        const movedAmount = getAmount(removedTx);
        setCurrentAmount(prev => prev - movedAmount);
        // Remove the recategorized transaction from local state
        setTransactions(transactions.filter(t => (t.line_id || t.lineId) !== lineId));
        // Notify the destination category to update its amount
        window.dispatchEvent(new CustomEvent('transaction-moved', {
          detail: { toCategoryId: parseInt(newCategoryId), amount: movedAmount }
        }));
        // Store undo info and show success message
        const destCategory = allAccounts.find(a => a.id === parseInt(newCategoryId));
        const destName = destCategory?.name || gettext('another category');
        setUndoInfo({ lineId, fromCategoryId: parseInt(categoryId), toCategoryId: parseInt(newCategoryId), amount: movedAmount, transaction: removedTx });
        setSnackbar({ open: true, message: `${formatCurrency(Math.abs(movedAmount))} ${gettext('recategorized to')} ${destName}`, severity: 'success' });
      } else {
        throw new Error('Failed to recategorize');
      }
    } catch (error) {
      console.error('Failed to recategorize:', error);
      setSnackbar({ open: true, message: gettext('Failed to recategorize'), severity: 'error' });
    }
  };

  const handleUndo = async () => {
    if (!undoInfo) return;

    try {
      const response = await fetch(`${apiUrls.lines}${undoInfo.lineId}/recategorize/`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': Cookies.get('csrftoken'),
        },
        body: JSON.stringify({ new_category_id: undoInfo.fromCategoryId }),
      });

      if (response.ok) {
        // Add the transaction back to this category
        setCurrentAmount(prev => prev + undoInfo.amount);
        setTransactions(prev => [...prev, undoInfo.transaction]);
        // Notify the other category to subtract the amount
        window.dispatchEvent(new CustomEvent('transaction-moved', {
          detail: { toCategoryId: undoInfo.toCategoryId, amount: -undoInfo.amount }
        }));
        setUndoInfo(null);
        setSnackbar({ open: true, message: gettext('Undo successful'), severity: 'success' });
      } else {
        throw new Error('Failed to undo');
      }
    } catch (error) {
      console.error('Failed to undo:', error);
      setSnackbar({ open: true, message: gettext('Failed to undo'), severity: 'error' });
    }
  };

  function formatWeekDayDate(date) {
  // Dates here are date-only values parsed as UTC midnight, so read them in
  // UTC — local getters would show the previous day west of UTC.
  const weekday = new Intl.DateTimeFormat('en-US', { weekday: 'short', timeZone: 'UTC' }).format(date);
  const day = date.getUTCDate();

  // Determine ordinal suffix
  let suffix = 'th';
  if (day === 1 || day === 21 || day === 31) suffix = 'st';
  else if (day === 2 || day === 22) suffix = 'nd';
  else if (day === 3 || day === 23) suffix = 'rd';

  return `${weekday}, ${day}${suffix}`;
}

  // Calculate amount display based on inflow/outflow
  const getAmount = (tx) => {
    const inflow = parseFloat(tx.inflow) || 0;
    const outflow = parseFloat(tx.outflow) || 0;
    return inflow > 0 ? inflow : -outflow;
  };

  const dismissToast = () => {
    setSnackbar((prev) => ({ ...prev, open: false }));
    setUndoInfo(null);
  };

  return (
    <>
      <PickerPopover
        label={formatCurrency(currentAmount)}
        onOpen={fetchTransactions}
        testId={`actual-tooltip-${categoryId}`}
        buttonClassName="money cursor-pointer hover:underline hover:text-primary"
        panelClassName="p-4"
      >
        {() => (
          <div className="max-h-[400px] min-w-[32rem] max-w-[44rem] overflow-auto">
            <h3 className="mb-2 text-lg font-bold">
              {categoryName} - {gettext('Transactions')}
            </h3>

            {loading ? (
              <div className="flex justify-center py-8">
                <Spinner size="lg" />
              </div>
            ) : transactions.length > 0 ? (
              <table className="table table-sm table-quiet w-full">
                <thead>
                  <tr>
                    <th>{gettext('Date')}</th>
                    <th>{gettext('Payee')}</th>
                    <th>{gettext('Memo')}</th>
                    <th className="text-right">{gettext('Amount')}</th>
                    <th>{gettext('Recategorize')}</th>
                  </tr>
                </thead>
                <tbody>
                  {transactions.map((tx) => {
                    const lineId = tx.line_id || tx.lineId;
                    return (
                      <tr key={lineId}>
                        <td className="whitespace-nowrap">{formatWeekDayDate(new Date(tx.date))}</td>
                        <td className="max-w-[120px] truncate">{tx.payee_name || tx.payeeName || '-'}</td>
                        <td className="max-w-[150px] truncate" title={tx.description}>
                          {tx.description || '-'}
                        </td>
                        <td className="money whitespace-nowrap text-right">{formatCurrency(getAmount(tx))}</td>
                        <td>
                          <select
                            className="select select-bordered select-sm min-w-[7.5rem]"
                            value=""
                            onChange={(e) => handleRecategorize(lineId, e.target.value)}
                            aria-label={gettext('Move to...')}
                          >
                            <option value="" disabled>
                              {gettext('Move to...')}
                            </option>
                            {categoryOptions.map((account) => (
                              <option key={account.id} value={account.id}>
                                {account.name}
                              </option>
                            ))}
                          </select>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <p className="py-4 text-center text-base-content/70">{gettext('No transactions found')}</p>
            )}

            <div className="mt-3 border-t border-base-300 pt-2 text-sm text-base-content/70">
              {transactions.length} {transactions.length === 1 ? gettext('transaction') : gettext('transactions')} |{' '}
              {gettext('Total')}: {formatCurrency(currentAmount)}
            </div>
          </div>
        )}
      </PickerPopover>

      <Toast
        open={snackbar.open}
        message={snackbar.message}
        severity={snackbar.severity}
        onClose={dismissToast}
        autoHideMs={undoInfo ? 6000 : 3000}
        testId="budget-actual-toast"
        action={
          undoInfo && (
            <button type="button" className="btn btn-ghost btn-xs" onClick={handleUndo}>
              {gettext('Undo')}
            </button>
          )
        }
      />
    </>
  );
};

export default ActualTooltip;
