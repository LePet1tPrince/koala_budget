'use strict';

import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import BudgetGrid from './react/BudgetGrid';
import { apiMonth, budget, errorMessage } from './budget-api';

/* globals gettext */

const t = (text) => (typeof gettext === 'function' ? gettext(text) : text);

/**
 * The grid's range is the address bar's (`?start=`, `?months=`); its rows,
 * amounts and reference actuals come from the budget API (`budgetGridRetrieve`).
 * Paging to another range is a navigation (BudgetGrid guards unsaved edits).
 */
const GridLoader = () => {
  const [grid, setGrid] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const { api, params } = budget();
    const query = new URL(window.location).searchParams;
    const start = query.get('start');
    const months = parseInt(query.get('months'), 10);
    api
      .budgetGridRetrieve({
        ...params,
        ...(start ? { start: apiMonth(start) } : {}),
        // Out of range is clamped, as the page always has.
        ...(Number.isFinite(months) ? { months: Math.max(1, Math.min(months, 24)) } : {}),
      })
      .then(setGrid)
      .catch(async (failure) => setError(await errorMessage(failure, t('Could not load the budget grid.'))));
  }, []);

  if (error) {
    return (
      <div role="alert" className="alert alert-error" data-testid="budget-grid-error">
        {error}
      </div>
    );
  }
  if (!grid) return <div className="skeleton h-96 w-full" aria-busy="true" aria-label={t('Loading…')} />;

  const saveChanges = async (changes) => {
    const { api, params } = budget();
    try {
      return await api.budgetGridSave({ ...params, gridSaveRequest: { changes } });
    } catch (failure) {
      throw new Error(await errorMessage(failure, t('Failed to save budgets')));
    }
  };

  return (
    <BudgetGrid
      months={grid.months.map((month) => ({ key: month.month, label: month.label }))}
      groups={grid.groups}
      actualModes={grid.actualModes}
      prevStart={grid.prevStart}
      nextStart={grid.nextStart}
      numMonths={grid.numMonths}
      saveChanges={saveChanges}
    />
  );
};

const el = document.getElementById('budget-grid');

if (el) {
  createRoot(el).render(<GridLoader />);
}
