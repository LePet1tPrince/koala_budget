import React from 'react';
import { createRoot } from 'react-dom/client';
import Cookies from 'js-cookie';

import TaskRail from './TaskRail';

const mount = document.getElementById('task-rail-app');
const propsEl = document.getElementById('task-rail-props');

if (mount && propsEl) {
  const props = JSON.parse(propsEl.textContent);
  createRoot(mount).render(<TaskRail props={{ ...props, csrf: Cookies.get('csrftoken') }} />);
}
