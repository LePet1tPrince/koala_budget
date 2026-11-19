import React from 'react';
import { createRoot } from 'react-dom/client';

import { bookFromBase } from '../common/book';
import { getOnboardingApi } from './api';
import TaskRail from './TaskRail';

/**
 * The server decides whether the rail belongs on the page (`onboarding_rail`) and
 * says which book it walks; the rail loads its tasks through the API once mounted.
 */
const mount = document.getElementById('task-rail-app');

if (mount) {
  const api = getOnboardingApi(bookFromBase(mount.dataset.bookBase));
  createRoot(mount).render(<TaskRail props={{ api, path: window.location.pathname }} />);
}
