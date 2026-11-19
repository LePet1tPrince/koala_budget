/* globals gettext */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';

import { readBook } from '../common/book';
import { getYnabApi } from './api';
import YnabImportWizard from './YnabImportWizard';

/**
 * Asks the server where the wizard opens (`api/state/`: can this book take an
 * import, and is there one to resume), then hands that to the wizard. The page
 * carries only its book; every link here is built from its base.
 */
const YnabImportApp = () => {
  const book = useMemo(() => readBook(), []);
  const api = useMemo(() => getYnabApi(book), [book]);
  const [state, setState] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setState(await api.state());
    } catch (e) {
      setError(e.message);
    }
  }, [api]);

  useEffect(() => {
    load();
  }, [load]);

  if (error) {
    return (
      <div className="app-card max-w-xl space-y-4">
        <div className="alert alert-error" data-testid="ynab-error">
          <span>{error}</span>
        </div>
        <button type="button" className="btn btn-primary btn-sm" onClick={load}>
          {gettext('Try again')}
        </button>
      </div>
    );
  }

  if (!state) {
    return (
      <div className="app-card space-y-3" aria-busy="true" data-testid="ynab-loading">
        <div className="skeleton h-6 w-1/3"></div>
        <div className="skeleton h-24 w-full"></div>
      </div>
    );
  }

  return (
    <YnabImportWizard
      props={{
        api,
        canImport: state.canImport,
        resume: state.resume,
        bookName: state.bookName,
        homeUrl: book.base,
        accountsUrl: `${book.base}accounts/`,
        budgetUrl: `${book.base}budget/`,
        goalsUrl: `${book.base}budget/goals/`,
      }}
    />
  );
};

createRoot(document.getElementById('ynab-import-app')).render(<YnabImportApp />);
