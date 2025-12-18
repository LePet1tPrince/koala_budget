/* globals SERVER_URL_BASE */
'use strict';

import JournalApp from './JournalApp';
import React from 'react';
import { createRoot } from 'react-dom/client';

// Get data from Django template
const accounts = JSON.parse(document.getElementById('accounts').textContent);
const allAccounts = JSON.parse(document.getElementById('all-accounts').textContent);
const allPayees = JSON.parse(document.getElementById('all-payees').textContent);
const apiUrls = JSON.parse(document.getElementById('api-urls').textContent);
const teamSlug = JSON.parse(document.getElementById('team-slug').textContent);

// Mount the React app
const domContainer = document.querySelector('#journal-app');
const root = createRoot(domContainer);
root.render(
  // <div>This is a test javascript thing</div>
  <JournalApp
    accounts={accounts}
    allAccounts={allAccounts}
    allPayees={allPayees}
    apiUrls={apiUrls}
    teamSlug={teamSlug}
  />
);
