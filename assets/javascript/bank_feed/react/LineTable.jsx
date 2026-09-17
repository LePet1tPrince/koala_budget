import React, { useEffect, useMemo, useState } from 'react';

import DateRangePicker from '../../common/DateRangePicker';
import EditTransactionModal from './EditTransactionModal';
import { Dropdown, MenuRow, ReconciledLock, SortArrow, TablePager, Toast } from './LineTableParts';
import { usePlaidLinkFlow } from './PlaidLinkButton';
import { formatCurrency } from '../../utilities/currency';
import { formatDate as formatDateUtc, formatDateForInput } from '../utils';

/* globals gettext */

const PAGE_SIZE_OPTIONS = [10, 20, 50];

// Column widths are fixed (the table is `table-fixed`) so the Description column
// absorbs whatever the others leave behind, and long payees or categories
// ellipsis rather than wrapping the row height.
const COLUMNS = [
  { key: 'select', label: '', width: 'w-12', sortable: false },
  { key: 'postedDate', label: gettext('Date'), width: 'w-[6rem]', sortable: true },
  { key: 'payee', label: gettext('Payee'), width: 'w-[9rem]', sortable: true, truncate: true },
  { key: 'category', label: gettext('Category'), width: 'w-[9rem]', sortable: true, truncate: true },
  { key: 'inflow', label: gettext('Inflow'), width: 'w-[6rem]', sortable: true, align: 'text-right' },
  { key: 'outflow', label: gettext('Outflow'), width: 'w-[6rem]', sortable: true, align: 'text-right' },
  { key: 'description', label: gettext('Description'), sortable: true, truncate: true },
  { key: 'isReconciled', label: gettext('Reconciled'), width: 'w-[6.5rem]', sortable: false, align: 'text-center' },
];

/** Value a column sorts on. Category sorts by name, amounts numerically. */
const sortValue = (row, key) => {
  switch (key) {
    case 'category':
      return (row.category?.name || '').toLowerCase();
    case 'inflow':
    case 'outflow':
      return parseFloat(row[key]) || 0;
    case 'postedDate':
      return row.postedDate ? formatDateForInput(row.postedDate) : '';
    default:
      return (row[key] || '').toString().toLowerCase();
  }
};

/**
 * The bank feed table.
 *
 * Replaces the `@material-table/core` + MUI implementation (restyle plan Phase
 * 5b). The filtering, counting and selection logic is carried over unchanged —
 * it is what `e2e/tests/test_bank_feed.py` pins — and only the rendering is new:
 * a plain `<table>` with hand-rolled sorting and pagination, which is a fraction
 * of the weight of a table component and lets the rows use theme tokens.
 */
