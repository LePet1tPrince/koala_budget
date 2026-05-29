/* globals gettext */

import React, { useState, useMemo } from 'react';

const ACCOUNT_TYPE_LABELS = {
  asset: gettext('Asset'),
  liability: gettext('Liability'),
  income: gettext('Income'),
  expense: gettext('Expense'),
  goal: gettext('Goal'),
};

const CreateAccountModal = ({ allAccountGroups, onSave, onCancel }) => {
  const [name, setName] = useState('');
  const [selectedType, setSelectedType] = useState('');
  const [selectedGroupId, setSelectedGroupId] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const accountTypes = useMemo(() => {
    const types = [...new Set(allAccountGroups.map((g) => g.account_type))];
    return types.sort();
  }, [allAccountGroups]);

  const filteredGroups = useMemo(() => {
    if (!selectedType) return [];
    return allAccountGroups.filter((g) => g.account_type === selectedType);
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
    <div className="modal modal-open" style={{ zIndex: 1100 }}>
      <div className="modal-box max-w-md">
        <h3 className="font-bold text-lg mb-4">{gettext('Create New Account')}</h3>

        {error && (
          <div className="alert alert-error mb-4">
            <i className="fa fa-exclamation-circle"></i>
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
                <p className="text-sm text-base-content/60">
                  {gettext('No groups available for this type.')}
                </p>
              ) : (
                <select
                  className="select select-bordered w-full"
                  value={selectedGroupId}
                  onChange={(e) => setSelectedGroupId(e.target.value)}
                  required
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
            <button
              type="button"
              className="btn btn-ghost"
              onClick={onCancel}
              disabled={loading}
            >
              {gettext('Cancel')}
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={loading || !name.trim() || !selectedGroupId}
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
      </div>
    </div>
  );
};

export default CreateAccountModal;
