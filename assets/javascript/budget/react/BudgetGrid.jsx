import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import Cookies from 'js-cookie';

import AmountInput from '../../common/AmountInput';
import Modal from '../../common/Modal';
import { evaluateAmount, sanitizeAmount } from '../../common/amount';

const cellKey = (categoryId, monthKey) => `${categoryId}|${monthKey}`;

/**
 * Parse spreadsheet clipboard text (TSV from Excel / Google Sheets) into a
 * matrix of cells. Trailing empty row (Excel adds one) is dropped.
 */
export function parseClipboardMatrix(text) {
  const rows = text.replace(/\r\n?/g, '\n').split('\n');
  while (rows.length > 0 && rows[rows.length - 1] === '') rows.pop();
  return rows.map((row) => row.split('\t'));
}

/** Numeric value of a cell for dirty comparison; empty/invalid → null. */
const numericValue = (text) => {
  const evaluated = evaluateAmount(text);
  return evaluated === null ? null : parseFloat(evaluated);
};

const currencyFmt = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// The actuals mode is a per-viewer preference; storage may be unavailable.
const ACTUAL_MODE_STORAGE_KEY = 'budget-grid-actual-mode';
const readStoredMode = () => {
  try {
    return window.localStorage.getItem(ACTUAL_MODE_STORAGE_KEY);
  } catch {
    return null;
  }
};
const storeMode = (mode) => {
  try {
    window.localStorage.setItem(ACTUAL_MODE_STORAGE_KEY, mode);
  } catch {
    // Not remembered; the picker still works for this page view.
  }
};

/**
 * Multi-month budget grid editor. Rows are budget categories (grouped by
 * account group), columns are months. Supports pasting a block of values
 * straight from Excel / Google Sheets: the paste anchors at the focused cell
 * and fills right and down, exactly like a spreadsheet.
 */
