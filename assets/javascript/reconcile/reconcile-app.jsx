/* globals gettext */
import React from 'react';
import { createRoot } from 'react-dom/client';

import { readBook } from '../common/book';
import { getReconcileApi } from './api';
import ReconcileApp from './ReconcileApp';

const mount = document.getElementById('reconcile-app');
const book = readBook();
const accountId = Number(mount.dataset.accountId);
const api = getReconcileApi(book);

// The rows the bank feed handed over to tick (`?lines=1,2`).
const preselect = (new URLSearchParams(window.location.search).get('lines') || '')
  .split(',')
  .filter((part) => /^\d+$/.test(part.trim()))
  .map(Number);

// The page's pulse placeholder is the loading state until the page data is in.
api
  .page(accountId)
  .then((page) => {
    const props = {
      ...page,
      preselect_line_ids: preselect,
      book_base: book.base,
      // Pages built from the book base (the Django URLconf: `apps/reconciliation/urls.py`,
      // `apps/bank_feed/urls.py`, `apps/accounts/urls.py`).
      urls: {
        hub: `${book.base}reconcile/`,
        feed: `${book.base}bankfeed/`,
        account_detail: `${book.base}accounts/accounts/${accountId}/`,
      },
    };
    createRoot(mount).render(<ReconcileApp props={props} api={api} />);
  })
  .catch((err) => {
    createRoot(mount).render(
      <div className="app-card" role="alert">
        <p className="text-error">
          {gettext('This reconciliation could not be loaded.')} {err.message}
        </p>
      </div>,
    );
  });
