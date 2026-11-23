'use strict';

import React from 'react';
import { createRoot } from 'react-dom/client';
import ActualTooltip from './react/ActualTooltip';
import { readBook } from '../common/book';
import { getFeedPageApi } from '../bank_feed/bank_feed';

const book = readBook();

// The "Move to..." picker's accounts: every account but the budget buckets, as
// the bank feed's pickers list them (`bank_feed:bank-feed-pickers`). Empty until
// they load; the tooltips render again once they have.
let allAccounts = [];
getFeedPageApi(book.base)
  .pickers()
  .then((pickers) => {
    allAccounts = pickers.accounts;
    roots.forEach(render);
  })
  .catch((err) => console.error('Failed to load the account picker:', err));

// Every root we have mounted, with its element, so they can be torn down again.
// A redraw replaces the table (month-swap.js), and a root whose container has
// been detached keeps its tree — and its subscriptions — alive with nothing left
// to render into.
let roots = [];

mount();

// `budget:swapped` fires once replacement markup is in the document, so these
// elements are the new ones.
document.addEventListener('budget:swapped', mount);
// A month change in place keeps the elements and rewrites their data
// attributes: render each root again with the new month's figures.
document.addEventListener('budget:month-changed', () => roots.forEach(render));

function render({ root, element }) {
  const { categoryId, categoryName, amount, month } = element.dataset;
  root.render(
    <ActualTooltip
      // A new month is a new tooltip: its own transactions and total.
      key={month}
      categoryId={categoryId}
      categoryName={categoryName}
      amount={amount}
      month={month}
      allAccounts={allAccounts}
      book={book}
    />,
  );
}

function mount() {
  // Unmount asynchronously: React refuses to tear a root down while it is
  // rendering, and the swap may well have been triggered from inside one.
  const stale = roots;
  roots = [];
  if (stale.length) queueMicrotask(() => stale.forEach(({ root }) => root.unmount()));

  document.querySelectorAll('[data-actual-tooltip]').forEach((element) => {
    const entry = { root: createRoot(element), element };
    roots.push(entry);
    render(entry);
  });
}
