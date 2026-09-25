import React from 'react';
import { createRoot } from 'react-dom/client';

import { getReconcileApi } from './api';
import ReconcileApp from './ReconcileApp';

const mount = document.getElementById('reconcile-app');
const props = JSON.parse(document.getElementById('reconcile-props').textContent);

createRoot(mount).render(<ReconcileApp props={props} api={getReconcileApi(props.urls.api)} />);
