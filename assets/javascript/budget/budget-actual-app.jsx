/* globals SERVER_URL_BASE */
'use strict';

import React from 'react';
import { createRoot } from 'react-dom/client';
import ActualTooltip from './react/ActualTooltip';

// Get data from Django template
const allAccounts = JSON.parse(document.getElementById('all-accounts').textContent);
const apiUrls = JSON.parse(document.getElementById('api-urls').textContent);
const teamSlug = JSON.parse(document.getElementById('team-slug').textContent);

// Every root we have mounted, so they can be torn down again. Changing month
// replaces the table without reloading the page (month-swap.js), and a root
// whose container has been detached keeps its tree — and its subscriptions —
// alive with nothing left to render into.
let roots = [];

mount();

// `budget:swapped` fires once the replacement markup is in the document, so
// these elements are the new ones.
document.addEventListener('budget:swapped', mount);

function mount() {
  // Unmount asynchronously: React refuses to tear a root down while it is
  // rendering, and the swap may well have been triggered from inside one.
  const stale = roots;
  roots = [];
  if (stale.length) queueMicrotask(() => stale.forEach((root) => root.unmount()));

  // Initialize all actual tooltips on the page
  document.querySelectorAll('[data-actual-tooltip]').forEach((element) => {
    const root = createRoot(element);
    roots.push(root);
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
}
