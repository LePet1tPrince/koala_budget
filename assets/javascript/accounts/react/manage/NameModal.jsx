/* globals gettext, interpolate */
import React, { useState } from 'react';

import { Field, ManageModal, useSubmit } from './parts';

/**
 * Payees and institutions are just a name, so one modal serves both. `kind`
 * picks the endpoints and wording; `item` ({ id, name }) edits one, null creates.
 */
const KINDS = {
  payee: {
    newTitle: gettext('New payee'),
    create: (api, params, body) => api.accountsPayeesCreate({ ...params, managedPayee: body }),
    update: (api, params, id, body) => api.accountsPayeesPartialUpdate({ ...params, id, patchedManagedPayee: body }),
    destroy: (api, params, id) => api.accountsPayeesDestroy({ ...params, id }),
    placeholder: gettext('e.g. Corner Grocer'),
    deleteNote: gettext("A payee on a transaction can't be deleted; rename it, or change those transactions first."),
    createLabel: gettext('Create payee'),
  },
  institution: {
    newTitle: gettext('New institution'),
    create: (api, params, body) => api.accountsInstitutionsCreate({ ...params, managedInstitution: body }),
    update: (api, params, id, body) =>
      api.accountsInstitutionsPartialUpdate({ ...params, id, patchedManagedInstitution: body }),
    destroy: (api, params, id) => api.accountsInstitutionsDestroy({ ...params, id }),
    placeholder: gettext('e.g. Northwind Bank'),
    deleteNote: gettext('Its accounts are kept, no longer linked to an institution.'),
    createLabel: gettext('Create institution'),
  },
};

export default function NameModal({ kind, book, api, item = null, confirmDelete, onSaved, onDeleted, onClose }) {
  const spec = KINDS[kind];
  const [name, setName] = useState(item?.name || '');
  const [busy, errors, run] = useSubmit();

  const save = () =>
    run(async () => {
      const body = { name: name.trim() };
      const saved = item
        ? await spec.update(api, book.params, item.id, body)
        : await spec.create(api, book.params, body);
      onSaved(saved);
    });

  const remove = () =>
    run(async () => {
      await spec.destroy(api, book.params, item.id);
      onDeleted();
    });

  return (
    <ManageModal
      title={item ? interpolate(gettext('Edit “%s”'), [item.name]) : spec.newTitle}
      testId={`${kind}-modal`}
      onClose={onClose}
      onSave={save}
      onDelete={item ? remove : null}
      confirmDelete={confirmDelete}
      deleteNote={spec.deleteNote}
      saveLabel={item ? gettext('Save') : spec.createLabel}
      canSave={Boolean(name.trim())}
      formError={errors._form}
      busy={busy}
    >
      <Field label={gettext('Name')} error={errors.name}>
        <input
          type="text"
          name="name"
          className="input input-bordered w-full"
          value={name}
          maxLength={200}
          placeholder={spec.placeholder}
          onChange={(e) => setName(e.target.value)}
          data-autofocus
          data-testid={`${kind}-name-input`}
        />
      </Field>
    </ManageModal>
  );
}
