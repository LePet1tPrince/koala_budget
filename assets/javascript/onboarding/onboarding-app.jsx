/* globals gettext */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';

import { readBook } from '../common/book';
import { getOnboardingApi } from './api';
import OnboardingShell from './OnboardingShell';

/**
 * Loads the catalog and the state, then hands both to the takeover. The page
 * carries only its book (`book-base`); everything the flow shows comes from the API.
 */
const OnboardingApp = () => {
  const book = useMemo(() => readBook(), []);
  const api = useMemo(() => getOnboardingApi(book), [book]);
  const [loaded, setLoaded] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [catalog, page] = await Promise.all([api.catalog(), api.state()]);
      setLoaded({ catalog, page });
    } catch (e) {
      setError(e.message);
    }
  }, [api]);

  useEffect(() => {
    load();
  }, [load]);

  if (!loaded) {
    return (
      <div className="onboarding-backdrop is-open" data-testid="onboarding-loading">
        <div className="onboarding-panel app-card" role="dialog" aria-modal="true" aria-busy={!error}>
          {error ? (
            <div className="space-y-4">
              <div className="alert alert-error" data-testid="onboarding-error">
                <span>{error}</span>
              </div>
              <button type="button" className="btn btn-primary btn-sm" onClick={load}>
                {gettext('Try again')}
              </button>
            </div>
          ) : (
            <div className="space-y-3">
              <div className="skeleton h-4 w-32"></div>
              <div className="skeleton h-8 w-2/3"></div>
              <div className="skeleton h-16 w-full"></div>
            </div>
          )}
        </div>
      </div>
    );
  }

  const { catalog, page } = loaded;
  return (
    <OnboardingShell
      props={{
        api,
        questions: catalog.questions,
        state: page.state,
        firstName: page.firstName,
        homeUrl: book.base,
        ynabUrl: page.ynabImportEnabled ? `${book.base}ynab-import/` : '',
      }}
    />
  );
};

createRoot(document.getElementById('onboarding-app')).render(<OnboardingApp />);
