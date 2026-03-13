'use strict';

import React from 'react';
import { createRoot } from 'react-dom/client';
import AccountBulkEdit from './AccountBulkEdit';

const apiUrls = JSON.parse(document.getElementById('api-urls').textContent);

const container = document.getElementById('accounts-bulk-edit-app');
createRoot(container).render(<AccountBulkEdit apiUrls={apiUrls} />);
