/* globals gettext */
import React from 'react';
import { createRoot } from 'react-dom/client';

import { readBook } from '../common/book';
import RulesApp from './RulesApp';
import { getRulesApi } from './api';

const mount = document.getElementById('rules-app');
const book = readBook();
const api = getRulesApi(book);

// The page's pulse placeholder is the loading state until the page data is in.
api
  .page()
  .then((page) => {
    const props = { ...page, book_base: book.base, feed_url: `${book.base}bankfeed/` };
    createRoot(mount).render(<RulesApp props={props} api={api} />);
  })
  .catch((err) => {
    createRoot(mount).render(
      <p className="text-error" role="alert">
        {gettext('The rules could not be loaded.')} {err.message}
      </p>,
    );
  });
