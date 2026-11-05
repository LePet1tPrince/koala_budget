/* globals gettext */

import React, { useState, useMemo } from 'react';
import Icon from '../../../common/Icon';
import Modal from '../../../common/Modal';

const ACCOUNT_TYPE_LABELS = {
  asset: gettext('Asset'),
  liability: gettext('Liability'),
  income: gettext('Income'),
  expense: gettext('Expense'),
  goal: gettext('Goal'),
};

/**
 * Name, type and group for a new account. A real `<dialog>` (common `Modal`), so it
 * stacks above whatever opened it — including another `<dialog>`, such as the
 * transaction editor. `allAccountGroups` null means the groups are still loading.
 */
const CreateAccountModal = ({ allAccountGroups, onSave, onCancel, initialName = '' }) => {
  const [name, setName] = useState(initialName);
  const [selectedType, setSelectedType] = useState('');
  const [selectedGroupId, setSelectedGroupId] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const accountTypes = useMemo(() => {
    const types = [...new Set((allAccountGroups || []).map((g) => g.account_type))];
    return types.sort();
  }, [allAccountGroups]);

  const filteredGroups = useMemo(() => {
    if (!selectedType) return [];
    return (allAccountGroups || []).filter((g) => g.account_type === selectedType);
  }, [allAccountGroups, selectedType]);

  const handleTypeChange = (type) => {
    setSelectedType(type);
    setSelectedGroupId('');
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!name.trim() || !selectedGroupId) return;

    setLoading(true);
    setError(null);
    try {
      const newAccount = await onSave(name.trim(), parseInt(selectedGroupId, 10));
      // onSave is responsible for closing the modal on success
    } catch (err) {
      setError(err.message || gettext('Failed to create account'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      open
      onClose={() => !loading && onCancel()}
      size="sm"
      title={gettext('Create New Account')}
      testId="create-account-modal"
      initialFocus="[data-testid='create-account-name']"
    >
      {error && (
        <div className="alert alert-error mb-4">
          <Icon name="exclamation-circle" className="inline-block shrink-0 w-4 h-4" />
          <span>{error}</span>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="form-control">
          <label className="label">
            <span className="label-text font-medium">{gettext('Account Name')}</span>
          </label>
          <input
            type="text"
            className="input input-bordered w-full"
            placeholder={gettext('e.g. Groceries')}
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoFocus
            required
            data-testid="create-account-name"
          />
        </div>

        <div className="form-control">
          <label className="label">
            <span className="label-text font-medium">{gettext('Account Type')}</span>
          </label>
          <select
            className="select select-bordered w-full"
            value={selectedType}
            onChange={(e) => handleTypeChange(e.target.value)}
            required
            disabled={!allAccountGroups}
            data-testid="create-account-type"
          >
            <option value="">{gettext('-- Select type --')}</option>
            {accountTypes.map((type) => (
              <option key={type} value={type}>
                {ACCOUNT_TYPE_LABELS[type] || type}
              </option>
            ))}
          </select>
        </div>

        {selectedType && (
          <div className="form-control">
            <label className="label">
              <span className="label-text font-medium">{gettext('Account Group')}</span>
            </label>
            {filteredGroups.length === 0 ? (
              <p className="text-sm text-base-content/70">{gettext('No groups available for this type.')}</p>
            ) : (
              <select
                className="select select-bordered w-full"
                value={selectedGroupId}
                onChange={(e) => setSelectedGroupId(e.target.value)}
                required
                data-testid="create-account-group"
              >
                <option value="">{gettext('-- Select group --')}</option>
                {filteredGroups.map((group) => (
                  <option key={group.id} value={group.id}>
                    {group.name}
                  </option>
                ))}
              </select>
            )}
          </div>
        )}

        <div className="modal-action">
          <button type="button" className="btn btn-ghost" onClick={onCancel} disabled={loading}>
            {gettext('Cancel')}
          </button>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={loading || !name.trim() || !selectedGroupId}
            data-testid="create-account-submit"
          >
            {loading ? (
              <>
                <span className="loading loading-spinner loading-sm"></span>
                {gettext('Creating...')}
              </>
            ) : (
              gettext('Create Account')
            )}
          </button>
        </div>
      </form>
    </Modal>
  );
};

export default CreateAccountModal;