const BudgetGrid = ({ months, groups, actualModes = [], prevStart, nextStart, numMonths, saveUrl }) => {
  // Flat row list in display order — paste fills straight down this list,
  // skipping group header rows (which aren't data rows).
  const flatRows = useMemo(
    () => groups.flatMap((group) => group.rows.map((row) => ({ ...row, groupType: group.type }))),
    [groups],
  );

  const buildInitialValues = useCallback(() => {
    const initial = {};
    flatRows.forEach((row) => {
      months.forEach((month) => {
        initial[cellKey(row.id, month.key)] = row.amounts[month.key] ?? '';
      });
    });
    return initial;
  }, [flatRows, months]);

  const [savedValues, setSavedValues] = useState(buildInitialValues);
  const [values, setValues] = useState(buildInitialValues);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState(null); // {type: 'success'|'error', message}
  const [menuOpenKey, setMenuOpenKey] = useState(null);
  const [actualMode, setActualMode] = useState(() => {
    const stored = readStoredMode();
    return actualModes.some((mode) => mode.key === stored) ? stored : actualModes[0]?.key;
  });
  const containerRef = useRef(null);
  const categoryHeaderRef = useRef(null);
  // The actuals column is frozen beside the category column, so its sticky
  // offset is the category column's rendered width (which follows the longest name).
  const [actualsLeft, setActualsLeft] = useState(0);

  useLayoutEffect(() => {
    const th = categoryHeaderRef.current;
    if (!th) return undefined;
    const measure = () => setActualsLeft(th.getBoundingClientRect().width);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(th);
    return () => observer.disconnect();
  }, []);

  const currentMode = actualModes.find((mode) => mode.key === actualMode);
  const changeActualMode = (mode) => {
    setActualMode(mode);
    storeMode(mode);
  };

  const isDirty = useCallback(
    (key) => numericValue(values[key]) !== numericValue(savedValues[key]),
    [values, savedValues],
  );

  const dirtyKeys = useMemo(
    () => Object.keys(values).filter((key) => isDirty(key)),
    [values, isDirty],
  );

  // Where the user asked to go while the "unsaved changes" dialog is up.
  const [leaveTo, setLeaveTo] = useState(null);
  // Set once the user has chosen to leave, so the browser's own prompt doesn't follow ours.
  const leaving = useRef(false);
  const hasChanges = dirtyKeys.length > 0;
  // The dialog's count must not drop to 0 in the moment between "Save and continue"
  // succeeding and the page unloading.
  const pendingCount = useRef(0);
  if (hasChanges) pendingCount.current = dirtyKeys.length;
  const leaveCount = pendingCount.current;

  useEffect(() => {
    if (!hasChanges) return undefined;
    // Any link on the page (Back to Budget, the sidebar, …) gets our dialog.
    const onClick = (e) => {
      const link = e.target.closest?.('a[href]');
      if (!link || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      if (link.target && link.target !== '_self') return;
      if (link.hasAttribute('download') || link.hasAttribute('data-dialog')) return;
      const url = new URL(link.href, window.location.href);
      if (url.origin !== window.location.origin) return;
      // Same-page anchors don't unload anything.
      if (url.pathname === window.location.pathname && url.search === window.location.search && url.hash) return;
      e.preventDefault();
      setLeaveTo(url.toString());
    };
    // Closing the tab, reloading and the browser's Back button can't be intercepted:
    // there the browser only ever shows its own prompt, so that stays as the fallback.
    const warn = (e) => {
      if (leaving.current) return;
      e.preventDefault();
      e.returnValue = '';
    };
    document.addEventListener('click', onClick);
    window.addEventListener('beforeunload', warn);
    return () => {
      document.removeEventListener('click', onClick);
      window.removeEventListener('beforeunload', warn);
    };
  }, [hasChanges]);

  // `showModal()` focuses the first button; put focus on the safe choice instead.
  const keepEditingRef = useRef(null);
  useEffect(() => {
    if (leaveTo !== null) keepEditingRef.current?.focus();
  }, [leaveTo]);

  const goTo = (url) => {
    leaving.current = true;
    window.location.href = url;
  };

  useEffect(() => {
    if (!toast) return undefined;
    const timer = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(timer);
  }, [toast]);

  // Close the cell menu on any click outside of it
  useEffect(() => {
    if (!menuOpenKey) return undefined;
    const handleClick = (e) => {
      if (!e.target.closest(`[data-menu-key="${menuOpenKey}"]`)) setMenuOpenKey(null);
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [menuOpenKey]);

  const setCell = (rowIdx, colIdx, text) => {
    const key = cellKey(flatRows[rowIdx].id, months[colIdx].key);
    setValues((prev) => ({ ...prev, [key]: text }));
  };

  const handlePaste = (e, rowIdx, colIdx) => {
    const text = e.clipboardData?.getData('text/plain');
    if (!text) return;
    const matrix = parseClipboardMatrix(text);
    if (matrix.length === 0) return;
    e.preventDefault();

    if (matrix.length === 1 && matrix[0].length === 1) {
      // Single cell: replace the input's value with the sanitized number
      // (or the raw text if it isn't numeric, so the user sees what happened)
      setCell(rowIdx, colIdx, sanitizeAmount(matrix[0][0]) ?? matrix[0][0]);
      return;
    }

    // Block paste: anchor at the focused cell, fill right and down.
    // Cells that fall outside the grid are ignored; non-numeric cells
    // (e.g. a pasted header row or label column) leave the target untouched.
    const updates = {};
    matrix.forEach((cells, dRow) => {
      const r = rowIdx + dRow;
      if (r >= flatRows.length) return;
      cells.forEach((cell, dCol) => {
        const c = colIdx + dCol;
        if (c >= months.length) return;
        const sanitized = sanitizeAmount(cell);
        if (sanitized === null) return;
        updates[cellKey(flatRows[r].id, months[c].key)] = sanitized;
      });
    });
    setValues((prev) => ({ ...prev, ...updates }));
  };

  const focusCell = (rowIdx, colIdx) => {
    const input = containerRef.current?.querySelector(
      `input[data-row="${rowIdx}"][data-col="${colIdx}"]`,
    );
    if (input) {
      input.focus();
      input.select();
    }
  };

  const handleKeyDown = (e, rowIdx, colIdx) => {
    let target = null;
    if (e.key === 'Enter') {
      target = [e.shiftKey ? rowIdx - 1 : rowIdx + 1, colIdx];
    } else if (e.key === 'ArrowDown') {
      target = [rowIdx + 1, colIdx];
    } else if (e.key === 'ArrowUp') {
      target = [rowIdx - 1, colIdx];
    } else if (e.key === 'Escape') {
      const key = cellKey(flatRows[rowIdx].id, months[colIdx].key);
      setValues((prev) => ({ ...prev, [key]: savedValues[key] }));
      return;
    }
    if (target) {
      e.preventDefault();
      const [r, c] = target;
      if (r >= 0 && r < flatRows.length) focusCell(r, c);
    }
  };

  const handleSave = async () => {
    const changes = dirtyKeys.map((key) => {
      const [categoryId, monthKey] = key.split('|');
      return {
        category_id: parseInt(categoryId, 10),
        month: monthKey,
        // A cleared cell that previously had a value is saved as 0
        amount: evaluateAmount(values[key]) ?? '0.00',
      };
    });
    setSaving(true);
    try {
      const response = await fetch(saveUrl, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': Cookies.get('csrftoken'),
        },
        body: JSON.stringify({ changes }),
      });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.error || 'Failed to save budgets');
      }
      const result = await response.json();
      // Normalize inputs to what was saved and mark everything clean
      setValues((prev) => {
        const next = { ...prev };
        changes.forEach((change) => {
          next[cellKey(change.category_id, change.month)] = change.amount;
        });
        setSavedValues(next);
        return next;
      });
      setToast({ type: 'success', message: `Saved ${result.saved} budget amount${result.saved === 1 ? '' : 's'}.` });
      return true;
    } catch (error) {
      setToast({ type: 'error', message: error.message });
      return false;
    } finally {
      setSaving(false);
    }
  };

  const handleDiscard = () => setValues(savedValues);

  const saveAndLeave = async () => {
    const target = leaveTo;
    if (await handleSave()) {
      goTo(target);
    } else {
      // The error toast says why; stay so nothing typed is lost.
      setLeaveTo(null);
    }
  };

  // Copy a cell's value to other months in the same calendar year for the
  // same category. `mode: 'year'` fills the whole year; `mode: 'forward'`
  // fills only that month and later ones, leaving earlier months untouched.
  // Only edits in-memory — the user still has to Save to persist it.
  const applyToYear = (rowIdx, colIdx, mode) => {
    const row = flatRows[rowIdx];
    const sourceMonth = months[colIdx];
    const year = sourceMonth.key.slice(0, 4);
    const sourceValue = values[cellKey(row.id, sourceMonth.key)];
    setValues((prev) => {
      const next = { ...prev };
      months.forEach((month, idx) => {
        if (month.key.slice(0, 4) !== year) return;
        if (mode === 'forward' && idx < colIdx) return;
        next[cellKey(row.id, month.key)] = sourceValue;
      });
      return next;
    });
    setMenuOpenKey(null);
  };

  const navigate = (start) => {
    const url = new URL(window.location);
    url.searchParams.set('start', start);
    if (hasChanges) {
      setLeaveTo(url.toString());
    } else {
      window.location.href = url.toString();
    }
  };

  // Live per-month totals by section (income / expense), so a big paste can
  // be sanity-checked against the source spreadsheet at a glance.
  const totalsByType = useMemo(() => {
    const totals = { income: months.map(() => 0), expense: months.map(() => 0) };
    flatRows.forEach((row) => {
      const bucket = totals[row.groupType === 'income' ? 'income' : 'expense'];
      months.forEach((month, colIdx) => {
        bucket[colIdx] += numericValue(values[cellKey(row.id, month.key)]) ?? 0;
      });
    });
    return totals;
  }, [flatRows, months, values]);

  // Actuals for the selected mode: null means the mode's window has no complete month.
  const actualFor = (row) => {
    const raw = row.actuals?.[actualMode];
    return raw === null || raw === undefined ? null : parseFloat(raw);
  };
  const actualTotals = { income: null, expense: null };
  flatRows.forEach((row) => {
    const value = actualFor(row);
    if (value === null) return;
    const type = row.groupType === 'income' ? 'income' : 'expense';
    actualTotals[type] = (actualTotals[type] ?? 0) + value;
  });
  const formatActual = (value) => (value === null ? '—' : currencyFmt.format(value));
  const actualsCellClass = 'sticky text-right font-mono pr-3 border-r border-base-300 whitespace-nowrap';
  const actualsStyle = { left: actualsLeft };

  const rangeLabel = `${months[0].label} – ${months[months.length - 1].label}`;
  const rowIndexById = useMemo(() => new Map(flatRows.map((row, idx) => [row.id, idx])), [flatRows]);

  return (
    <div>
      {/* Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
        <div className="flex items-center gap-1">
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => navigate(prevStart)} aria-label={`Previous ${numMonths} months`}>
            «
          </button>
          <span className="font-bold text-lg px-1">{rangeLabel}</span>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => navigate(nextStart)} aria-label={`Next ${numMonths} months`}>
            »
          </button>
        </div>
        <div className="text-sm opacity-70">
          Tip: copy a block of cells in Excel or Google Sheets, click the top-left target cell here, and paste.
        </div>
      </div>

      {/* Grid */}
      <div ref={containerRef} className="overflow-auto bg-base-100 rounded-lg shadow max-h-[calc(100vh-16rem)]" data-testid="budget-grid">
        <table className="table table-sm w-full border-separate border-spacing-0">
          <thead>
            <tr>
              <th ref={categoryHeaderRef} className="sticky top-0 left-0 z-30 bg-base-200 min-w-48">Category</th>
              <th
                className="sticky top-0 z-30 bg-base-200 text-right align-bottom border-r border-base-300 min-w-36"
                style={actualsStyle}
                data-testid="budget-grid-actuals-header"
              >
                <label className="flex flex-col items-end gap-1">
                  <span className="sr-only">Actuals shown</span>
                  <select
                    className="select select-xs w-40"
                    value={actualMode ?? ''}
                    onChange={(e) => changeActualMode(e.target.value)}
                    data-testid="budget-grid-actuals-mode"
                  >
                    {actualModes.map((mode) => (
                      <option key={mode.key} value={mode.key}>{mode.label}</option>
                    ))}
                  </select>
                  <span className="text-xs font-normal opacity-70" data-testid="budget-grid-actuals-detail">
                    {currentMode?.detail}
                  </span>
                </label>
              </th>
              {months.map((month) => (
                <th key={month.key} className="sticky top-0 z-20 bg-base-200 text-right min-w-28">{month.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {flatRows.length === 0 && (
              <tr>
                <td colSpan={months.length + 2} className="text-center opacity-60 py-8" data-testid="budget-grid-empty">
                  No budget categories found. Please add income or expense accounts first.
                </td>
              </tr>
            )}
            {groups.map((group) => (
              <React.Fragment key={group.name}>
                <tr>
                  <td className="sticky left-0 z-10 bg-base-200 font-bold" data-testid="budget-grid-group">{group.name}</td>
                  <td className="sticky z-10 bg-base-200 border-r border-base-300" style={actualsStyle} />
                  <td colSpan={months.length} className="bg-base-200" />
                </tr>
                {group.rows.map((row) => {
                  const r = rowIndexById.get(row.id);
                  return (
                    <tr key={row.id} data-testid="budget-grid-row">
                      <td className="sticky left-0 z-10 bg-base-100 pl-6 whitespace-nowrap">{row.name}</td>
                      <td
                        className={`${actualsCellClass} z-10 bg-base-100 ${actualFor(row) ? 'text-base-content/70' : 'text-base-content/40'}`}
                        style={actualsStyle}
                        data-testid="budget-grid-actual"
                      >
                        {formatActual(actualFor(row))}
                      </td>
                      {months.map((month, colIdx) => {
                        const key = cellKey(row.id, month.key);
                        const dirty = isDirty(key);
                        return (
                          <td key={month.key} className="p-1">
                            <div className="relative">
                              <AmountInput
                                strict
                                className={`input input-bordered input-sm w-full min-w-24 text-right font-mono ${dirty ? 'input-warning bg-warning/10' : ''}`}
                                value={values[key]}
                                data-row={r}
                                data-col={colIdx}
                                aria-label={`${row.name} ${month.label}`}
                                onValueChange={(next) => setValues((prev) => ({ ...prev, [key]: next }))}
                                onPaste={(e) => handlePaste(e, r, colIdx)}
                                onKeyDown={(e) => handleKeyDown(e, r, colIdx)}
                                onFocus={(e) => e.target.select()}
                              />
                              {dirty && (
                                <div
                                  className="absolute -top-2 -right-2 z-30"
                                  data-menu-key={key}
                                >
                                  <button
                                    type="button"
                                    tabIndex={-1}
                                    className="flex items-center justify-center w-5 h-5 rounded-full border border-base-300 bg-base-100 shadow text-xs leading-none hover:bg-base-200"
                                    aria-label={`More options for ${row.name} ${month.label}`}
                                    data-testid="budget-grid-cell-menu-btn"
                                    onMouseDown={(e) => e.preventDefault()}
                                    onClick={() => setMenuOpenKey((prevKey) => (prevKey === key ? null : key))}
                                  >
                                    ⋮
                                  </button>
                                  {menuOpenKey === key && (
                                    <ul
                                      className="dropdown-content menu menu-sm absolute right-0 top-full mt-1 z-40 w-52 bg-base-100 rounded-box shadow border border-base-300 p-1"
                                      data-testid="budget-grid-cell-menu"
                                    >
                                      <li>
                                        <button
                                          type="button"
                                          data-testid="budget-grid-apply-year"
                                          onClick={() => applyToYear(r, colIdx, 'year')}
                                        >
                                          Apply to entire year
                                        </button>
                                      </li>
                                      <li>
                                        <button
                                          type="button"
                                          data-testid="budget-grid-apply-forward"
                                          onClick={() => applyToYear(r, colIdx, 'forward')}
                                        >
                                          Apply forward (rest of year)
                                        </button>
                                      </li>
                                    </ul>
                                  )}
                                </div>
                              )}
                            </div>
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </React.Fragment>
            ))}
          </tbody>
          {flatRows.length > 0 && (
            <tfoot>
              {['income', 'expense'].map((type) => (
                <tr key={type} className="font-bold" data-testid={`budget-grid-total-${type}`}>
                  <td className="sticky bottom-0 left-0 z-30 bg-base-200">
                    {type === 'income' ? 'Total Income' : 'Total Expenses'}
                  </td>
                  <td className={`${actualsCellClass} bottom-0 z-30 bg-base-200`} style={actualsStyle}>
                    {formatActual(actualTotals[type])}
                  </td>
                  {totalsByType[type].map((total, colIdx) => (
                    <td key={months[colIdx].key} className="sticky bottom-0 z-20 bg-base-200 text-right font-mono pr-3">
                      {currencyFmt.format(total)}
                    </td>
                  ))}
                </tr>
              ))}
            </tfoot>
          )}
        </table>
      </div>

      {/* Save bar */}
      {dirtyKeys.length > 0 && (
        <div className="sticky bottom-4 z-40 mt-4 flex items-center justify-between gap-4 bg-base-300 rounded-lg shadow-lg px-4 py-3" data-testid="budget-grid-save-bar">
          <span className="font-medium">
            {dirtyKeys.length} unsaved change{dirtyKeys.length === 1 ? '' : 's'}
          </span>
          <div className="flex gap-2">
            <button type="button" className="btn btn-ghost btn-sm" onClick={handleDiscard} disabled={saving}>
              Discard
            </button>
            <button type="button" className="btn btn-primary btn-sm" onClick={handleSave} disabled={saving} data-testid="budget-grid-save">
              {saving && <span className="loading loading-spinner loading-xs" />}
              Save Changes
            </button>
          </div>
        </div>
      )}

      <Modal
        open={leaveTo !== null}
        onClose={() => !saving && setLeaveTo(null)}
        title="Save your changes?"
        size="sm"
        testId="budget-grid-leave-dialog"
        actions={
          <>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => goTo(leaveTo)}
              disabled={saving}
              data-testid="budget-grid-leave-discard"
            >
              Discard
            </button>
            <button
              type="button"
              className="btn btn-outline"
              onClick={() => setLeaveTo(null)}
              disabled={saving}
              ref={keepEditingRef}
              data-testid="budget-grid-leave-cancel"
            >
              Keep editing
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={saveAndLeave}
              disabled={saving}
              data-testid="budget-grid-leave-save"
            >
              {saving && <span className="loading loading-spinner loading-xs" />}
              Save and continue
            </button>
          </>
        }
      >
        <p className="text-base-content/70">
          You have {leaveCount} unsaved change{leaveCount === 1 ? '' : 's'} on this page. Save
          {leaveCount === 1 ? ' it' : ' them'} before you go, or discard {leaveCount === 1 ? 'it' : 'them'}?
        </p>
      </Modal>

      {/* Toast */}
      {toast && (
        <div className="toast toast-end z-50">
          <div className={`alert ${toast.type === 'success' ? 'alert-success' : 'alert-error'}`} data-testid="budget-grid-toast">
            <span>{toast.message}</span>
          </div>
        </div>
      )}
    </div>
  );
};

export default BudgetGrid;
