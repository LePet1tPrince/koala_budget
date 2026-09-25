import React from 'react';
import { createRoot } from 'react-dom/client';

import { getPortabilityApi } from './api';
import DataTransferWizard from './DataTransferWizard';

const mount = document.getElementById('data-transfer-app');
const props = JSON.parse(document.getElementById('portability-props').textContent);

createRoot(mount).render(<DataTransferWizard props={{ ...props, api: getPortabilityApi(props.urls) }} />);
