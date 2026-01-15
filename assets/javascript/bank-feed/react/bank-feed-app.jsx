/* globals SERVER_URL_BASE */
'use strict';

import BankFeedApp from './BankFeedApp';
import React from 'react';
import { createRoot } from 'react-dom/client';
import { getBankFeedApiClient } from './utils';

// Get data from Django template
const accounts = JSON.parse(document.getElementById('accounts').textContent);
const allAccounts = JSON.parse(document.getElementById('all-accounts').textContent);
const allPayees = JSON.parse(document.getElementById('all-payees').textContent);
const teamSlug = JSON.parse(document.getElementById('team-slug').textContent);

// Create API client
const apiClient = getBankFeedApiClient(teamSlug);

// Mount the React app
const domContainer = document.querySelector('#bank-feed-app');
const root = createRoot(domContainer);
root.render(
  <BankFeedApp
    accounts={accounts}
    allAccounts={allAccounts}
    allPayees={allPayees}
    teamSlug={teamSlug}
    apiClient={apiClient}
  />
);
