import React from 'react';
import { createRoot } from 'react-dom/client';

import { readBook } from '../common/book';
import AccountsBoard from './react/AccountsBoard';

const mountNode = document.getElementById('accounts-board');
if (mountNode) {
  createRoot(mountNode).render(<AccountsBoard book={readBook()} />);
}
