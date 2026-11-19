import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';

import { readBook } from '../common/book';
import { getMonthlyReviewApi, loadReview, reviewUrls } from './api';
import ReviewApp from './ReviewApp';

/**
 * Loads the month's review (`GET …/monthly-review/api/review/?month=`) and hands
 * it to the app; a skeleton stands in while it is on its way.
 */
const ReviewLoader = ({ book, month }) => {
  const [loaded, setLoaded] = useState(null);
  const [error, setError] = useState('');
  const urls = reviewUrls(book.base, month);

  useEffect(() => {
    loadReview(book, month, urls)
      .then(setLoaded)
      .catch((err) => setError(err.message || 'The review could not be loaded.'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [month]);

  if (error) {
    return (
      <div role="alert" className="alert alert-error" data-testid="monthly-review-load-error">
        {error}
      </div>
    );
  }
  if (!loaded) {
    return <div className="skeleton h-96 w-full" data-testid="monthly-review-loading" />;
  }
  if (!loaded.review) {
    return (
      <div className="app-card">
        <p>There&apos;s no ledger activity yet for this month, so there&apos;s nothing to review.</p>
        <a href={urls.reportsHome} className="btn btn-outline btn-sm mt-4">
          Back to Reports
        </a>
      </div>
    );
  }
  return (
    <ReviewApp
      props={{ review: loaded.review, state: loaded.state, urls, api: getMonthlyReviewApi(book, loaded.month) }}
    />
  );
};

const mount = document.getElementById('monthly-review-app');
createRoot(mount).render(<ReviewLoader book={readBook()} month={mount.dataset.month} />);
