/* globals gettext */

import React, { useState } from 'react';
import { apiRequest, handleApiError } from './utils';

/**
 * PlaidAccountMapper - Modal component for mapping Plaid accounts to ledger accounts
 *
 * After linking a bank account via Plaid, users need to map each Plaid account
 * to an existing ledger account in their chart of accounts.
 *
 * Props:
 * - teamSlug: The team slug for API calls
 * - plaidAccounts: Array of newly created Plaid accounts
 * - ledgerAccounts: Array of all available ledger accounts
 * - onComplete: Callback when mapping is complete
 * - onCancel: Callback when user cancels
 */
const PlaidAccountMapper = ({ teamSlug, plaidAccounts, ledgerAccounts, onComplete, onCancel }) => {
  const [mappings, setMappings] = useState({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  /**
   * Handle mapping change for a Plaid account
   */
  const handleMappingChange = (plaidAccountId, ledgerAccountId) => {
    setMappings(prev => ({
      ...prev,
      [plaidAccountId]: ledgerAccountId
    }));
  };

  /**
   * Save all mappings to the backend
   */
  const handleSave = async () => {
    // Validate that all accounts are mapped
    const unmappedAccounts = plaidAccounts.filter(
      account => !mappings[account.id]
    );

    if (unmappedAccounts.length > 0) {
      setError(gettext('Please map all accounts before saving.'));
      return;
    }

    setSaving(true);
    setError(null);

    try {
      // Update each Plaid account with its mapped ledger account
      const updatePromises = Object.entries(mappings).map(async ([plaidAccountId, ledgerAccountId]) => {
        const response = await apiRequest(`/a/${teamSlug}/plaid/api/accounts/${plaidAccountId}/`, {
          method: 'PATCH',
          body: JSON.stringify({
            account: ledgerAccountId
          }),
        });
        await handleApiError(response, gettext('Failed to save account mapping'));
        return response;
      });

      await Promise.all(updatePromises);

      // Success! Call the completion callback
      onComplete();
    } catch (err) {
      console.error('Error saving mappings:', err);
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  /**
   * Get account type badge color
   */
  const getAccountTypeBadge = (type) => {
    const typeMap = {
      'depository': 'badge-primary',
      'credit': 'badge-secondary',
      'loan': 'badge-accent',
      'investment': 'badge-info',
    };
    return typeMap[type] || 'badge-neutral';
  };

  return (
    <div className="modal modal-open">
      <div className="modal-box max-w-3xl">
        <h3 className="font-bold text-lg mb-2">
          {gettext('Map Bank Accounts to Ledger Accounts')}
        </h3>
        <p className="text-sm text-base-content/70 mb-6">
          {gettext('Connect each bank account from Plaid to an account in your chart of accounts.')}
        </p>

        {error && (
          <div className="alert alert-error mb-4">
            <i className="fa fa-exclamation-circle"></i>
            <span>{error}</span>
          </div>
        )}

        <div className="space-y-4 max-h-96 overflow-y-auto">
          {plaidAccounts.map(plaidAccount => (
            <div key={plaidAccount.id} className="card bg-base-200 p-4">
              <div className="mb-3">
                <div className="flex items-center justify-between mb-1">
                  <span className="font-semibold text-base">
                    {plaidAccount.name}
                  </span>
                  <span className={`badge ${getAccountTypeBadge(plaidAccount.type)}`}>
                    {plaidAccount.type}
                  </span>
                </div>
                <div className="text-sm text-base-content/70">
                  {plaidAccount.official_name && (
                    <div>{plaidAccount.official_name}</div>
                  )}
                  <div>
                    {plaidAccount.subtype} • ****{plaidAccount.mask}
                  </div>
                </div>
              </div>

              <div className="form-control">
                <label className="label">
                  <span className="label-text font-medium">
                    {gettext('Map to Ledger Account')}
                  </span>
                </label>
                <select
                  className="select select-bordered w-full"
                  value={mappings[plaidAccount.id] || ''}
                  onChange={(e) => handleMappingChange(plaidAccount.id, e.target.value)}
                >
                  <option value="">{gettext('Select an account...')}</option>
                  {ledgerAccounts.map(account => (
                    <option key={account.account_id} value={account.account_id}>
                      {account.account_number} - {account.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          ))}
        </div>

        <div className="modal-action">
          <button
            className="btn btn-ghost"
            onClick={onCancel}
            disabled={saving}
          >
            {gettext('Cancel')}
          </button>
          <button
            className="btn btn-primary"
            onClick={handleSave}
            disabled={saving || Object.keys(mappings).length !== plaidAccounts.length}
          >
            {saving ? (
              <>
                <span className="loading loading-spinner loading-sm"></span>
                {gettext('Saving...')}
              </>
            ) : (
              gettext('Save Mappings')
            )}
          </button>
        </div>
      </div>
    </div>
  );
};

export default PlaidAccountMapper;

