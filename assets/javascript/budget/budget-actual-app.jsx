/* globals SERVER_URL_BASE */
'use strict';

import React from 'react';
import { createRoot } from 'react-dom/client';
import ActualTooltip from './react/ActualTooltip';

// Get data from Django template
const allAccounts = JSON.parse(document.getElementById('all-accounts').textContent);
const apiUrls = JSON.parse(document.getElementById('api-urls').textContent);
const teamSlug = JSON.parse(document.getElementById('team-slug').textContent);

// Initialize all actual tooltips on the page
document.querySelectorAll('[data-actual-tooltip]').forEach((element) => {
  const root = createRoot(element);
  const categoryId = element.dataset.categoryId;
  const categoryName = element.dataset.categoryName;
  const amount = element.dataset.amount;
  const month = element.dataset.month;

  root.render(
    <ActualTooltip
      categoryId={categoryId}
      categoryName={categoryName}
      amount={amount}
      month={month}
      allAccounts={allAccounts}
      apiUrls={apiUrls}
      teamSlug={teamSlug}
    />
  );
});
