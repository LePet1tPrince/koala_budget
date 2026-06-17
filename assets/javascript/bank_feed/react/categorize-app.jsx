/* globals SERVER_URL_BASE */
'use strict';

import CategorizeMode from './CategorizeMode';
import React from 'react';
import { createRoot } from 'react-dom/client';

const allAccounts = JSON.parse(document.getElementById('all-accounts').textContent);
const allAccountGroups = JSON.parse(document.getElementById('all-account-groups').textContent);
const teamSlug = JSON.parse(document.getElementById('team-slug').textContent);
const backUrl = JSON.parse(document.getElementById('back-url').textContent);
const categorySuggestions = JSON.parse(document.getElementById('category-suggestions').textContent);

const domContainer = document.querySelector('#categorize-app');
const root = createRoot(domContainer);
root.render(
  <CategorizeMode
    teamSlug={teamSlug}
    allAccounts={allAccounts}
    allAccountGroups={allAccountGroups}
    categorySuggestions={categorySuggestions}
    backUrl={backUrl}
  />
);
