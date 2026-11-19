'use strict';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';

import TransactionEditModal from '../transactions/TransactionEditModal';
import { getTransactionsApi } from '../transactions/transactionsApi';
import Toast from '../common/Toast';
import { readBook } from '../common/book';

/**
 * The Transactions page's edit modal, on an account's server-rendered activity
 * table (`reports/components/account_activity_section.html`).
 *
 * A row carrying `data-entry-id` opens the modal on that journal entry; links
 * inside the row (linked account, payee) keep navigating. Every write reloads
 * the page: the running balance, totals and charts are all rendered server-side,
 * and patching one row would leave them disagreeing with it.
 */
const AccountActivityEditor = ({ table }) => {
  const book = useMemo(() => readBook(), []);
  const api = useMemo(() => getTransactionsApi(book.base), [book.base]);
  // The modal's pickers (`journal:transaction-pickers`), asked for once when the
  // page opens; the first row click waits for them only if they are still in flight.
  const pickers = useMemo(() => api.pickers(), [api]);
  const [allAccounts, setAllAccounts] = useState([]);
  const [allPayees, setAllPayees] = useState([]);
  const [editing, setEditing] = useState([]);
  const [toast, setToast] = useState(null);

  useEffect(() => {
    pickers
      .then((loaded) => {
        setAllAccounts(loaded.accounts);
        setAllPayees(loaded.payees);
      })
      .catch(() => {});
  }, [pickers]);

  const openEditor = useCallback(
    async (entryId) => {
      try {
        // The table row is a display projection; the detail fetch carries the
        // ids, split legs and capabilities the modal opens on.
        const [detail] = await Promise.all([api.fetchDetail(entryId), pickers]);
        setEditing([detail]);
      } catch (err) {
        setToast({ message: err.message, severity: 'error' });
      }
    },
    [api, pickers],
  );

  useEffect(() => {
    const onClick = (event) => {
      const button = event.target.closest('[data-edit-entry]');
      if (button) {
        openEditor(button.dataset.editEntry);
        return;
      }
      // A link in the row navigates; only a click on the row itself edits.
      if (event.target.closest('a, button, input')) return;
      const row = event.target.closest('tr[data-entry-id]');
      if (row) openEditor(row.dataset.entryId);
    };
    table.addEventListener('click', onClick);
    return () => table.removeEventListener('click', onClick);
  }, [table, openEditor]);

  const reload = () => window.location.reload();

  return (
    <>
      <TransactionEditModal
        open={editing.length > 0}
        transactions={editing}
        allAccounts={allAccounts}
        allPayees={allPayees}
        book={book}
        onSave={async (ids, updates) => {
          await api.saveEdits(ids, updates);
          reload();
        }}
        onDelete={async (ids) => {
          await api.deleteTransactions(ids);
          reload();
        }}
        onSetStatus={async (ids, statusValue) => {
          await api.setStatus(ids, statusValue);
          reload();
        }}
        onClose={() => setEditing([])}
        onAccountCreated={(account) =>
          setAllAccounts((prev) => (prev.some((a) => a.id === account.id) ? prev : [...prev, account]))
        }
      />
      <Toast
        open={Boolean(toast)}
        message={toast?.message || ''}
        severity={toast?.severity || 'info'}
        onClose={() => setToast(null)}
        testId="account-activity-toast"
      />
    </>
  );
};

const container = document.getElementById('account-activity-editor');
const table = document.querySelector('[data-testid="account-activity-table"]');
if (container && table) {
  createRoot(container).render(<AccountActivityEditor table={table} />);
}