const LineTable = ({
  lines,
  selectedAccount,
  allAccounts,
  allPayees = [],
  categorySuggestions = {},
  teamSlug,
  onAdd,
  onDelete,
  onEditTransaction,
  selectedIds = new Set(),
  onSelectionChange,
  onFilterModeChange,
  hidden = false,
  onUploadClick,
  onRefresh,
  refreshing = false,
  uploadDisabled = false,
  plaidClient,
  onLinkSuccess,
}) => {
  // Date range filter state (YYYY-MM-DD strings)
  const [filterStart, setFilterStart] = useState('');
  const [filterEnd, setFilterEnd] = useState('');
  // Controlled page size so it survives data reloads
  const [pageSize, setPageSize] = useState(10);
  const [page, setPage] = useState(0);
  const [sort, setSort] = useState({ key: 'postedDate', dir: 'desc' });
  const [quickFiltersOpen, setQuickFiltersOpen] = useState(false);
  const [actionsOpen, setActionsOpen] = useState(false);

  // Plaid "Link Bank Account" flow, triggered from the dropdown menu below
  const { handleClick: handleLinkBankClick, loading: linkBankLoading, modal: linkBankModal } = usePlaidLinkFlow({
    teamSlug,
    allAccounts,
    onSuccess: onLinkSuccess,
    plaidClient,
  });

  const [snackbar, setSnackbar] = useState({ open: false, message: '', severity: 'info' });

  // Archived is its own view, separate from the quick filters below
  const [showArchived, setShowArchived] = useState(false);
  // Quick filters: independently toggleable, applied only outside the archived view.
  // "To Review" and "Reconciled" are mutually exclusive (opposite states); "Uncategorized" is orthogonal.
  const [quickFilters, setQuickFilters] = useState({ toReview: false, reconciled: false, uncategorized: false });

  // Edit modal state
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editingTransaction, setEditingTransaction] = useState(null);
  const [modalMode, setModalMode] = useState('edit'); // 'create' | 'edit'

  // Id of the row whose checkbox was last clicked, used as the anchor for
  // shift-click range selection
  const [lastCheckedId, setLastCheckedId] = useState(null);

  const toggleQuickFilter = (key) => {
    setQuickFilters((prev) => {
      const next = { ...prev, [key]: !prev[key] };
      if (key === 'toReview' && next.toReview) next.reconciled = false;
      if (key === 'reconciled' && next.reconciled) next.toReview = false;
      return next;
    });
  };
  const activeQuickFilterCount = Object.values(quickFilters).filter(Boolean).length;

  // Clear selection and notify parent when switching between the active and archived views
  useEffect(() => {
    setLastCheckedId(null);
    if (onSelectionChange) {
      onSelectionChange(new Set());
    }
    if (onFilterModeChange) {
      onFilterModeChange(showArchived ? 'archived' : 'active');
    }
  }, [showArchived]);

  // Clear selection when quick filters change so the batch bar doesn't act on rows that scrolled out of view
  useEffect(() => {
    setLastCheckedId(null);
    if (onSelectionChange) {
      onSelectionChange(new Set());
    }
  }, [quickFilters]);

  const showSnackbar = (message, severity = 'info') => setSnackbar({ open: true, message, severity });
  const handleCloseSnackbar = () => setSnackbar((s) => ({ ...s, open: false }));

  // Date-only values are rendered in UTC so users west of UTC don't see
  // the previous day.
  const formatDate = (dateValue) => (dateValue ? formatDateUtc(dateValue) : '');

  const handleEditClick = (rowData) => {
    setEditingTransaction(rowData);
    setModalMode('edit');
    setEditModalOpen(true);
  };

  const handleAddClick = () => {
    setEditingTransaction(null);
    setModalMode('create');
    setEditModalOpen(true);
  };

  const handleEditModalClose = () => {
    setEditModalOpen(false);
    setEditingTransaction(null);
  };

  const handleEditSave = async (data, mode) => {
    if (mode === 'create') {
      if (onAdd) {
        await onAdd(data);
        showSnackbar(gettext('Transaction added successfully'), 'success');
      }
    } else if (onEditTransaction) {
      await onEditTransaction(data);
      showSnackbar(gettext('Transaction updated successfully'), 'success');
    }
  };

  // Filter lines by selected date range, view (active/archived), and quick filters
  const filteredLines = useMemo(() => {
    if (!Array.isArray(lines)) return [];
    let filtered = lines;

    // Handle both camelCase (from generated API client) and snake_case (raw API)
    const isArchived = (l) => l.isArchived ?? l.is_archived ?? false;
    const isReconciled = (l) => l.isReconciled ?? l.is_reconciled ?? false;

    if (showArchived) {
      filtered = filtered.filter((l) => isArchived(l));
    } else {
      // Default: everything not archived, regardless of categorized/reconciled state
      filtered = filtered.filter((l) => !isArchived(l));
      if (quickFilters.toReview) {
        filtered = filtered.filter((l) => !isReconciled(l));
      } else if (quickFilters.reconciled) {
        filtered = filtered.filter((l) => isReconciled(l));
      }
      if (quickFilters.uncategorized) {
        filtered = filtered.filter((l) => !l.category);
      }
    }

    // Apply date range filter. Compare YYYY-MM-DD strings so UTC-parsed
    // posted dates and local picker dates can't disagree on boundary days.
    if (filterStart || filterEnd) {
      const startStr = filterStart ? formatDateForInput(filterStart) : null;
      const endStr = filterEnd ? formatDateForInput(filterEnd) : null;
      filtered = filtered.filter((l) => {
        if (!l.postedDate) return false;
        const dateStr = formatDateForInput(l.postedDate);
        if (startStr && dateStr < startStr) return false;
        if (endStr && dateStr > endStr) return false;
        return true;
      });
    }

    return filtered;
  }, [lines, filterStart, filterEnd, showArchived, quickFilters]);

  // Counts (independent of the active filter/date range) for the badges shown
  // on the Quick Filters menu items and the Archived button
  const filterCounts = useMemo(() => {
    if (!Array.isArray(lines)) return { to_review: 0, reconciled: 0, archived: 0, uncategorized: 0 };
    const isArchived = (l) => l.isArchived ?? l.is_archived ?? false;
    const isReconciled = (l) => l.isReconciled ?? l.is_reconciled ?? false;
    return lines.reduce(
      (acc, l) => {
        if (isArchived(l)) {
          acc.archived += 1;
          return acc;
        }
        if (isReconciled(l)) {
          acc.reconciled += 1;
        } else {
          acc.to_review += 1;
        }
        if (!l.category) {
          acc.uncategorized += 1;
        }
        return acc;
      },
      { to_review: 0, reconciled: 0, archived: 0, uncategorized: 0 }
    );
  }, [lines]);

  const sortedLines = useMemo(() => {
    const rows = [...filteredLines];
    rows.sort((a, b) => {
      const av = sortValue(a, sort.key);
      const bv = sortValue(b, sort.key);
      if (av < bv) return sort.dir === 'asc' ? -1 : 1;
      if (av > bv) return sort.dir === 'asc' ? 1 : -1;
      return 0;
    });
    return rows;
  }, [filteredLines, sort]);

  const pageCount = Math.max(1, Math.ceil(sortedLines.length / pageSize));
  // Filtering can shrink the list under the current page; clamp rather than
  // render an empty page.
  const safePage = Math.min(page, pageCount - 1);
  const pageRows = sortedLines.slice(safePage * pageSize, safePage * pageSize + pageSize);

  useEffect(() => {
    setPage(0);
  }, [filteredLines.length, pageSize]);

  const toggleSort = (key) =>
    setSort((prev) => (prev.key === key ? { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'asc' }));

  // Handle row selection. Shift-click extends the selection to every row
  // between the last-clicked checkbox and this one (in displayed order).
  const handleRowSelect = (rowId, checked, shiftKey) => {
    if (!onSelectionChange) return;
    const newSelected = new Set(selectedIds);

    if (shiftKey && lastCheckedId !== null) {
      const ids = sortedLines.map((l) => l.id);
      const anchorIndex = ids.indexOf(lastCheckedId);
      const targetIndex = ids.indexOf(rowId);
      if (anchorIndex !== -1 && targetIndex !== -1) {
        const [start, end] = anchorIndex < targetIndex ? [anchorIndex, targetIndex] : [targetIndex, anchorIndex];
        for (let i = start; i <= end; i += 1) {
          if (checked) {
            newSelected.add(ids[i]);
          } else {
            newSelected.delete(ids[i]);
          }
        }
        onSelectionChange(newSelected);
        setLastCheckedId(rowId);
        return;
      }
    }

    if (checked) {
      newSelected.add(rowId);
    } else {
      newSelected.delete(rowId);
    }
    onSelectionChange(newSelected);
    setLastCheckedId(rowId);
  };

  const handleSelectAll = (checked) => {
    if (!onSelectionChange) return;
    onSelectionChange(checked ? new Set(filteredLines.map((l) => l.id)) : new Set());
  };

  const allSelected = filteredLines.length > 0 && filteredLines.every((l) => selectedIds.has(l.id));
  const someSelected = filteredLines.some((l) => selectedIds.has(l.id)) && !allSelected;

  if (!selectedAccount) {
    return (
      <div className="alert alert-info">
        <i className="fa fa-info-circle"></i>
        <span>{gettext('Please select an account to view lines')}</span>
      </div>
    );
  }

  return (
    <div style={hidden ? { display: 'none' } : undefined}>
      <div className="space-y-4">
        {/* Toolbar: quick filters, archived view, date filter, and actions */}
        <div className="flex flex-wrap items-center gap-2">
          <Dropdown
            open={quickFiltersOpen}
            onOpenChange={setQuickFiltersOpen}
            trigger={({ toggle, open }) => (
              <button
                type="button"
                className={`btn btn-sm ${activeQuickFilterCount > 0 ? 'btn-primary' : 'btn-outline'}`}
                disabled={showArchived}
                aria-haspopup="menu"
                aria-expanded={open}
                onClick={toggle}
                data-testid="quick-filters-btn"
              >
                {gettext('Quick Filters')}
                {activeQuickFilterCount > 0 && (
                  <span className="badge badge-sm">{activeQuickFilterCount}</span>
                )}
                <span aria-hidden="true">▾</span>
              </button>
            )}
          >
            {({ close }) => (
              <>
                <MenuRow
                  testId="filter-to-review"
                  checked={quickFilters.toReview}
                  label={gettext('To Review')}
                  count={filterCounts.to_review}
                  countClass="badge-warning badge-outline"
                  onClick={() => toggleQuickFilter('toReview')}
                />
                <MenuRow
                  testId="filter-reconciled"
                  checked={quickFilters.reconciled}
                  label={gettext('Reconciled')}
                  count={filterCounts.reconciled}
                  countClass="badge-success badge-outline"
                  onClick={() => toggleQuickFilter('reconciled')}
                />
                <MenuRow
                  testId="filter-uncategorized"
                  checked={quickFilters.uncategorized}
                  label={gettext('Uncategorized')}
                  count={filterCounts.uncategorized}
                  countClass="badge-outline"
                  onClick={() => toggleQuickFilter('uncategorized')}
                />
                {activeQuickFilterCount > 0 && (
                  <>
                    <div className="my-1 border-t border-base-300" />
                    <MenuRow
                      label={gettext('Clear filters')}
                      onClick={() => {
                        setQuickFilters({ toReview: false, reconciled: false, uncategorized: false });
                        close();
                      }}
                    />
                  </>
                )}
              </>
            )}
          </Dropdown>

          <button
            type="button"
            className={`btn btn-sm ${showArchived ? 'btn-neutral' : 'btn-outline'}`}
            onClick={() => setShowArchived((v) => !v)}
            aria-pressed={showArchived}
            data-testid="filter-archived"
          >
            {gettext('Archived')}
            <span className="badge badge-sm badge-ghost">{filterCounts.archived}</span>
          </button>

          <div className="mx-1 h-6 w-px bg-base-300" />

          <DateRangePicker
            startDate={filterStart}
            endDate={filterEnd}
            onApply={(s, e) => {
              setFilterStart(s);
              setFilterEnd(e);
            }}
          />
          <span className="whitespace-nowrap text-sm text-base-content/70">
            {filteredLines.length} {gettext('lines')}
          </span>

          <div className="mx-1 h-6 w-px bg-base-300" />

          <div className="join" data-testid="add-transaction-btn">
            <button type="button" className="btn btn-sm btn-primary join-item" onClick={handleAddClick}>
              {gettext('Add Transaction')}
            </button>
            <Dropdown
              open={actionsOpen}
              onOpenChange={setActionsOpen}
              align="right"
              trigger={({ toggle, open }) => (
                <button
                  type="button"
                  className="btn btn-sm btn-primary join-item px-2"
                  aria-label={gettext('More actions')}
                  aria-haspopup="menu"
                  aria-expanded={open}
                  onClick={toggle}
                >
                  <span aria-hidden="true">▾</span>
                </button>
              )}
            >
              {({ close }) => (
                <>
                  <MenuRow
                    label={gettext('Upload CSV/Excel')}
                    disabled={uploadDisabled}
                    onClick={() => {
                      close();
                      onUploadClick();
                    }}
                  />
                  <div className="my-1 border-t border-base-300" />
                  <MenuRow
                    label={linkBankLoading ? gettext('Loading...') : gettext('Link Bank Account')}
                    disabled={linkBankLoading}
                    onClick={() => {
                      close();
                      handleLinkBankClick();
                    }}
                  />
                  <MenuRow
                    label={refreshing ? gettext('Refreshing...') : gettext('Refresh')}
                    disabled={refreshing || uploadDisabled}
                    onClick={() => {
                      close();
                      onRefresh();
                    }}
                  />
                </>
              )}
            </Dropdown>
          </div>
          {linkBankModal}
        </div>

        <div className="app-surface overflow-hidden">
          {/* Select-all strip, which `@material-table/core` rendered as its toolbar */}
          <div className="flex items-center gap-2 border-b border-base-300 px-3 py-2">
            <input
              type="checkbox"
              className="checkbox checkbox-sm rounded-sm"
              checked={allSelected}
              ref={(el) => {
                if (el) el.indeterminate = someSelected;
              }}
              onChange={(e) => handleSelectAll(e.target.checked)}
              aria-label={gettext('Select all')}
              data-testid="select-all"
            />
            {selectedIds.size > 0 && (
              <span className="text-sm text-primary">
                {selectedIds.size} {gettext('selected')}
              </span>
            )}
          </div>

          <div className="overflow-x-auto">
            <table className="table table-sm table-quiet table-fixed w-full">
              <thead>
                <tr>
                  {COLUMNS.map((col) => (
                    <th key={col.key} className={`truncate ${col.width || ''} ${col.align || ''}`}>
                      {col.sortable ? (
                        <button
                          type="button"
                          className="group inline-flex items-center gap-1 hover:text-base-content"
                          onClick={() => toggleSort(col.key)}
                        >
                          {col.label}
                          <SortArrow active={sort.key === col.key} direction={sort.dir} />
                        </button>
                      ) : (
                        col.label
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {pageRows.map((row) => {
                  // Uncategorized rows are muted outside the archived view. This was a
                  // hardcoded #9CA3AF, which did not follow the theme.
                  const muted = !showArchived && !row.category;
                  const reconciled = row.isReconciled ?? row.is_reconciled ?? false;
                  return (
                    <tr
                      key={row.id}
                      className={`cursor-pointer ${muted ? 'text-base-content/50' : ''}`}
                      onClick={() => handleEditClick(row)}
                      data-testid={`feed-row-${row.id}`}
                    >
                      <td className="w-12" onClick={(e) => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          className="checkbox checkbox-sm rounded-sm"
                          checked={selectedIds.has(row.id)}
                          onChange={(e) => handleRowSelect(row.id, e.target.checked, e.nativeEvent.shiftKey)}
                          aria-label={gettext('Select row')}
                        />
                      </td>
                      <td className="whitespace-nowrap">{formatDate(row.postedDate)}</td>
                      <td className="truncate" title={row.payee || ''}>
                        {row.payee || ''}
                      </td>
                      <td className="truncate" title={row.category ? row.category.name : gettext('Uncategorized')}>
                        {row.category ? gettext(row.category.name) : gettext('Uncategorized')}
                      </td>
                      <td className="money whitespace-nowrap text-right">
                        {row.inflow && parseFloat(row.inflow) > 0 ? formatCurrency(row.inflow) : ''}
                      </td>
                      <td className="money whitespace-nowrap text-right">
                        {row.outflow && parseFloat(row.outflow) > 0 ? formatCurrency(row.outflow) : ''}
                      </td>
                      <td className="truncate" title={row.description || ''}>
                        {row.description || ''}
                      </td>
                      <td className="text-center">
                        <ReconciledLock reconciled={reconciled} />
                      </td>
                    </tr>
                  );
                })}
                {pageRows.length === 0 && (
                  <tr>
                    <td colSpan={COLUMNS.length} className="py-8 text-center text-base-content/70">
                      {gettext('No transactions to show')}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <TablePager
            page={safePage}
            pageCount={pageCount}
            pageSize={pageSize}
            pageSizeOptions={PAGE_SIZE_OPTIONS}
            total={sortedLines.length}
            onPageChange={setPage}
            onPageSizeChange={setPageSize}
          />
        </div>
      </div>

      {/* Prop-for-prop as the Material version passed them: the modal reads
          `onDelete`/`selectedAccount` if given, and passing them here would add
          behaviour this change is not meant to introduce. */}
      <EditTransactionModal
        open={editModalOpen}
        onClose={handleEditModalClose}
        transaction={editingTransaction}
        allAccounts={allAccounts}
        allPayees={allPayees}
        categorySuggestions={categorySuggestions}
        teamSlug={teamSlug}
        onSave={handleEditSave}
        mode={modalMode}
      />

      <Toast
        open={snackbar.open}
        message={snackbar.message}
        severity={snackbar.severity}
        onClose={handleCloseSnackbar}
        autoHideMs={6000}
      />
    </div>
  );
};

export default LineTable;
