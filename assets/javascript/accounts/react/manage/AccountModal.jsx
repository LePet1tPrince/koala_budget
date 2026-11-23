/* globals gettext, interpolate */
import React, { useEffect, useMemo, useState } from 'react';

import { ACCOUNT_TYPES, ChoiceButtons, Field, ManageModal, Toggle, useSubmit } from './parts';

// Only assets and liabilities are held at an institution or come in through a feed.
const HELD_TYPES = new Set(['asset', 'liability']);

/**
 * Create or edit an account: name, type, group, institution, feed and (editing)
 * hidden. `accountId` null creates one; `defaults` ({ name, accountType,
 * accountGroup, institution }) pre-fill a new one. Calls `onSaved(account)` with
 * the saved `ManagedAccount`, `onDeleted()` after a delete.
 */
export default function AccountModal({
  book,
  api,
  accountId = null,
  defaults = {},
  confirmDelete,
  onSaved,
  onDeleted,
  onClose,
}) {
  const isNew = accountId == null;
  const [loaded, setLoaded] = useState(null);
  const [groups, setGroups] = useState(null);
  const [institutions, setInstitutions] = useState([]);
  const [name, setName] = useState(defaults.name || '');
  const [accountType, setAccountType] = useState(defaults.accountType || '');
  const [groupId, setGroupId] = useState(defaults.accountGroup ? Number(defaults.accountGroup) : null);
  const [institution, setInstitution] = useState(defaults.institution ? Number(defaults.institution) : null);
  const [hasFeed, setHasFeed] = useState(null); // null: the server's default for the type
  const [isHidden, setIsHidden] = useState(false);
  const [loadError, setLoadError] = useState(null);
  const [busy, errors, run] = useSubmit();

  useEffect(() => {
    const params = book.params;
    Promise.all([
      api.accountsGroupsList(params),
      api.accountsInstitutionsList(params),
      isNew ? null : api.accountsAccountsRetrieve({ ...params, id: accountId }),
    ])
      .then(([groupList, institutionList, account]) => {
        setGroups(groupList);
        setInstitutions(institutionList);
        if (account) {
          setLoaded(account);
          setName(account.name);
          setAccountType(account.accountType);
          setGroupId(account.accountGroup);
          setInstitution(account.institution ?? null);
          setHasFeed(Boolean(account.hasFeed));
          setIsHidden(Boolean(account.isHidden));
        } else if (!defaults.accountType && defaults.accountGroup) {
          const group = groupList.find((g) => g.id === Number(defaults.accountGroup));
          if (group) setAccountType(group.accountType);
        }
      })
      .catch(() => setLoadError(gettext('This account could not be loaded. Please try again.')));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const groupsOfType = useMemo(
    () => (groups || []).filter((g) => g.accountType === accountType),
    [groups, accountType],
  );
  const held = HELD_TYPES.has(accountType);
  const fixed = Boolean(loaded && (loaded.isSystem || loaded.isGoal));

  const pickType = (key) => {
    if (key === accountType) return;
    setAccountType(key);
    const ofType = (groups || []).filter((g) => g.accountType === key);
    setGroupId(ofType.length === 1 ? ofType[0].id : null);
  };

  const save = () =>
    run(async () => {
      const body = { name: name.trim(), accountGroup: groupId, institution: held ? institution : null };
      if (hasFeed !== null) body.hasFeed = held && hasFeed;
      if (!isNew) body.isHidden = isHidden;
      const account = isNew
        ? await api.accountsAccountsCreate({ ...book.params, managedAccount: body })
        : await api.accountsAccountsPartialUpdate({ ...book.params, id: accountId, patchedManagedAccount: body });
      onSaved(account);
    });

  const remove = () =>
    run(async () => {
      await api.accountsAccountsDestroy({ ...book.params, id: accountId });
      onDeleted();
    });

  const ready = groups !== null && (isNew || loaded);
  const title = isNew ? gettext('New account') : interpolate(gettext('Edit “%s”'), [loaded?.name ?? '']);

  return (
    <ManageModal
      title={title}
      testId="account-modal"
      onClose={onClose}
      onSave={save}
      onDelete={!isNew && loaded && !fixed ? remove : null}
      confirmDelete={confirmDelete}
      deleteNote={gettext(
        "An account with transactions can't be deleted; an opening balance, if it has one, is removed with it.",
      )}
      saveLabel={isNew ? gettext('Create account') : gettext('Save')}
      canSave={Boolean(ready && name.trim() && groupId)}
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
                placeholder={gettext('e.g. Everyday chequing')}
                onChange={(e) => setName(e.target.value)}
                data-autofocus
                data-testid="account-name-input"
              />
            </Field>

            <Field
              label={gettext('Type')}
              hint={fixed ? gettext('Goal and system accounts keep their type and group.') : null}
            >
              <ChoiceButtons
                options={ACCOUNT_TYPES}
                value={accountType}
                onChange={pickType}
                disabled={fixed}
                testIdFor={(option) => `type-btn-${option.key}`}
              />
            </Field>

            {accountType && (
              <Field
                label={gettext('Group')}
                error={errors.accountGroup}
                hint={
                  groupsOfType.length === 0 ? gettext('No groups of this type yet — add one on the Groups tab.') : null
                }
              >
                {groupsOfType.length > 0 && (
                  <ChoiceButtons
                    options={groupsOfType.map((g) => ({ key: g.id, label: g.name }))}
                    value={groupId}
                    onChange={setGroupId}
                    disabled={fixed}
                    testIdFor={() => 'group-btn'}
                  />
                )}
              </Field>
            )}

            {held && (
              <>
                <Field label={gettext('Institution')} error={errors.institution}>
                  <select
                    className="select select-bordered w-full"
                    value={institution ?? ''}
                    onChange={(e) => setInstitution(e.target.value ? Number(e.target.value) : null)}
                    data-testid="account-institution-select"
                  >
                    <option value="">{gettext('None')}</option>
                    {institutions.map((i) => (
                      <option key={i.id} value={i.id}>
                        {i.name}
                      </option>
                    ))}
                  </select>
                </Field>
                <Toggle
                  label={gettext('Bank feed')}
                  hint={gettext('Its transactions come into the Inbox to be categorized.')}
                  checked={hasFeed ?? true}
                  onChange={setHasFeed}
                  testId="account-feed-toggle"
                />
              </>
            )}

            {!isNew && (
              <Toggle
                label={gettext('Hidden')}
                hint={gettext('Left out of account pickers and the Inbox; it still counts in every balance.')}
                checked={isHidden}
                onChange={setIsHidden}
                testId="account-hidden-toggle"
              />
            )}
          </>
        )
      )}
    </ManageModal>
  );
}
