import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Cookies from 'js-cookie';

const cellKey = (categoryId, monthKey) => `${categoryId}|${monthKey}`;

/**
 * Parse one pasted/typed cell into a normalized amount string, or null if it
 * isn't a number. Handles common spreadsheet formats: "$1,234.56", "(45.00)"
 * (negative), currency symbols, thin/non-breaking spaces.
 */
export function sanitizeAmount(raw) {
  if (raw === null || raw === undefined) return null;
  let text = String(raw).replace(/[\s\u00A0\u2009\u202F]/g, '');
  if (text === '') return null;

  let negative = false;
  const parens = text.match(/^\((.*)\)$/);
  if (parens) {
    negative = true;
    text = parens[1];
  }
  text = text.replace(/[$€£]/g, '').replace(/,/g, '');
  if (text.startsWith('-')) {
    negative = !negative;
    text = text.slice(1);
  }
  if (text === '' || !/^\d*\.?\d*$/.test(text) || !/\d/.test(text)) return null;

  const value = parseFloat(text);
  if (!isFinite(value)) return null;
  return (negative ? -value : value).toFixed(2);
}

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
  const sanitized = sanitizeAmount(text);
  return sanitized === null ? null : parseFloat(sanitized);
};

const currencyFmt = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/**
 * Multi-month budget grid editor. Rows are budget categories (grouped by
 * account group), columns are months. Supports pasting a block of values
 * straight from Excel / Google Sheets: the paste anchors at the focused cell
 * and fills right and down, exactly like a spreadsheet.
 */
const BudgetGrid = ({ months, groups, prevStart, nextStart, numMonths, saveUrl }) => {
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
  const containerRef = useRef(null);

  const isDirty = useCallback(
    (key) => numericValue(values[key]) !== numericValue(savedValues[key]),
    [values, savedValues],
  );

  const dirtyKeys = useMemo(
    () => Object.keys(values).filter((key) => isDirty(key)),
    [values, isDirty],
  );

  // Warn before leaving the page with unsaved changes
  useEffect(() => {
    if (dirtyKeys.length === 0) return undefined;
    const handler = (e) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [dirtyKeys.length]);

  useEffect(() => {
    if (!toast) return undefined;
    const timer = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(timer);
  }, [toast]);

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
        amount: sanitizeAmount(values[key]) ?? '0.00',
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
    } catch (error) {
      setToast({ type: 'error', message: error.message });
    } finally {
      setSaving(false);
    }
  };

  const handleDiscard = () => setValues(savedValues);

  const navigate = (start) => {
    if (dirtyKeys.length > 0 && !window.confirm('You have unsaved changes. Leave without saving?')) return;
    const url = new URL(window.location);
    url.searchParams.set('start', start);
    // beforeunload fires on navigation; the confirm above already covered it
    window.location.href = url.toString();
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
              <th className="sticky top-0 left-0 z-30 bg-base-200 min-w-48">Category</th>
              {months.map((month) => (
                <th key={month.key} className="sticky top-0 z-20 bg-base-200 text-right min-w-28">{month.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {flatRows.length === 0 && (
              <tr>
                <td colSpan={months.length + 1} className="text-center opacity-60 py-8" data-testid="budget-grid-empty">
                  No budget categories found. Please add income or expense accounts first.
                </td>
              </tr>
            )}
            {groups.map((group) => (
              <React.Fragment key={group.name}>
                <tr>
                  <td className="sticky left-0 z-10 bg-base-200 font-bold" data-testid="budget-grid-group">{group.name}</td>
                  <td colSpan={months.length} className="bg-base-200" />
                </tr>
                {group.rows.map((row) => {
                  const r = rowIndexById.get(row.id);
                  return (
                    <tr key={row.id} data-testid="budget-grid-row">
                      <td className="sticky left-0 z-10 bg-base-100 pl-6 whitespace-nowrap">{row.name}</td>
                      {months.map((month, colIdx) => {
                        const key = cellKey(row.id, month.key);
                        const dirty = isDirty(key);
                        return (
                          <td key={month.key} className="p-1">
                            <input
                              type="text"
                              inputMode="decimal"
                              className={`input input-bordered input-sm w-full min-w-24 text-right font-mono ${dirty ? 'input-warning bg-warning/10' : ''}`}
                              value={values[key]}
                              data-row={r}
                              data-col={colIdx}
                              aria-label={`${row.name} ${month.label}`}
                              onChange={(e) => setValues((prev) => ({ ...prev, [key]: e.target.value }))}
                              onPaste={(e) => handlePaste(e, r, colIdx)}
                              onKeyDown={(e) => handleKeyDown(e, r, colIdx)}
                              onFocus={(e) => e.target.select()}
                            />
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
