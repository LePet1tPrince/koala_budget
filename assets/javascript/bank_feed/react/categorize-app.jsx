/* globals gettext */
'use strict';

import CategorizeMode from './CategorizeMode';
import React from 'react';
import { createRoot } from 'react-dom/client';
import { readBook } from '../../common/book';
import { getFeedPageApi } from '../bank_feed';

const book = readBook();
// Back to the Inbox (`bank_feed:bank_feed_home`).
const backUrl = `${book.base}bankfeed/`;

// The page's spinner is the loading state until the pickers are in.
const domContainer = document.querySelector('#categorize-app');

getFeedPageApi(book.base)
  .pickers()
  .then((pickers) => {
    createRoot(domContainer).render(
      <CategorizeMode
        book={book}
        allAccounts={pickers.accounts}
        allAccountGroups={pickers.account_groups}
        allPayees={pickers.payees}
        categoryUsage={pickers.category_usage}
        backUrl={backUrl}
      />,
    );
  })
  .catch((err) => {
    console.error('Failed to load categorize mode:', err);
    createRoot(domContainer).render(
      <div className="min-h-screen flex flex-col items-center justify-center gap-3 bg-base-200" role="alert">
        <p className="text-error">
          {gettext('Categorize mode could not be loaded.')} {err.message}
        </p>
        <a className="btn btn-sm" href={backUrl}>
          {gettext('Back to the bank feed')}
        </a>
      </div>,
    );
  });
