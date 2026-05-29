/* globals gettext */

import React, { useState } from 'react';
import AccountComboBox from './AccountComboBox';
import CreateAccountModal from './CreateAccountModal';

/**
 * Step3CategoryMapping - Map unrecognized categories to existing accounts
 *
 * Props:
 * - unmappedCategories: Array of category names that need mapping
 * - allAccounts: All available accounts for selection
 * - allAccountGroups: All account groups (for creating new accounts)
 * - uploadApi: API helpers (includes createAccount)
 * - onComplete: Callback with category mappings
 * - onBack: Callback to go back
 * - onCancel: Callback when user cancels
 */
const Step3CategoryMapping = ({ unmappedCategories, allAccounts, allAccountGroups, uploadApi, onComplete, onBack, onCancel }) => {
  const [mappings, setMappings] = useState({});
  const [loading, setLoading] = useState(false);

  // Local copy of accounts so newly created accounts appear without a full page reload
  const [localAccounts, setLocalAccounts] = useState(allAccounts);

  // Track which category is requesting account creation (null = modal closed)
  const [creatingForCategory, setCreatingForCategory] = useState(null);

  const handleMappingChange = (categoryName, accountId) => {
    setMappings((prev) => {
      const next = { ...prev };
      if (accountId == null) {
        delete next[categoryName];
      } else {
        next[categoryName] = accountId;
      }
      return next;
    });
  };

  const handleComplete = async () => {
    setLoading(true);
    await onComplete(mappings);
    setLoading(false);
  };

  const handleCreateAccount = async (name, accountGroupId) => {
    const newAccount = await uploadApi.createAccount(name, accountGroupId);
    setLocalAccounts((prev) => [...prev, newAccount].sort((a, b) => a.name.localeCompare(b.name)));
    // Auto-select the new account for the category that triggered creation
    if (creatingForCategory) {
      handleMappingChange(creatingForCategory, newAccount.id);
    }
    setCreatingForCategory(null);
    return newAccount;
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
              <div className="flex-1 min-w-0">
                <div className="font-medium mb-2">
                  <span className="badge badge-warning mr-2">{gettext('Unmapped')}</span>
                  {categoryName}
                </div>
                <AccountComboBox
                  allAccounts={localAccounts}
                  value={mappings[categoryName] || null}
                  onChange={(accountId) => handleMappingChange(categoryName, accountId)}
                  onCreateNew={() => setCreatingForCategory(categoryName)}
                />
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
        <button className="btn btn-ghost" onClick={onCancel} disabled={loading}>
          {gettext('Cancel')}
        </button>
        <button className="btn btn-ghost" onClick={onBack} disabled={loading}>
          {gettext('Back')}
        </button>
        <button className="btn btn-primary" onClick={handleComplete} disabled={loading}>
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

      {/* Create Account Modal - rendered on top, preserves all upload state */}
      {creatingForCategory && (
        <CreateAccountModal
          allAccountGroups={allAccountGroups}
          onSave={handleCreateAccount}
          onCancel={() => setCreatingForCategory(null)}
        />
      )}
    </div>
  );
};

export default Step3CategoryMapping;
