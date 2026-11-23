/* globals gettext, interpolate */
import React, { useEffect, useState } from 'react';

import { ManageModal, useSubmit } from './parts';

/**
 * Which of the book's asset and liability accounts an institution holds: a
 * checklist by type and group. Ticking an account held elsewhere moves it here
 * (its current institution is named beside it). Saves the whole list at once.
 */
export default function InstitutionAccountsModal({ book, api, institution, onSaved, onClose }) {
  const [sections, setSections] = useState(null);
  const [chosen, setChosen] = useState(new Set());
  const [loadError, setLoadError] = useState(null);
  const [busy, errors, run] = useSubmit();

  useEffect(() => {
    api
      .accountsInstitutionsAccountsRetrieve({ ...book.params, id: institution.id })
      .then((data) => {
        setSections(data.sections);
        const linked = data.sections.flatMap((s) => s.groups.flatMap((g) => g.choices.filter((c) => c.linked)));
        setChosen(new Set(linked.map((c) => c.id)));
      })
      .catch(() => setLoadError(gettext('The accounts could not be loaded. Please try again.')));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toggle = (id) =>
    setChosen((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const save = () =>
    run(async () => {
      await api.accountsInstitutionsAccountsUpdate({
        ...book.params,
        id: institution.id,
        institutionAccountsUpdate: { accountIds: [...chosen] },
      });
      onSaved();
    });

  const empty = sections && sections.every((s) => s.groups.length === 0);
  return (
    <ManageModal
      title={interpolate(gettext('Accounts at %s'), [institution.name])}
      testId="institution-accounts-modal"
      onClose={onClose}
      onSave={save}
      canSave={Boolean(sections)}
      formError={loadError || errors._form}
      busy={busy}
    >
      {!sections && !loadError && (
        <div className="flex justify-center py-8" aria-label={gettext('Loading')}>
          <span className="loading loading-spinner loading-md text-base-content/40" />
        </div>
      )}
      {empty && (
        <p className="text-sm text-base-content/70">{gettext('This book has no asset or liability accounts yet.')}</p>
      )}
      {sections &&
        sections
          .filter((s) => s.groups.length)
          .map((section) => (
            <div key={section.accountType}>
              <span className="label-text mb-1 block text-sm text-base-content/70">{section.label}</span>
              {section.groups.map((group) => (
                <div key={group.id} className="mb-2">
                  <p className="text-xs font-semibold uppercase tracking-wide text-base-content/70">{group.name}</p>
                  <ul className="mt-1">
                    {group.choices.map((choice) => (
                      <li key={choice.id}>
                        <label className="flex cursor-pointer items-center gap-3 rounded-lg px-2 py-1.5 hover:bg-base-200">
                          <input
                            type="checkbox"
                            className="checkbox checkbox-sm checkbox-primary"
                            checked={chosen.has(choice.id)}
                            onChange={() => toggle(choice.id)}
                            data-testid="institution-account-checkbox"
                          />
                          <span className="min-w-0 flex-1 truncate text-sm">{choice.name}</span>
                          {choice.elsewhere && !chosen.has(choice.id) && (
                            <span className="shrink-0 text-xs text-base-content/70">{choice.elsewhere.name}</span>
                          )}
                          {choice.elsewhere && chosen.has(choice.id) && (
                            <span className="shrink-0 text-xs text-warning">
                              {interpolate(gettext('moves from %s'), [choice.elsewhere.name])}
                            </span>
                          )}
                        </label>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          ))}
    </ManageModal>
  );
}
