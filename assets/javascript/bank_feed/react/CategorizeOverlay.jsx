/* globals gettext */
import React, { Suspense, lazy, useEffect, useState } from 'react';

import { getFeedPageApi } from '../bank_feed';

// Its own chunk: the Inbox does not pay for Categorize Mode until it is opened.
const CategorizeMode = lazy(() => import('./CategorizeMode'));

function Loading() {
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-base-200" data-testid="categorize-loading">
      <span className="loading loading-spinner loading-lg text-primary" />
    </div>
  );
}

/**
 * Categorize Mode over the Inbox, without a page load. The pickers are read
 * fresh each time it opens (how often each category is used, what goals have
 * left); the queue's scope is in the URL, which the caller has already set.
 */
export default function CategorizeOverlay({ book, backUrl, onExit }) {
  const [pickers, setPickers] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    getFeedPageApi(book.base)
      .pickers()
      .then(setPickers)
      .catch((err) => setError(err.message || gettext('Categorize mode could not be loaded.')));
  }, [book]);

  // The Inbox underneath does not scroll while the queue is over it.
  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previous;
    };
  }, []);

  if (error) {
    return (
      <div className="fixed inset-0 z-[60] flex flex-col items-center justify-center gap-3 bg-base-200" role="alert">
        <p className="text-error">{error}</p>
        <button type="button" className="btn btn-sm" onClick={onExit}>
          {gettext('Back to the Inbox')}
        </button>
      </div>
    );
  }
  if (!pickers) return <Loading />;
  return (
    <Suspense fallback={<Loading />}>
      <CategorizeMode
        book={book}
        allAccounts={pickers.accounts}
        allAccountGroups={pickers.account_groups}
        allPayees={pickers.payees}
        categoryUsage={pickers.category_usage}
        backUrl={backUrl}
        onExit={onExit}
      />
    </Suspense>
  );
}
