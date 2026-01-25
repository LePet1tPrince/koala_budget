/* globals gettext */

import React, { useState } from 'react';

/**
 * Step3CategoryMapping - Map unrecognized categories to existing accounts
 *
 * Props:
 * - unmappedCategories: Array of category names that need mapping
 * - allAccounts: All available accounts for selection
 * - onComplete: Callback with category mappings
 * - onBack: Callback to go back
 * - onCancel: Callback when user cancels
 */
const Step3CategoryMapping = ({ unmappedCategories, allAccounts, onComplete, onBack, onCancel }) => {
  const [mappings, setMappings] = useState({});
  const [loading, setLoading] = useState(false);
  const [searchTerms, setSearchTerms] = useState({});

  const handleMappingChange = (categoryName, accountId) => {
    const value = accountId === '' ? null : parseInt(accountId, 10);
    setMappings((prev) => {
      const newMappings = { ...prev };
      if (value === null) {
        delete newMappings[categoryName];
      } else {
        newMappings[categoryName] = value;
      }
      return newMappings;
    });
  };

  const handleSearchChange = (categoryName, term) => {
    setSearchTerms((prev) => ({
      ...prev,
      [categoryName]: term,
    }));
  };

  const getFilteredAccounts = (categoryName) => {
    const searchTerm = (searchTerms[categoryName] || '').toLowerCase();
    if (!searchTerm) return allAccounts;
    return allAccounts.filter(
      (account) =>
        account.name.toLowerCase().includes(searchTerm) ||
        account.account_number.toLowerCase().includes(searchTerm)
    );
  };

  const handleComplete = async () => {
    setLoading(true);
    await onComplete(mappings);
    setLoading(false);
  };

  // Group accounts by type for easier selection
  const groupedAccounts = allAccounts.reduce((groups, account) => {
    const type = account.account_group?.account_type || 'other';
    if (!groups[type]) {
      groups[type] = [];
    }
    groups[type].push(account);
    return groups;
  }, {});

  const accountTypeLabels = {
    asset: gettext('Assets'),
    liability: gettext('Liabilities'),
    income: gettext('Income'),
    expense: gettext('Expenses'),
    equity: gettext('Equity'),
    other: gettext('Other'),
  };

  return (
    <div className="space-y-6">
      <div className="text-sm text-base-content/70">
        {gettext('The following categories from your file could not be automatically matched. Map them to existing accounts or leave them unmapped to categorize later.')}
      </div>

      <div className="space-y-4 max-h-96 overflow-y-auto">
        {unmappedCategories.map((categoryName) => (
          <div key={categoryName} className="card bg-base-200 p-4">
            <div className="flex items-start gap-4">
              <div className="flex-1">
                <div className="font-medium mb-2">
                  <span className="badge badge-warning mr-2">{gettext('Unmapped')}</span>
                  {categoryName}
                </div>
                <div className="form-control">
                  <input
                    type="text"
                    className="input input-bordered input-sm mb-2"
                    placeholder={gettext('Search accounts...')}
                    value={searchTerms[categoryName] || ''}
                    onChange={(e) => handleSearchChange(categoryName, e.target.value)}
                  />
                  <select
                    className="select select-bordered w-full"
                    value={mappings[categoryName] || ''}
                    onChange={(e) => handleMappingChange(categoryName, e.target.value)}
                  >
                    <option value="">{gettext('-- Leave uncategorized --')}</option>
                    {Object.entries(groupedAccounts).map(([type, accounts]) => {
                      const filteredAccounts = accounts.filter((account) => {
                        const searchTerm = (searchTerms[categoryName] || '').toLowerCase();
                        if (!searchTerm) return true;
                        return (
                          account.name.toLowerCase().includes(searchTerm) ||
                          account.account_number.toLowerCase().includes(searchTerm)
                        );
                      });

                      if (filteredAccounts.length === 0) return null;

                      return (
                        <optgroup key={type} label={accountTypeLabels[type] || type}>
                          {filteredAccounts.map((account) => (
                            <option key={account.id} value={account.id}>
                              {account.account_number} - {account.name}
                            </option>
                          ))}
                        </optgroup>
                      );
                    })}
                  </select>
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="text-sm text-base-content/70">
        <i className="fa fa-info-circle mr-2"></i>
        {Object.keys(mappings).length} {gettext('of')} {unmappedCategories.length} {gettext('categories mapped')}
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
          onClick={handleComplete}
          disabled={loading}
        >
          {loading ? (
            <>
              <span className="loading loading-spinner loading-sm"></span>
              {gettext('Processing...')}
            </>
          ) : (
            gettext('Next')
          )}
        </button>
      </div>
    </div>
  );
};

export default Step3CategoryMapping;
