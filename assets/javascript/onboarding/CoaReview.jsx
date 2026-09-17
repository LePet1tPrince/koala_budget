/* globals gettext */

import React, { useCallback, useEffect, useState } from 'react';

import Icon from '../common/Icon';

/**
 * Phase C: review the generated chart of accounts.
 *
 * The user sees what their answers produced, grouped by type, and can rename or
 * drop anything before it is written. Edits are held as a diff — removals,
 * renames, additions — and posted as such: the server owns the base chart and
 * only ever applies edits to its own generated set, so nothing here can invent an
 * account in a group no answer created.
 *
 * Props:
 * - sections: [{ type, label, blurb, groups: [{ name, accounts: [name] }], count }]
 * - edits / onEditsChange: the diff, lifted so the shell can post it on submit
 */

const AccountChip = ({ name, onRename, onRemove }) => {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(name);

  useEffect(() => setDraft(name), [name]);

  const commit = () => {
    const cleaned = draft.trim();
    setEditing(false);
    if (cleaned && cleaned !== name) {
      onRename(cleaned);
    } else {
      setDraft(name);
    }
  };

  if (editing) {
    return (
      <input
        autoFocus
        className="input input-bordered input-sm w-44"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit();
          if (e.key === 'Escape') {
            setDraft(name);
            setEditing(false);
          }
        }}
        data-testid={`coa-rename-${name}`}
      />
    );
  }

  return (
    <span className="coa-chip" data-testid={`coa-chip-${name}`}>
      <button
        type="button"
        className="coa-chip-name"
        onClick={() => setEditing(true)}
        title={gettext('Rename')}
      >
        {name}
      </button>
      <button
        type="button"
        className="coa-chip-remove"
        onClick={onRemove}
        aria-label={gettext('Remove {name}').replace('{name}', name)}
        data-testid={`coa-remove-${name}`}
      >
        <Icon name="times" className="w-3 h-3" />
      </button>
    </span>
  );
};

const AddAccount = ({ onAdd }) => {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState('');

  const commit = () => {
    const cleaned = draft.trim();
    if (cleaned) onAdd(cleaned);
    setDraft('');
    setOpen(false);
  };

  if (!open) {
    return (
      <button type="button" className="coa-add" onClick={() => setOpen(true)}>
        <Icon name="plus" className="w-3 h-3 mr-1" />
        {gettext('Add')}
      </button>
    );
  }

  return (
    <input
      autoFocus
      className="input input-bordered input-sm w-44"
      placeholder={gettext('Account name')}
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') commit();
        if (e.key === 'Escape') {
          setDraft('');
          setOpen(false);
        }
      }}
    />
  );
};

const CoaReview = ({ sections, edits, onEditsChange, loading, error }) => {
  const rename = useCallback(
    (from, to) => {
      // Renaming something already renamed must still key off the ORIGINAL name,
      // since that is what the server's generated chart calls it.
      const original = Object.keys(edits.renamed).find((k) => edits.renamed[k] === from) || from;
      onEditsChange({ ...edits, renamed: { ...edits.renamed, [original]: to } });
    },
    [edits, onEditsChange],
  );

  const remove = useCallback(
    (name) => {
      // An added account is dropped from the additions rather than recorded as a
      // removal — the server never generated it, so there is nothing to remove.
      const addedIndex = edits.added.findIndex((a) => a.name === name);
      if (addedIndex !== -1) {
        onEditsChange({ ...edits, added: edits.added.filter((_, i) => i !== addedIndex) });
        return;
      }
      const original = Object.keys(edits.renamed).find((k) => edits.renamed[k] === name) || name;
      const { [original]: _dropped, ...renamed } = edits.renamed;
      onEditsChange({ ...edits, removed: [...edits.removed, original], renamed });
    },
    [edits, onEditsChange],
  );

  const add = useCallback(
    (group, name) => onEditsChange({ ...edits, added: [...edits.added, { group, name }] }),
    [edits, onEditsChange],
  );

  const total = sections.reduce((sum, s) => sum + s.count, 0);

  return (
    <div data-testid="coa-review">
      <h2 className="text-xl font-semibold tracking-tight">{gettext('Here are your accounts')}</h2>
      <p className="mt-1 text-sm text-base-content/70">
        {gettext(
          'Built from your answers. Click a name to rename it, or remove anything you don’t need — you can always change this later.',
        )}
      </p>

      {error && (
        <div className="alert alert-error mt-4" data-testid="coa-error">
          <span>{error}</span>
        </div>
      )}

      <div className="coa-scroll mt-5">
        {loading ? (
          <div className="space-y-3">
            <div className="skeleton h-20 w-full"></div>
            <div className="skeleton h-20 w-full"></div>
          </div>
        ) : (
          sections.map((section) => (
            <section key={section.type} className="coa-section" data-testid={`coa-section-${section.type}`}>
              <div className="flex items-baseline justify-between gap-3">
                <h3 className="text-[0.6875rem] font-semibold uppercase tracking-[0.08em] text-base-content/70">
                  {section.label}
                </h3>
                <span className="text-xs text-base-content/45">{section.count}</span>
              </div>
              <p className="mt-0.5 text-xs text-base-content/70">{section.blurb}</p>

              {section.groups.map((group) => (
                <div key={group.name} className="mt-3">
                  <p className="mb-1.5 text-sm font-medium">{group.name}</p>
                  <div className="flex flex-wrap items-center gap-1.5">
                    {group.accounts.map((name) => (
                      <AccountChip
                        key={name}
                        name={name}
                        onRename={(to) => rename(name, to)}
                        onRemove={() => remove(name)}
                      />
                    ))}
                    <AddAccount onAdd={(name) => add(group.name, name)} />
                  </div>
                </div>
              ))}
            </section>
          ))
        )}
      </div>

      {!loading && (
        <p className="mt-4 text-sm text-base-content/70" data-testid="coa-count">
          {gettext('{n} accounts').replace('{n}', total)}
        </p>
      )}
    </div>
  );
};

export default CoaReview;
