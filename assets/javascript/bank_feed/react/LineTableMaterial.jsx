import {
  AccountBalance as AccountBalanceIcon,
  Add as AddIcon,
  ArrowDropDown as ArrowDropDownIcon,
  ArrowUpward as ArrowUpwardIcon,
  Check as CheckIcon,
  ChevronLeft as ChevronLeftIcon,
  ChevronRight as ChevronRightIcon,
  Clear as ClearIcon,
  Delete as DeleteIcon,
  Edit as EditIcon,
  FilterList as FilterListIcon,
  FirstPage as FirstPageIcon,
  LastPage as LastPageIcon,
  Lock as LockIcon,
  LockOpen as LockOpenIcon,
  Refresh as RefreshIcon,
  Search as SearchIcon,
  Upload as UploadIcon,
} from '@mui/icons-material';
import { Alert, Badge, Box, Button, ButtonGroup, Checkbox, Chip, CircularProgress, Divider, ListItemIcon, ListItemText, Menu, MenuItem, Snackbar, Toolbar, Tooltip, Typography } from '@mui/material';
import React, { useEffect, useMemo, useState } from 'react';
import { ThemeProvider, createTheme } from '@mui/material/styles';

import DateRangePicker from '../../common/DateRangePicker';
import EditTransactionModal from './EditTransactionModal';
import MaterialTable from '@material-table/core';
import { usePlaidLinkFlow } from './PlaidLinkButton';
import { formatCurrency } from '../../utilities/currency';
import { formatDate as formatDateUtc, formatDateForInput } from '../utils';

/* globals gettext */

// Single-line, ellipsis-truncated cell so long payees/categories/descriptions
// never wrap the row height. Width is omitted for the Description column so
// it absorbs whatever space the fixed-width columns leave behind.
const TRUNCATE_CELL_STYLE = (width) => ({
  ...(width ? { width, maxWidth: width } : {}),
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap',
});



/**
 * LineTableMaterial component - displays and edits lines using Material-Table
 * Drop-in replacement for LineTable component
 */
