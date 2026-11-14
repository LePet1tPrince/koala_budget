import React from 'react';
import { createRoot } from 'react-dom/client';

import RulesApp from './RulesApp';
import { getRulesApi } from './api';

const mount = document.getElementById('rules-app');
const props = JSON.parse(document.getElementById('rules-props').textContent);

createRoot(mount).render(<RulesApp props={props} api={getRulesApi(props.api)} />);
