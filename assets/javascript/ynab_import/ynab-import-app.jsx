import React from 'react';
import { createRoot } from 'react-dom/client';

import { getYnabApi } from './api';
import YnabImportWizard from './YnabImportWizard';

const mount = document.getElementById('ynab-import-app');
const props = JSON.parse(document.getElementById('ynab-props').textContent);

createRoot(mount).render(<YnabImportWizard props={{ ...props, api: getYnabApi(props.urls) }} />);
