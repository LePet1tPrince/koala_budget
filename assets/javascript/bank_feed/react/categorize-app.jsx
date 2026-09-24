/* globals SERVER_URL_BASE */
'use strict';

import CategorizeMode from './CategorizeMode';
import React from 'react';
import { createRoot } from 'react-dom/client';
import { readBook } from '../../common/book';

const allAccounts = JSON.parse(document.getElementById('all-accounts').textContent);
const allAccountGroups = JSON.parse(document.getElementById('all-account-groups').textContent);
const allPayees = JSON.parse(document.getElementById('all-payees').textContent);
const book = readBook();
const backUrl = JSON.parse(document.getElementById('back-url').textContent);

const domContainer = document.querySelector('#categorize-app');
const root = createRoot(domContainer);
root.render(
  <CategorizeMode
    book={book}
    allAccounts={allAccounts}
    allAccountGroups={allAccountGroups}
    allPayees={allPayees}
    backUrl={backUrl}
  />
);
