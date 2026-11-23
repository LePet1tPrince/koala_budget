/* globals gettext */
import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';

import { readBook } from '../common/book';
import { getAccountsApi } from './accountsApi';
import AccountModal from './react/manage/AccountModal';
import GroupModal from './react/manage/GroupModal';
import InstitutionAccountsModal from './react/manage/InstitutionAccountsModal';
import NameModal from './react/manage/NameModal';

/**
 * The Manage pages that are still server-rendered (the Groups, Payees and
 * Institutions lists, their detail pages, an account's page and the board's
 * "New account") open the same React editors the accounts board uses.
 *
 * A trigger is a link whose href is the no-JS form page:
 *   data-manage-modal   account | group | payee | institution | institution-accounts
 *   data-id, data-name  the item being edited (none: create)
 *   data-account-type, data-account-group, data-institution   defaults for a new account/group
 *   data-confirm-delete opens the editor with its Delete already asked
 *   data-after-save     "reload" stays on this page; otherwise a new item opens its own page
 *   data-after-delete   where to go once the item is deleted (default: reload)
 */
const book = readBook();
const api = getAccountsApi();

const detailUrl = {
  account: (id) => `${book.base}accounts/accounts/${id}/`,
  group: (id) => `${book.base}accounts/account-groups/${id}/`,
  payee: (id) => `${book.base}accounts/payees/${id}/`,
  institution: (id) => `${book.base}accounts/institutions/${id}/`,
};

function Editors() {
  const [open, setOpen] = useState(null); // the clicked trigger's dataset + whether it edits

  useEffect(() => {
    const onClick = (event) => {
      const trigger = event.target.closest('[data-manage-modal]');
      if (!trigger || event.defaultPrevented || event.metaKey || event.ctrlKey || event.shiftKey) return;
      event.preventDefault();
      setOpen({ ...trigger.dataset });
    };
    document.addEventListener('click', onClick);
    return () => document.removeEventListener('click', onClick);
  }, []);

  if (!open) return null;
  const kind = open.manageModal;
  const id = open.id ? Number(open.id) : null;
  const close = () => setOpen(null);
  const saved = (item) => {
    if (id || open.afterSave === 'reload' || !detailUrl[kind]) window.location.reload();
    else window.location.assign(detailUrl[kind](item.id));
  };
  const deleted = () => {
    if (open.afterDelete) window.location.assign(open.afterDelete);
    else window.location.reload();
  };
  const common = {
    book,
    api,
    onClose: close,
    onSaved: saved,
    onDeleted: deleted,
    confirmDelete: 'confirmDelete' in open,
  };

  if (kind === 'account') {
    const defaults = { accountType: open.accountType, accountGroup: open.accountGroup, institution: open.institution };
    return <AccountModal {...common} accountId={id} defaults={defaults} />;
  }
  if (kind === 'group') return <GroupModal {...common} groupId={id} defaults={{ accountType: open.accountType }} />;
  if (kind === 'payee' || kind === 'institution') {
    return <NameModal {...common} kind={kind} item={id ? { id, name: open.name } : null} />;
  }
  if (kind === 'institution-accounts') {
    return (
      <InstitutionAccountsModal
        {...common}
        institution={{ id, name: open.name }}
        onSaved={() => window.location.reload()}
      />
    );
  }
  // eslint-disable-next-line no-console
  console.error(gettext('Unknown editor'), kind);
  return null;
}

const mount = document.createElement('div');
document.body.appendChild(mount);
createRoot(mount).render(<Editors />);
