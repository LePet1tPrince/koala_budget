/* globals gettext */
import React, { useState } from 'react';

import { formatCurrency } from '../../utilities/currency';
import { formatDate } from './utils';

/**
 * BankTransactionTable component - displays bank transactions from BankTransaction model
 */
const BankTransactionTable = ({
  transactions,
  selectedAccount,
  allAccounts,
  allPayees,
  onCategorize,
}) => {
  const [selectedRows, setSelectedRows] = useState([]);
  const [categoryAccount, setCategoryAccount] = useState('');

  // Handle row selection for categorization
  const handleRowSelect = (row, isSelected) => {
    if (isSelected) {
      setSelectedRows([...selectedRows, row]);
    } else {
      setSelectedRows(selectedRows.filter(r => r.id !== row.id));
    }
  };

  // Handle categorize button click
  const handleCategorizeClick = async () => {
    if (selectedRows.length === 0 || !categoryAccount) {
      alert(gettext('Please select transactions and a category account.'));
      return;
    }

    try {
      await onCategorize(selectedRows, categoryAccount);
      setSelectedRows([]);
      setCategoryAccount('');
    } catch (err) {
      alert(gettext('Failed to categorize transactions: ') + err.message);
    }
  };

  // Filter out only uncategorized transactions for categorization
  const uncategorizedRows = transactions.filter(tx => !tx.is_categorized);

  return (
    <div className="space-y-4">
      {/* Categorization Controls */}
      {uncategorizedRows.length > 0 && (
        <div className="bg-blue-50 p-4 rounded-lg border border-blue-200">
          <h3 className="text-sm font-medium text-blue-900 mb-3">
            {gettext('Categorize Transactions')}
          </h3>
          <div className="flex gap-4 items-end">
            <div className="flex-1">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                {gettext('Category Account')}
              </label>
              <select
                value={categoryAccount}
                onChange={(e) => setCategoryAccount(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">{gettext('Select category...')}</option>
                {allAccounts.map((account) => (
                  <option key={account.account_id} value={account.account_id}>
                    {account.name}
                  </option>
                ))}
              </select>
            </div>
            <button
              onClick={handleCategorizeClick}
              disabled={selectedRows.length === 0 || !categoryAccount}
              className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
            >
              {gettext('Categorize Selected')} ({selectedRows.length})
            </button>
          </div>
        </div>
      )}

      {/* Transactions Table */}
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="w-8 px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                <input
                  type="checkbox"
                  onChange={(e) => {
                    if (e.target.checked) {
                      setSelectedRows(uncategorizedRows);
                    } else {
                      setSelectedRows([]);
                    }
                  }}
                  checked={selectedRows.length === uncategorizedRows.length && uncategorizedRows.length > 0}
                />
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                {gettext('Date')}
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                {gettext('Description')}
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                {gettext('Source')}
              </th>
              <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                {gettext('Amount')}
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                {gettext('Status')}
              </th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {transactions.map((tx) => (
              <tr key={tx.id} className={tx.is_categorized ? '' : 'bg-yellow-50'}>
                <td className="px-3 py-4 whitespace-nowrap">
                  {!tx.is_categorized && (
                    <input
                      type="checkbox"
                      checked={selectedRows.some(r => r.id === tx.id)}
                      onChange={(e) => handleRowSelect(tx, e.target.checked)}
                    />
                  )}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                  {formatDate(tx.date)}
                </td>
                <td className="px-6 py-4 text-sm text-gray-900">
                  <div>
                    {tx.description}
                    {tx.merchant_name && (
                      <div className="text-xs text-gray-500">{tx.merchant_name}</div>
                    )}
                  </div>
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                  <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                    tx.source === 'plaid' ? 'bg-blue-100 text-blue-800' :
                    tx.source === 'csv' ? 'bg-green-100 text-green-800' :
                    'bg-gray-100 text-gray-800'
                  }`}>
                    {tx.source}
                  </span>
                </td>
                <td className={`px-6 py-4 whitespace-nowrap text-sm text-right ${
                  parseFloat(tx.amount) < 0 ? 'text-green-600' : 'text-red-600'
                }`}>
                  {formatCurrency(Math.abs(tx.amount))}
                  {parseFloat(tx.amount) < 0 ? ' ↓' : ' ↑'}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm">
                  <div className="flex items-center space-x-2">
                    {tx.pending && (
                      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-800">
                        {gettext('Pending')}
                      </span>
                    )}
                    {tx.is_categorized ? (
                      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
                        {gettext('Categorized')}
                      </span>
                    ) : (
                      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-orange-100 text-orange-800">
                        {gettext('Uncategorized')}
                      </span>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {transactions.length === 0 && (
        <div className="text-center py-12 text-gray-500">
          {gettext('No transactions found for this account.')}
        </div>
      )}
    </div>
  );
};

export default BankTransactionTable;

