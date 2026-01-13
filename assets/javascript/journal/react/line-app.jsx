/* globals SERVER_URL_BASE */
'use strict';

import LineApp from './LineApp';
import React from 'react';
import { createRoot } from 'react-dom/client';

// Get data from Django template
const accounts = JSON.parse(document.getElementById('accounts').textContent);
const allAccounts = JSON.parse(document.getElementById('all-accounts').textContent);
const allPayees = JSON.parse(document.getElementById('all-payees').textContent);
const teamSlug = JSON.parse(document.getElementById('team-slug').textContent);

// Mount the React app
const domContainer = document.querySelector('#line-app');
const root = createRoot(domContainer);
root.render(
  <LineApp
    accounts={accounts}
    allAccounts={allAccounts}
    allPayees={allPayees}
    teamSlug={teamSlug}
  />
);
