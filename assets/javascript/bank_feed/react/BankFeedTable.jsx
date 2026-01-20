/* globals gettext */

import React, { useState } from 'react';

import { formatCurrency } from '../../utilities/currency';
import { formatDate } from './utils';

/**
 * BankFeedTable component - displays bank feed data (ledger + Plaid transactions)
 */
const BankFeedTable = ({
  lines,
  selectedAccount,
  allAccounts,
  allPayees,
  onCategorize,
  onEditLedger,
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

  // Filter out only uncategorized Plaid transactions for categorization
  const uncategorizedRows = lines.filter(line => !line.category);

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
                  <option key={account.id} value={account.id}>
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
                {gettext('Category')}
              </th>
              <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                {gettext('Outflow')}
              </th>
              <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                {gettext('Inflow')}
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                {gettext('Status')}
              </th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {lines.map((line) => (
              <tr key={line.id} className={line.source === 'plaid' ? 'bg-blue-50' : ''}>
                <td className="px-3 py-4 whitespace-nowrap">
                  {line.source === 'plaid' && !line.category && (
                    <input
                      type="checkbox"
                      checked={selectedRows.some(r => r.id === line.id)}
                      onChange={(e) => handleRowSelect(line, e.target.checked)}
                    />
                  )}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                  {formatDate(line.posted_date)}
                </td>
                <td className="px-6 py-4 text-sm text-gray-900">
                  <div>
                    {line.description}
                    {line.merchant_name && (
                      <div className="text-xs text-gray-500">{line.merchant_name}</div>
                    )}
                  </div>
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                  {line.category ? line.category.name : (
                    <span className="text-gray-400 italic">{gettext('Uncategorized')}</span>
                  )}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 text-right">
                  {line.outflow > 0 ? formatCurrency(line.outflow) : ''}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 text-right">
                  {line.inflow > 0 ? formatCurrency(line.inflow) : ''}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm">
                  <div className="flex items-center space-x-2">
                    {line.source === 'plaid' && (
                      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
                        {gettext('Bank')}
                      </span>
                    )}
                    {line.is_pending && (
                      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-800">
                        {gettext('Pending')}
                      </span>
                    )}
                    {line.is_cleared && (
                      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
                        {gettext('Cleared')}
                      </span>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {lines.length === 0 && (
        <div className="text-center py-12 text-gray-500">
          {gettext('No transactions found for this account.')}
        </div>
      )}
    </div>
  );
};

export default BankFeedTable;
