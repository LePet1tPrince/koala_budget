'use strict';

import React from 'react';
import { createRoot } from 'react-dom/client';
import BudgetMonthPicker from './react/BudgetMonthPicker';

const el = document.getElementById('budget-month-picker');

if (el) {
  const initialMonth = el.dataset.month;
  createRoot(el).render(<BudgetMonthPicker initialMonth={initialMonth} />);
}
