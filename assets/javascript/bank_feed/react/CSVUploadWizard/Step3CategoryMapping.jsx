/* globals gettext */

import React, { useState } from 'react';
import AccountComboBox from './AccountComboBox';
import CreateAccountModal from './CreateAccountModal';
import { formatCurrency } from '../../../utilities/currency';

/**
 * Build the initial mapping from each category's deterministic suggestion.
 * Suggestions pre-fill the dropdown but are clearly flagged so the user knows
 * to double-check them.
 */
const buildInitialMappings = (unmappedCategories) => {
  const initial = {};
  unmappedCategories.forEach((cat) => {
    if (cat.suggested_account_id != null) {
      initial[cat.name] = cat.suggested_account_id;
    }
  });
  return initial;
};

/**
 * Step3CategoryMapping - Map unrecognized categories to existing accounts
 *
 * Props:
 * - unmappedCategories: Array of { name, inflow, outflow, count,
 *     suggested_account_id, suggested_account_name } that need mapping
 * - allAccounts: All available accounts for selection
 * - allAccountGroups: All account groups (for creating new accounts)
 * - uploadApi: API helpers (includes createAccount)
 * - onComplete: Callback with category mappings
 * - onBack: Callback to go back
 * - onCancel: Callback when user cancels
 */
const Step3CategoryMapping = ({ unmappedCategories, initialMappings = {}, allAccounts, allAccountGroups, uploadApi, onComplete, onBack, onCancel }) => {
  // Seed with suggestions, then overlay any mappings the user already confirmed (initialMappings wins).
  const [mappings, setMappings] = useState(() => ({
    ...buildInitialMappings(unmappedCategories),
    ...initialMappings,
  }));
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
      {unmappedCategories.length > 0 && (
        <div className="text-sm text-base-content/70">
          {gettext('The following categories from your file could not be automatically matched. Map them to existing accounts or leave them unmapped to categorize later. We pre-fill a suggested account where we can — please double-check it.')}
        </div>
      )}

      {/* Responsive multi-column grid of mapping cards */}
      {unmappedCategories.length === 0 ? (
        <div className="py-8 text-center text-base-content/50">
          <i className="fa fa-check-circle text-2xl mb-2 block text-success"></i>
          {gettext('No categories to map — all transactions are already categorized.')}
        </div>
      ) : null}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 max-h-[28rem] overflow-y-auto pr-1">
        {unmappedCategories.map((cat) => {
          const isSuggested = cat.suggested_account_id != null && mappings[cat.name] === cat.suggested_account_id;
          const inflow = parseFloat(cat.inflow) || 0;
          const outflow = parseFloat(cat.outflow) || 0;
          return (
            <div key={cat.name} className="card bg-base-200 p-4 flex flex-col gap-3">
              <div className="min-w-0">
                <div className="font-medium flex items-center gap-2 flex-wrap">
                  {!mappings[cat.name] && (
                    <span className="badge badge-warning">{gettext('Unmapped')}</span>
                  )}
                  <span className="truncate" title={cat.name}>{cat.name}</span>
                </div>
                {cat.count != null && (
                  <div className="text-xs text-base-content/50 mt-1">
                    {cat.count} {cat.count === 1 ? gettext('transaction') : gettext('transactions')}
                  </div>
                )}
              </div>

              {/* Inflow / outflow totals for this category */}
              <div className="flex items-center gap-4 text-sm">
                <div className="flex flex-col">
                  <span className="text-xs uppercase tracking-wide text-base-content/50">{gettext('In')}</span>
                  <span className={inflow > 0 ? 'text-success font-medium' : 'text-base-content/40'}>
                    {formatCurrency(inflow)}
                  </span>
                </div>
                <div className="flex flex-col">
                  <span className="text-xs uppercase tracking-wide text-base-content/50">{gettext('Out')}</span>
                  <span className={outflow > 0 ? 'text-error font-medium' : 'text-base-content/40'}>
                    {formatCurrency(outflow)}
                  </span>
                </div>
              </div>

              <div className="mt-auto">
                <AccountComboBox
                  allAccounts={localAccounts}
                  value={mappings[cat.name] || null}
                  onChange={(accountId) => handleMappingChange(cat.name, accountId)}
                  onCreateNew={() => setCreatingForCategory(cat.name)}
                />
                {isSuggested && (
                  <div className="text-xs text-info mt-1 flex items-center gap-1">
                    <i className="fa fa-lightbulb-o"></i>
                    {gettext('Suggested — please verify')}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {unmappedCategories.length > 0 && (
        <div className="text-sm text-base-content/70">
          <i className="fa fa-info-circle mr-2"></i>
          {Object.keys(mappings).length} {gettext('of')} {unmappedCategories.length} {gettext('categories mapped')}
        </div>
      )}

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
