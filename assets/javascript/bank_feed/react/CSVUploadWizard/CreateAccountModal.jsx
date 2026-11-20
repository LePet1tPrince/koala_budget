/* globals gettext */

import React, { useMemo, useState } from 'react';

import { ACCOUNT_TYPES, ChoiceButtons, Field, ManageModal } from '../../../accounts/react/manage/parts';

/**
 * Name, type and group for a new account, from a category picker (the Inbox,
 * Categorize, the transaction editor, the CSV wizard). Laid out like the Manage
 * editors (`accounts/react/manage/`): the same fields, buttons for type and group,
 * the error in place. A real `<dialog>`, so it stacks above whatever opened it —
 * including another `<dialog>`, such as the transaction editor.
 *
 * `allAccountGroups` ({id, name, account_type}) null means they are still loading.
 * `onSave(name, groupId)` creates the account and closes the modal; a thrown
 * error's message is shown.
 */
const CreateAccountModal = ({ allAccountGroups, onSave, onCancel, initialName = '' }) => {
  const [name, setName] = useState(initialName);
  const [accountType, setAccountType] = useState('');
  const [groupId, setGroupId] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  // The types the book has groups for, in the usual order.
  const types = useMemo(() => {
    const present = new Set((allAccountGroups || []).map((g) => g.account_type));
    return ACCOUNT_TYPES.filter((type) => present.has(type.key));
  }, [allAccountGroups]);

  const groupsOfType = useMemo(
    () => (allAccountGroups || []).filter((g) => g.account_type === accountType),
    [allAccountGroups, accountType],
  );

  const pickType = (key) => {
    if (key === accountType) return;
    setAccountType(key);
    const ofType = (allAccountGroups || []).filter((g) => g.account_type === key);
    setGroupId(ofType.length === 1 ? ofType[0].id : null);
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await onSave(name.trim(), groupId);
    } catch (err) {
      setError(err.message || gettext('The account could not be created.'));
      setBusy(false);
    }
  };

  return (
    <ManageModal
      title={gettext('New account')}
      testId="create-account-modal"
      onClose={onCancel}
      onSave={save}
      saveLabel={gettext('Create account')}
      canSave={Boolean(name.trim() && groupId)}
      formError={error}
      busy={busy}
    >
      <Field label={gettext('Name')}>
        <input
          type="text"
          className="input input-bordered w-full"
          value={name}
          maxLength={200}
          placeholder={gettext('e.g. Groceries')}
          onChange={(e) => setName(e.target.value)}
          data-autofocus
          data-testid="create-account-name"
        />
      </Field>

      {allAccountGroups === null ? (
        <div className="flex justify-center py-4" aria-label={gettext('Loading')} data-testid="create-account-loading">
          <span className="loading loading-spinner loading-md text-base-content/40" />
        </div>
      ) : (
        <>
          <Field label={gettext('Type')}>
            <ChoiceButtons
              options={types}
              value={accountType}
              onChange={pickType}
              testIdFor={(option) => `create-account-type-${option.key}`}
            />
          </Field>
          {accountType && (
            <Field
              label={gettext('Group')}
              hint={groupsOfType.length === 0 ? gettext('No groups of this type yet.') : null}
            >
              {groupsOfType.length > 0 && (
                <ChoiceButtons
                  options={groupsOfType.map((g) => ({ key: g.id, label: g.name }))}
                  value={groupId}
                  onChange={setGroupId}
                  testIdFor={() => 'create-account-group'}
                />
              )}
            </Field>
          )}
        </>
      )}
    </ManageModal>
  );
};

export default CreateAccountModal;
