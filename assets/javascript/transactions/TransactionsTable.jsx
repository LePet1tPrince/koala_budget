/* globals gettext */

import React, { useCallback, useState, useMemo } from 'react';

import { formatCurrency } from '../utilities/currency';
import { formatDate } from '../bank_feed/utils';
import DateRangePicker from '../common/DateRangePicker';

/**
 * Badge component for displaying status/source labels.
 */
const Badge = ({ children, className }) => (
  <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${className}`}>
    {children}
  </span>
);

/**
 * Map source values to human-readable labels and badge colours.
 */
const SOURCE_STYLES = {
  manual: { label: 'Manual', className: 'bg-gray-100 text-gray-800' },
  import: { label: 'Import', className: 'bg-blue-100 text-blue-800' },
  bank_match: { label: 'Bank', className: 'bg-indigo-100 text-indigo-800' },
  recurring: { label: 'Recurring', className: 'bg-purple-100 text-purple-800' },
};

const STATUS_STYLES = {
  draft: { label: 'Draft', className: 'bg-yellow-100 text-yellow-800' },
  posted: { label: 'Posted', className: 'bg-green-100 text-green-800' },
  void: { label: 'Void', className: 'bg-red-100 text-red-800' },
};

/**
 * Check whether `haystack` loosely matches `needle`.
 * Case-insensitive substring match.
 */
const fuzzyMatch = (haystack, needle) => {
  if (!haystack) return false;
  return String(haystack).toLowerCase().includes(needle);
};

/**
 * TransactionsTable - displays a flat list of journal entries as transaction rows.
 *
 * Props:
 *   transactions  – array of transaction row objects from the API
 */
const TransactionsTable = ({ transactions }) => {
  const [search, setSearch] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');

  const handleDateApply = useCallback((start, end) => {
    setStartDate(start);
    setEndDate(end);
  }, []);

  const filtered = useMemo(() => {
    let rows = transactions;

    // Date range filter
    if (startDate || endDate) {
      rows = rows.filter((tx) => {
        if (startDate && tx.date < startDate) return false;
        if (endDate && tx.date > endDate) return false;
        return true;
      });
    }

    // Text search filter
    const q = search.trim().toLowerCase();
    if (q) {
      rows = rows.filter((tx) =>
        fuzzyMatch(tx.payee_name, q) ||
        fuzzyMatch(tx.description, q) ||
        fuzzyMatch(tx.debit_account, q) ||
        fuzzyMatch(tx.credit_account, q) ||
        fuzzyMatch(tx.debit_account_number, q) ||
        fuzzyMatch(tx.credit_account_number, q) ||
        fuzzyMatch(tx.amount, q)
      );
    }

    return rows;
  }, [transactions, search, startDate, endDate]);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={gettext('Search by payee, description, account, account number, or amount...')}
          className="input input-bordered flex-1"
        />
        <DateRangePicker
          startDate={startDate}
          endDate={endDate}
          onApply={handleDateApply}
        />
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                {gettext('Date')}
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                {gettext('Payee')}
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                {gettext('Description')}
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                {gettext('Debit Account')}
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                {gettext('Credit Account')}
              </th>
              <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                {gettext('Amount')}
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                {gettext('Source')}
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                {gettext('Status')}
              </th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {filtered.map((tx) => {
              const source = SOURCE_STYLES[tx.source] || { label: tx.source, className: 'bg-gray-100 text-gray-800' };
              const statusStyle = STATUS_STYLES[tx.status] || { label: tx.status, className: 'bg-gray-100 text-gray-800' };

              return (
                <tr key={tx.id}>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                    {formatDate(tx.date)}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                    {tx.payee_name || <span className="text-gray-400 italic">{gettext('—')}</span>}
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-900 max-w-xs truncate">
                    {tx.description}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                    {tx.debit_account || '—'}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                    {tx.credit_account || '—'}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 text-right">
                    {formatCurrency(tx.amount)}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm">
                    <Badge className={source.className}>{source.label}</Badge>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm">
                    <Badge className={statusStyle.className}>{statusStyle.label}</Badge>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {filtered.length === 0 && (
        <div className="text-center py-12 text-gray-500">
          {gettext('No transactions found.')}
        </div>
      )}
    </div>
  );
};

export default TransactionsTable;
