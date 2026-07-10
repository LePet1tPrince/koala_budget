'use strict';

import React from 'react';
import { createRoot } from 'react-dom/client';
import BudgetGrid from './react/BudgetGrid';

const el = document.getElementById('budget-grid');

if (el) {
  const props = JSON.parse(document.getElementById('budget-grid-props').textContent);
  createRoot(el).render(<BudgetGrid {...props} />);
}
