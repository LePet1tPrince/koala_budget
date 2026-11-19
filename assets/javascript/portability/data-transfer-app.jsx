/* globals gettext */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';

import { readBook } from '../common/book';
import { getPortabilityApi } from './api';
import DataTransferWizard from './DataTransferWizard';

/**
 * Asks the server what the page opens on (`api/state/`), then hands that to the
 * wizard. The page carries only its book; every link here is built from its base.
 */
const DataTransferApp = () => {
  const book = useMemo(() => readBook(), []);
  const api = useMemo(() => getPortabilityApi(book), [book]);
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
      <div className="app-card space-y-4">
        <div className="alert alert-error">
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
      <div className="app-card space-y-3" aria-busy="true" data-testid="data-transfer-loading">
        <div className="skeleton h-6 w-1/3"></div>
        <div className="skeleton h-16 w-full"></div>
      </div>
    );
  }

  return (
    <DataTransferWizard
      props={{
        api,
        bookName: state.bookName,
        uncategorizedCount: state.uncategorizedCount,
        resume: state.resume,
        bankFeedUrl: `${book.base}bankfeed/`,
        homeUrl: book.base,
      }}
    />
  );
};

createRoot(document.getElementById('data-transfer-app')).render(<DataTransferApp />);
