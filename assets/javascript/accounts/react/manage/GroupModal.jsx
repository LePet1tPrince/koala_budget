/* globals gettext, interpolate */
import React, { useEffect, useState } from 'react';

import { ACCOUNT_TYPES, ChoiceButtons, Field, ManageModal, useSubmit } from './parts';

/**
 * Create or edit an account group: name, type and description. A group's type is
 * fixed while it holds accounts, and a system group can't be deleted; the server
 * enforces both and this only says so up front. `groupId` null creates one,
 * pre-typed by `defaults.accountType`.
 */
export default function GroupModal({
  book,
  api,
  groupId = null,
  defaults = {},
  confirmDelete,
  onSaved,
  onDeleted,
  onClose,
}) {
  const isNew = groupId == null;
  const [loaded, setLoaded] = useState(null);
  const [name, setName] = useState(defaults.name || '');
  const [accountType, setAccountType] = useState(defaults.accountType || '');
  const [description, setDescription] = useState('');
  const [loadError, setLoadError] = useState(null);
  const [busy, errors, run] = useSubmit();

  useEffect(() => {
    if (isNew) return;
    api
      .accountsGroupsRetrieve({ ...book.params, id: groupId })
      .then((group) => {
        setLoaded(group);
        setName(group.name);
        setAccountType(group.accountType);
        setDescription(group.description || '');
      })
      .catch(() => setLoadError(gettext('This group could not be loaded. Please try again.')));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const typeLocked = Boolean(loaded && (loaded.isSystem || loaded.accountCount > 0));

  const save = () =>
    run(async () => {
      const body = { name: name.trim(), accountType, description: description.trim() };
      const group = isNew
        ? await api.accountsGroupsCreate({ ...book.params, managedAccountGroup: body })
        : await api.accountsGroupsPartialUpdate({ ...book.params, id: groupId, patchedManagedAccountGroup: body });
      onSaved(group);
    });

  const remove = () =>
    run(async () => {
      await api.accountsGroupsDestroy({ ...book.params, id: groupId });
      onDeleted();
    });

  const ready = isNew || loaded;
  return (
    <ManageModal
      title={isNew ? gettext('New group') : interpolate(gettext('Edit “%s”'), [loaded?.name ?? ''])}
      testId="group-modal"
      onClose={onClose}
      onSave={save}
      onDelete={loaded && !loaded.isSystem ? remove : null}
      confirmDelete={confirmDelete}
      deleteNote={gettext('Only an empty group can be deleted: move its accounts to another group first.')}
      saveLabel={isNew ? gettext('Create group') : gettext('Save')}
      canSave={Boolean(ready && name.trim() && accountType)}
      formError={loadError || errors._form}
      busy={busy}
    >
      {!ready && !loadError ? (
        <div className="flex justify-center py-8" aria-label={gettext('Loading')}>
          <span className="loading loading-spinner loading-md text-base-content/40" />
        </div>
      ) : (
        ready && (
          <>
            <Field label={gettext('Name')} error={errors.name}>
              <input
                type="text"
                name="name"
                className="input input-bordered w-full"
                value={name}
                maxLength={200}
                placeholder={gettext('e.g. Bank accounts')}
                onChange={(e) => setName(e.target.value)}
                data-autofocus
                data-testid="group-name-input"
              />
            </Field>
            <Field
              label={gettext('Type')}
              error={errors.accountType}
              hint={typeLocked ? gettext('Fixed while the group has accounts in it.') : null}
            >
              <ChoiceButtons
                options={ACCOUNT_TYPES}
                value={accountType}
                onChange={setAccountType}
                disabled={typeLocked}
                testIdFor={(option) => `type-btn-${option.key}`}
              />
            </Field>
            <Field label={gettext('Description')} error={errors.description} hint={gettext('Optional.')}>
              <textarea
                className="textarea textarea-bordered w-full"
                rows={2}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                data-testid="group-description-input"
              />
            </Field>
          </>
        )
      )}
    </ManageModal>
  );
}
