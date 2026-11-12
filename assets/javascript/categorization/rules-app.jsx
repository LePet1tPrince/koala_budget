'use strict';

import React from 'react';
import { createRoot } from 'react-dom/client';
import { readBook } from '../common/book';
import RulesApp from './RulesApp';

const props = JSON.parse(document.getElementById('rules-props').textContent);

createRoot(document.getElementById('rules-app')).render(<RulesApp book={readBook()} {...props} />);
