import React, { useCallback, useMemo, useState } from 'react';
import { getUploadApiHelpers } from '../bank_feed';
import CreateAccountModal from './CSVUploadWizard/CreateAccountModal';

/**
 * Create an account from a category picker: `open(typedName)` shows the create
 * form prefilled with what was typed, and a saved account is handed to
 * `onCreated(account)` (the caller selects it) and kept in `created`, so a
 * picker built from a fixed `allAccounts` can offer it straight away.
 *
 * The account groups are fetched the first time the form opens, so a page that
 * never creates an account never asks for them. Render `modal` outside any
 * other `<dialog>`'s form; it is its own `<dialog>` and stacks on top.
 *
 * `book` null (a caller with no book to post to) disables it: `available` is false.
 */
export default function useCreateAccount(book, onCreated) {
  const api = useMemo(() => (book?.base ? getUploadApiHelpers(book.base) : null), [book]);
  const [draftName, setDraftName] = useState(null); // null = form closed
  const [groups, setGroups] = useState(null);
  const [created, setCreated] = useState([]);

  const open = useCallback(
    (name = '') => {
      if (!api) return;
      setDraftName(name);
      if (!groups) {
        api
          .getAccountGroups()
          .then(setGroups)
          .catch(() => setGroups([]));
      }
    },
    [api, groups]
  );

  const save = useCallback(
    async (name, accountGroupId) => {
      const account = await api.createAccount(name, accountGroupId);
      setCreated((prev) => [...prev, account]);
      setDraftName(null);
      onCreated?.(account);
      return account;
    },
    [api, onCreated]
  );

  const modal =
    draftName !== null ? (
      <CreateAccountModal
        allAccountGroups={groups}
        initialName={draftName}
        onSave={save}
        onCancel={() => setDraftName(null)}
      />
    ) : null;

  return { available: Boolean(api), created, open, modal, isOpen: draftName !== null };
}
