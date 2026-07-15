import React from 'react';
import { createRoot } from 'react-dom/client';

import AccountsBoard from './react/AccountsBoard';

const mountNode = document.getElementById('accounts-board');
if (mountNode) {
  const props = JSON.parse(document.getElementById('accounts-board-props').textContent);
  createRoot(mountNode).render(<AccountsBoard {...props} />);
}
