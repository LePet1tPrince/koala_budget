/* globals SERVER_URL_BASE, gettext */
'use strict';

import LineApp from './LineApp';
import React from 'react';
import { createRoot } from 'react-dom/client';
import { readBook } from '../../common/book';
import { getBankFeedApiClient, getFeedPageApi, getPlaidApiClient, getUploadApiHelpers } from '../bank_feed';

const book = readBook();

// Create API clients
const bankFeedClient = getBankFeedApiClient(SERVER_URL_BASE);
const plaidClient = getPlaidApiClient(SERVER_URL_BASE);
const uploadApi = getUploadApiHelpers(book.base);
const pageApi = getFeedPageApi(book.base);

// The page's server-rendered skeleton is the loading state: React mounts over it
// once the feed accounts and the pickers are in.
const domContainer = document.querySelector('#line-app');

Promise.all([pageApi.feedAccounts(), pageApi.pickers()])
  .then(([accounts, pickers]) => {
    createRoot(domContainer).render(
      <LineApp
        accounts={accounts}
        allAccounts={pickers.accounts}
        allPayees={pickers.payees}
        allAccountGroups={pickers.account_groups}
        book={book}
        bankFeedClient={bankFeedClient}
        plaidClient={plaidClient}
        uploadApi={uploadApi}
      />,
    );
  })
  .catch((err) => {
    console.error('Failed to load the bank feed:', err);
    createRoot(domContainer).render(
      <section className="app-card" role="alert" data-testid="bank-feed-load-error">
        <p className="text-error">
          {gettext('The bank feed could not be loaded.')} {err.message}
        </p>
        <button type="button" className="btn btn-sm mt-3" onClick={() => window.location.reload()}>
          {gettext('Try again')}
        </button>
      </section>,
    );
  });
