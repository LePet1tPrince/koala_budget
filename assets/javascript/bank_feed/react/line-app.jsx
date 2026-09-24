/* globals SERVER_URL_BASE */
'use strict';

import LineApp from './LineApp';
import React from 'react';
import { createRoot } from 'react-dom/client';
import { readBook } from '../../common/book';
import { getBankFeedApiClient, getPlaidApiClient, getJournalApiClient, getUploadApiHelpers } from '../bank_feed';

// Get data from Django template
const accounts = JSON.parse(document.getElementById('accounts').textContent);
const allAccounts = JSON.parse(document.getElementById('all-accounts').textContent);
const allPayees = JSON.parse(document.getElementById('all-payees').textContent);
const allAccountGroups = JSON.parse(document.getElementById('all-account-groups').textContent);
const book = readBook();

// Create API clients
const bankFeedClient = getBankFeedApiClient(SERVER_URL_BASE);
const plaidClient = getPlaidApiClient(SERVER_URL_BASE);
const journalClient = getJournalApiClient(SERVER_URL_BASE);
const uploadApi = getUploadApiHelpers(book.base);

// Mount the React app
const domContainer = document.querySelector('#line-app');
const root = createRoot(domContainer);
root.render(
  <LineApp
    accounts={accounts}
    allAccounts={allAccounts}
    allPayees={allPayees}
    allAccountGroups={allAccountGroups}
    book={book}
    bankFeedClient={bankFeedClient}
    plaidClient={plaidClient}
    journalClient={journalClient}
    uploadApi={uploadApi}
  />
);