const LineTableMaterial = ({
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
  // Anchor for the "Add Transaction" split button's dropdown menu
  const [actionsMenuAnchorEl, setActionsMenuAnchorEl] = useState(null);
  // Anchor for the "Quick Filters" dropdown menu
  const [quickFiltersAnchorEl, setQuickFiltersAnchorEl] = useState(null);

  // Plaid "Link Bank Account" flow, triggered from the dropdown menu below
  const { handleClick: handleLinkBankClick, loading: linkBankLoading, modal: linkBankModal } = usePlaidLinkFlow({
    teamSlug,
    allAccounts,
    onSuccess: onLinkSuccess,
    plaidClient,
  });

  // Snackbar state
  const [snackbar, setSnackbar] = useState({
    open: false,
    message: '',
    severity: 'info', // 'success', 'error', 'warning', 'info'
  });

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

  // Create MUI theme that adapts to existing theme
  const theme = useMemo(() => {
    // Detect if dark mode is active by checking document classes or CSS variables
    const isDarkMode = document.documentElement.classList.contains('dark') ||
                       window.matchMedia('(prefers-color-scheme: dark)').matches;

    return createTheme({
      palette: {
        mode: isDarkMode ? 'dark' : 'light',
      },
    });
  }, []);

  // Show snackbar helper
  const showSnackbar = (message, severity = 'info') => {
    setSnackbar({ open: true, message, severity });
  };

  // Close snackbar
  const handleCloseSnackbar = () => {
    setSnackbar({ ...snackbar, open: false });
  };

  // Format date for display (handles both Date objects and strings).
  // Date-only values are rendered in UTC so users west of UTC don't see
  // the previous day.
  const formatDate = (dateValue) => {
    if (!dateValue) return '';
    return formatDateUtc(dateValue);
  };

  // Handle opening edit modal
  const handleEditClick = (rowData) => {
    setEditingTransaction(rowData);
    setModalMode('edit');
    setEditModalOpen(true);
  };

  // Handle opening create modal
  const handleAddClick = () => {
    setEditingTransaction(null);
    setModalMode('create');
    setEditModalOpen(true);
  };

  // Handle closing edit modal
  const handleEditModalClose = () => {
    setEditModalOpen(false);
    setEditingTransaction(null);
  };

  // Handle save from edit modal
  const handleEditSave = async (data, mode) => {
    if (mode === 'create') {
      if (onAdd) {
        await onAdd(data);
        showSnackbar(gettext('Transaction added successfully'), 'success');
      }
    } else {
      if (onEditTransaction) {
        await onEditTransaction(data);
        showSnackbar(gettext('Transaction updated successfully'), 'success');
      }
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

  // Handle row selection. Shift-click extends the selection to every row
  // between the last-clicked checkbox and this one (in displayed order).
  const handleRowSelect = (rowId, checked, shiftKey) => {
    if (!onSelectionChange) return;
    const newSelected = new Set(selectedIds);

    if (shiftKey && lastCheckedId !== null) {
      const ids = filteredLines.map((l) => l.id);
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

  // Handle select all
  const handleSelectAll = (checked) => {
    if (!onSelectionChange) return;
    if (checked) {
      const allIds = new Set(filteredLines.map(l => l.id));
      onSelectionChange(allIds);
    } else {
      onSelectionChange(new Set());
    }
  };

  // Check if all rows are selected
  const allSelected = filteredLines.length > 0 && filteredLines.every(l => selectedIds.has(l.id));
  const someSelected = filteredLines.some(l => selectedIds.has(l.id)) && !allSelected;

  // Define columns for Material-Table
  const columns = [
    // Selection checkbox column
    {
      title: '',
      field: 'select',
      width: 50,
      sorting: false,
      render: (rowData) => (
        <Checkbox
          size="small"
          checked={selectedIds.has(rowData.id)}
          onChange={(e) => handleRowSelect(rowData.id, e.target.checked, e.nativeEvent.shiftKey)}
          onClick={(e) => e.stopPropagation()}
        />
      ),
      headerStyle: { width: 50, paddingLeft: 8, paddingRight: 0 },
      cellStyle: { width: 50, paddingLeft: 8, paddingRight: 0 },
    },
    {
      title: gettext('Date'),
      field: 'postedDate',
      type: 'date',
      width: 90,
      render: (rowData) => formatDate(rowData.postedDate),
      headerStyle: { width: 90 },
      cellStyle: { width: 90, whiteSpace: 'nowrap' },
    },
    {
      title: gettext('Payee'),
      field: 'payee',
      width: 150,
      render: (rowData) => rowData.payee || '',
      headerStyle: { width: 150 },
      cellStyle: TRUNCATE_CELL_STYLE(150),
    },
    {
      title: gettext('Category'),
      field: 'category',
      width: 150,
      render: (rowData) => {
        const category = rowData.category;
        return category ? gettext(category.name) : gettext('Uncategorized');
      },
      headerStyle: { width: 150 },
      cellStyle: TRUNCATE_CELL_STYLE(150),
    },
    {
      title: gettext('Inflow'),
      field: 'inflow',
      type: 'numeric',
      width: 90,
      render: (rowData) => {
        const value = rowData.inflow;
        return value && parseFloat(value) > 0 ? formatCurrency(value) : '';
      },
      headerStyle: { width: 90 },
      cellStyle: { width: 90, whiteSpace: 'nowrap' },
    },
    {
      title: gettext('Outflow'),
      field: 'outflow',
      type: 'numeric',
      width: 90,
      render: (rowData) => {
        const value = rowData.outflow;
        return value && parseFloat(value) > 0 ? formatCurrency(value) : '';
      },
      headerStyle: { width: 90 },
      cellStyle: { width: 90, whiteSpace: 'nowrap' },
    },
    {
      title: gettext('Description'),
      field: 'description',
      render: (rowData) => {
        const desc = rowData.description || '';
        return <span title={desc}>{desc}</span>;
      },
      cellStyle: TRUNCATE_CELL_STYLE(),
    },
    {
      title: gettext('Reconciled'),
      field: 'isReconciled',
      width: 40,
      sorting: false,
      render: (rowData) => {
        const reconciled = rowData.isReconciled ?? rowData.is_reconciled ?? false;
        const tooltip = reconciled ? gettext('Reconciled') : gettext('Not yet reconciled');
        // Class names must be full literals, otherwise Tailwind's compiler
        // can't see them and strips them from the build.
        const colorClasses = reconciled ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-400';
        return (
          <Tooltip title={tooltip} arrow placement="top">
            <span className={`inline-flex items-center justify-center w-6 h-6 rounded-full ${colorClasses} cursor-default`}>
              {reconciled ? <LockIcon sx={{ fontSize: 14 }} /> : <LockOpenIcon sx={{ fontSize: 14 }} />}
            </span>
          </Tooltip>
        );
      },
      headerStyle: { width: 40, textAlign: 'center', paddingLeft: 4, paddingRight: 4 },
      cellStyle: { width: 40, textAlign: 'center', paddingLeft: 4, paddingRight: 4 },
    },
  ];

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
    <ThemeProvider theme={theme}>
      <div className="space-y-4">
        {/* Toolbar: quick filters, archived view, date filter, and actions */}
        <div className="flex items-center gap-2 flex-wrap">
          <Button
            size="small"
            variant={activeQuickFilterCount > 0 ? 'contained' : 'outlined'}
            color="primary"
            disabled={showArchived}
            startIcon={<FilterListIcon fontSize="small" />}
            endIcon={<ArrowDropDownIcon fontSize="small" />}
            onClick={(e) => setQuickFiltersAnchorEl(e.currentTarget)}
            data-testid="quick-filters-btn"
          >
            {gettext('Quick Filters')}
          </Button>
          <Menu
            anchorEl={quickFiltersAnchorEl}
            open={Boolean(quickFiltersAnchorEl)}
            onClose={() => setQuickFiltersAnchorEl(null)}
          >
            <MenuItem onClick={() => toggleQuickFilter('toReview')} data-testid="filter-to-review" sx={{ justifyContent: 'space-between', gap: 3 }}>
              <Box sx={{ display: 'flex', alignItems: 'center' }}>
                <Checkbox size="small" checked={quickFilters.toReview} tabIndex={-1} onChange={() => {}} sx={{ p: 0, mr: 1, pointerEvents: 'none' }} />
                <ListItemText>{gettext('To Review')}</ListItemText>
              </Box>
              <Chip label={filterCounts.to_review} size="small" color="warning" variant="outlined" sx={{ height: 20 }} />
            </MenuItem>
            <MenuItem onClick={() => toggleQuickFilter('reconciled')} data-testid="filter-reconciled" sx={{ justifyContent: 'space-between', gap: 3 }}>
              <Box sx={{ display: 'flex', alignItems: 'center' }}>
                <Checkbox size="small" checked={quickFilters.reconciled} tabIndex={-1} onChange={() => {}} sx={{ p: 0, mr: 1, pointerEvents: 'none' }} />
                <ListItemText>{gettext('Reconciled')}</ListItemText>
              </Box>
              <Chip label={filterCounts.reconciled} size="small" color="success" variant="outlined" sx={{ height: 20 }} />
            </MenuItem>
            <MenuItem onClick={() => toggleQuickFilter('uncategorized')} data-testid="filter-uncategorized" sx={{ justifyContent: 'space-between', gap: 3 }}>
              <Box sx={{ display: 'flex', alignItems: 'center' }}>
                <Checkbox size="small" checked={quickFilters.uncategorized} tabIndex={-1} onChange={() => {}} sx={{ p: 0, mr: 1, pointerEvents: 'none' }} />
                <ListItemText>{gettext('Uncategorized')}</ListItemText>
              </Box>
              <Chip label={filterCounts.uncategorized} size="small" variant="outlined" sx={{ height: 20 }} />
            </MenuItem>
            {activeQuickFilterCount > 0 && [
              <Divider key="quick-filters-divider" />,
              <MenuItem
                key="quick-filters-clear"
                onClick={() => {
                  setQuickFilters({ toReview: false, reconciled: false, uncategorized: false });
                  setQuickFiltersAnchorEl(null);
                }}
              >
                <ListItemText>{gettext('Clear filters')}</ListItemText>
              </MenuItem>,
            ]}
          </Menu>

          <Button
            size="small"
            variant={showArchived ? 'contained' : 'outlined'}
            color="inherit"
            onClick={() => setShowArchived((v) => !v)}
            data-testid="filter-archived"
          >
            <Badge
              badgeContent={filterCounts.archived}
              color="default"
              max={999}
              sx={{ '& .MuiBadge-badge': { right: -10, top: -2 } }}
            >
              {gettext('Archived')}
            </Badge>
          </Button>

          <Divider orientation="vertical" flexItem sx={{ mx: 0.5 }} />

          <DateRangePicker
            startDate={filterStart}
            endDate={filterEnd}
            onApply={(s, e) => {
              setFilterStart(s);
              setFilterEnd(e);
            }}
          />
          <span className="text-sm text-gray-500 whitespace-nowrap">
            {filteredLines.length} {gettext('lines')}
          </span>

          <Divider orientation="vertical" flexItem sx={{ mx: 0.5 }} />

          <ButtonGroup size="small" variant="contained" color="primary" data-testid="add-transaction-btn">
            <Button startIcon={<AddIcon fontSize="small" />} onClick={handleAddClick}>
              {gettext('Add Transaction')}
            </Button>
            <Button
              size="small"
              sx={{ px: 0.5 }}
              aria-label={gettext('More actions')}
              aria-haspopup="true"
              aria-controls={actionsMenuAnchorEl ? 'toolbar-actions-menu' : undefined}
              onClick={(e) => setActionsMenuAnchorEl(e.currentTarget)}
            >
              <ArrowDropDownIcon fontSize="small" />
            </Button>
          </ButtonGroup>
          <Menu
            id="toolbar-actions-menu"
            anchorEl={actionsMenuAnchorEl}
            open={Boolean(actionsMenuAnchorEl)}
            onClose={() => setActionsMenuAnchorEl(null)}
          >
            <MenuItem
              onClick={() => {
                setActionsMenuAnchorEl(null);
                onUploadClick();
              }}
              disabled={uploadDisabled}
            >
              <ListItemIcon>
                <UploadIcon fontSize="small" />
              </ListItemIcon>
              <ListItemText>{gettext('Upload CSV/Excel')}</ListItemText>
            </MenuItem>
            <Divider />
            <MenuItem
              onClick={() => {
                setActionsMenuAnchorEl(null);
                handleLinkBankClick();
              }}
              disabled={linkBankLoading}
            >
              <ListItemIcon>
                {linkBankLoading ? <CircularProgress size={16} /> : <AccountBalanceIcon fontSize="small" />}
              </ListItemIcon>
              <ListItemText>{linkBankLoading ? gettext('Loading...') : gettext('Link Bank Account')}</ListItemText>
            </MenuItem>
            <MenuItem
              onClick={() => {
                setActionsMenuAnchorEl(null);
                onRefresh();
              }}
              disabled={refreshing || uploadDisabled}
            >
              <ListItemIcon>
                {refreshing ? <CircularProgress size={16} /> : <RefreshIcon fontSize="small" />}
              </ListItemIcon>
              <ListItemText>{refreshing ? gettext('Refreshing...') : gettext('Refresh')}</ListItemText>
            </MenuItem>
          </Menu>
          {linkBankModal}
        </div>

        {/* Material Table */}
        <MaterialTable
          title=""
          columns={columns}
          data={filteredLines}
          components={{
            Toolbar: () => (
              <Toolbar variant="dense" sx={{ pl: 1, pr: 1, minHeight: 40 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', flexGrow: 1 }}>
                  <Checkbox
                    size="small"
                    checked={allSelected}
                    indeterminate={someSelected}
                    onChange={(e) => handleSelectAll(e.target.checked)}
                    sx={{ mr: 1 }}
                  />
                  {selectedIds.size > 0 && (
                    <Typography variant="body2" color="primary">
                      {selectedIds.size} {gettext('selected')}
                    </Typography>
                  )}
                </Box>
              </Toolbar>
            ),
          }}
          icons={{
            Add: AddIcon,
            Edit: EditIcon,
            Delete: DeleteIcon,
            Check: CheckIcon,
            Clear: ClearIcon,
            Search: SearchIcon,
            FirstPage: FirstPageIcon,
            LastPage: LastPageIcon,
            PreviousPage: ChevronLeftIcon,
            NextPage: ChevronRightIcon,
            SortArrow: ArrowUpwardIcon,
            Filter: FilterListIcon,
          }}
          onRowClick={(_event, rowData) => handleEditClick(rowData)}
          onChangeRowsPerPage={setPageSize}
          options={{
            actionsColumnIndex: -1,
            pageSize: pageSize,
            pageSizeOptions: [10, 20, 50],
            addRowPosition: 'first',
            sorting: true,
            search: false,
            toolbar: true,
            showTitle: false,
            padding: 'dense',
            tableLayout: 'fixed',
            emptyRowsWhenPaging: false,
            rowStyle: (rowData) => {
              // Style uncategorized transactions with grey text outside the archived view
              if (!showArchived && rowData.category === null) {
                return {
                  color: '#9CA3AF',
                  cursor: 'pointer',
                };
              }
              return { cursor: 'pointer' };
            },
          }}
          localization={{
            header: {
              actions: gettext('Actions'),
            },
            body: {
              emptyDataSourceMessage: gettext('No lines found'),
              addTooltip: gettext('Add Line'),
              deleteTooltip: gettext('Delete'),
              editTooltip: gettext('Edit'),
              editRow: {
                deleteText: gettext('Are you sure you want to delete this line?'),
                cancelTooltip: gettext('Cancel'),
                saveTooltip: gettext('Save'),
              },
            },
            pagination: {
              labelDisplayedRows: '{from}-{to} ' + gettext('of') + ' {count}',
              firstTooltip: gettext('First Page'),
              previousTooltip: gettext('Previous Page'),
              nextTooltip: gettext('Next Page'),
              lastTooltip: gettext('Last Page'),
            },
          }}
        />

        {/* Edit/Create Transaction Modal */}
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

        {/* Snackbar for notifications */}
        <Snackbar
          open={snackbar.open}
          autoHideDuration={6000}
          onClose={handleCloseSnackbar}
          anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
        >
          <Alert onClose={handleCloseSnackbar} severity={snackbar.severity} sx={{ width: '100%' }}>
            {snackbar.message}
          </Alert>
        </Snackbar>
      </div>
    </ThemeProvider>
    </div>
  );
};

export default LineTableMaterial;
