import {
  Add as AddIcon,
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
  Search as SearchIcon,
} from '@mui/icons-material';
import { Alert, Box, Button, Checkbox, FormControlLabel, IconButton, InputAdornment, Snackbar, Switch, TextField, ToggleButton, ToggleButtonGroup, Toolbar, Tooltip, Typography } from '@mui/material';
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ThemeProvider, createTheme } from '@mui/material/styles';

import DateRangePicker from '../../common/DateRangePicker';
import EditTransactionModal from './EditTransactionModal';
import MaterialTable from '@material-table/core';
import { formatCurrency } from '../../utilities/currency';
import { formatDate as formatDateUtc, formatDateForInput } from '../utils';

/* globals gettext */







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
  bankFeedClient,
  onAdd,
  onDelete,
  onEditTransaction,
  selectedIds = new Set(),
  onSelectionChange,
  onFilterModeChange,
  hidden = false,
}) => {
  // Date range filter state (YYYY-MM-DD strings)
  const [filterStart, setFilterStart] = useState('');
  const [filterEnd, setFilterEnd] = useState('');
  // Controlled page size so it survives data reloads
  const [pageSize, setPageSize] = useState(10);
  const [showUncategorizedOnly, setShowUncategorizedOnly] = useState(false);

  // Search state
  const [searchText, setSearchText] = useState('');
  const [searchAllAccounts, setSearchAllAccounts] = useState(false);
  const [allAccountResults, setAllAccountResults] = useState(null);
  const [searchLoading, setSearchLoading] = useState(false);
  const searchDebounceRef = useRef(null);

  // Snackbar state
  const [snackbar, setSnackbar] = useState({
    open: false,
    message: '',
    severity: 'info', // 'success', 'error', 'warning', 'info'
  });

  // Filter state for Feed/Reconciled/Archived toggle
  const [filterMode, setFilterMode] = useState('to_review');

  // Edit modal state
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editingTransaction, setEditingTransaction] = useState(null);
  const [modalMode, setModalMode] = useState('edit'); // 'create' | 'edit'

  // Clear selection and notify parent when filter mode changes
  useEffect(() => {
    setShowUncategorizedOnly(false);
    if (onSelectionChange) {
      onSelectionChange(new Set());
    }
    if (onFilterModeChange) {
      onFilterModeChange(filterMode);
    }
  }, [filterMode]);

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

  // Search all accounts via backend API (debounced)
  const searchAllAccountsBackend = useCallback(async (query) => {
    if (!query.trim() || !bankFeedClient) {
      setAllAccountResults(null);
      return;
    }
    setSearchLoading(true);
    try {
      const results = [];
      let data = await bankFeedClient.bankFeedFeedList({ teamSlug, search: query });
      results.push(...(data.results || []));
      while (data.next) {
        const nextPage = Number(new URL(data.next, window.location.origin).searchParams.get('page'));
        if (!nextPage) break;
        data = await bankFeedClient.bankFeedFeedList({ teamSlug, search: query, page: nextPage });
        results.push(...(data.results || []));
      }
      setAllAccountResults(results);
    } catch (err) {
      console.error('Search failed:', err);
    } finally {
      setSearchLoading(false);
    }
  }, [bankFeedClient, teamSlug]);

  useEffect(() => {
    if (!searchAllAccounts) {
      setAllAccountResults(null);
      return;
    }
    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
    searchDebounceRef.current = setTimeout(() => {
      searchAllAccountsBackend(searchText);
    }, 400);
    return () => clearTimeout(searchDebounceRef.current);
  }, [searchText, searchAllAccounts, searchAllAccountsBackend]);

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

  // Filter lines by selected date range and filter mode
  const filteredLines = useMemo(() => {
    if (!Array.isArray(lines)) return [];
    let filtered = lines;

    // Apply filter mode (Feed/Reconciled/Archived)
    // Handle both camelCase (from generated API client) and snake_case (raw API)
    const isArchived = (l) => l.isArchived ?? l.is_archived ?? false;
    const isReconciled = (l) => l.isReconciled ?? l.is_reconciled ?? false;

    if (filterMode === 'to_review') {
      // To Review: not reconciled and not archived
      filtered = filtered.filter((l) => !isReconciled(l) && !isArchived(l));
    } else if (filterMode === 'reconciled') {
      // Reconciled: reconciled and not archived
      filtered = filtered.filter((l) => isReconciled(l) && !isArchived(l));
    } else if (filterMode === 'archived') {
      // Archived: show archived transactions
      filtered = filtered.filter((l) => isArchived(l));
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

    // Apply uncategorized filter
    if (showUncategorizedOnly) {
      filtered = filtered.filter((l) => !l.category);
    }

    // Apply client-side search for current account mode
    if (searchText.trim() && !searchAllAccounts) {
      const q = searchText.trim().toLowerCase();
      filtered = filtered.filter((l) => {
        const payee = (l.payee || l.merchantName || l.merchant_name || '').toLowerCase();
        const category = (l.category || '').toLowerCase();
        const description = (l.description || '').toLowerCase();
        const inflow = String(l.inflow || '');
        const outflow = String(l.outflow || '');
        return payee.includes(q) || category.includes(q) || description.includes(q) || inflow.includes(q) || outflow.includes(q);
      });
    }

    return filtered;
  }, [lines, filterStart, filterEnd, filterMode, showUncategorizedOnly, searchText, searchAllAccounts]);

  // Determine which lines to display: all-account search results or filtered local lines
  const displayLines = (searchAllAccounts && searchText.trim() && allAccountResults) ? allAccountResults : filteredLines;

  // Handle row selection
  const handleRowSelect = (rowId, checked) => {
    if (!onSelectionChange) return;
    const newSelected = new Set(selectedIds);
    if (checked) {
      newSelected.add(rowId);
    } else {
      newSelected.delete(rowId);
    }
    onSelectionChange(newSelected);
  };

  // Handle select all
  const handleSelectAll = (checked) => {
    if (!onSelectionChange) return;
    if (checked) {
      const allIds = new Set(displayLines.map(l => l.id));
      onSelectionChange(allIds);
    } else {
      onSelectionChange(new Set());
    }
  };

  // Check if all rows are selected
  const allSelected = displayLines.length > 0 && displayLines.every(l => selectedIds.has(l.id));
  const someSelected = displayLines.some(l => selectedIds.has(l.id)) && !allSelected;

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
          onChange={(e) => handleRowSelect(rowData.id, e.target.checked)}
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
      render: (rowData) => formatDate(rowData.postedDate),
    },
    {
      title: gettext('Payee'),
      field: 'payee',
      render: (rowData) => rowData.payee || '',
    },
    {
      title: gettext('Category'),
      field: 'category',
      render: (rowData) => {
        const category = rowData.category;
        return category ? gettext(category.name) : gettext('Uncategorized');
      },
    },
    {
      title: gettext('Inflow'),
      field: 'inflow',
      type: 'numeric',
      render: (rowData) => {
        const value = rowData.inflow;
        return value && parseFloat(value) > 0 ? formatCurrency(value) : '';
      },
    },
    {
      title: gettext('Outflow'),
      field: 'outflow',
      type: 'numeric',
      render: (rowData) => {
        const value = rowData.outflow;
        return value && parseFloat(value) > 0 ? formatCurrency(value) : '';
      },
    },
    {
      title: gettext('Description'),
      field: 'description',
      render: (rowData) => {
        const desc = rowData.description || '';
        return desc.length > 26 ? desc.slice(0, 26) + '...' : desc;
      },
    },
    {
      title: '',
      field: 'source',
      width: 30,
      render: (rowData) => {
        const source = rowData.source;
        // Class names must be full literals, otherwise Tailwind's compiler
        // can't see them and strips them from the build.
        let letter = 'S';
        let tooltip = gettext('System transaction');
        let colorClasses = 'bg-gray-100 text-gray-700';

        if (source === 'plaid') {
          letter = 'P';
          tooltip = gettext('Plaid transaction');
          colorClasses = 'bg-blue-100 text-blue-700';
        } else if (source === 'csv') {
          letter = 'U';
          tooltip = gettext('Uploaded transaction');
          colorClasses = 'bg-orange-100 text-orange-700';
        } else if (source === 'manual') {
          letter = 'M';
          tooltip = gettext('Manual transaction');
          colorClasses = 'bg-purple-100 text-purple-700';
        } else if (source === 'ledger') {
          letter = 'L';
          tooltip = gettext('Ledger transaction');
          colorClasses = 'bg-green-100 text-green-700';
        }

        return (
          <Tooltip title={tooltip} arrow placement="top">
            <span className={`inline-flex items-center justify-center w-5 h-5 rounded text-xs font-semibold ${colorClasses} cursor-default`}>
              {letter}
            </span>
          </Tooltip>
        );
      },
      headerStyle: { width: 30, paddingLeft: 4, paddingRight: 4 },
      cellStyle: { width: 30, paddingLeft: 4, paddingRight: 4 },
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
        {/* Filter Mode Toggle */}
        <div className="flex items-center justify-center">
          <ToggleButtonGroup
            color="primary"
            value={filterMode}
            exclusive
            onChange={(_event, newMode) => {
              if (newMode !== null) {
                setFilterMode(newMode);
              }
            }}
            aria-label="Transaction filter"
          >
            <ToggleButton value="to_review" data-testid="filter-to-review">{gettext('To Review')}</ToggleButton>
            <ToggleButton value="reconciled" data-testid="filter-reconciled">{gettext('Reconciled')}</ToggleButton>
            <ToggleButton value="archived" data-testid="filter-archived">{gettext('Archived')}</ToggleButton>
          </ToggleButtonGroup>
        </div>

        {/* Date Range Filter + Search */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <DateRangePicker
              startDate={filterStart}
              endDate={filterEnd}
              onApply={(s, e) => {
                setFilterStart(s);
                setFilterEnd(e);
              }}
            />
            {filterMode === 'to_review' && (
              <Button
                size="small"
                variant={showUncategorizedOnly ? 'contained' : 'outlined'}
                onClick={() => setShowUncategorizedOnly(v => !v)}
              >
                {gettext('Uncategorized')}
              </Button>
            )}
            <TextField
              size="small"
              placeholder={gettext('Search payee, category, amount, description…')}
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              slotProps={{
                input: {
                  startAdornment: (
                    <InputAdornment position="start">
                      <SearchIcon fontSize="small" />
                    </InputAdornment>
                  ),
                  endAdornment: searchText ? (
                    <InputAdornment position="end">
                      <IconButton size="small" onClick={() => setSearchText('')}>
                        <ClearIcon fontSize="small" />
                      </IconButton>
                    </InputAdornment>
                  ) : null,
                },
              }}
              sx={{ minWidth: 280 }}
            />
            <FormControlLabel
              control={
                <Switch
                  size="small"
                  checked={searchAllAccounts}
                  onChange={(e) => setSearchAllAccounts(e.target.checked)}
                />
              }
              label={<Typography variant="body2">{gettext('All accounts')}</Typography>}
              sx={{ ml: 0, whiteSpace: 'nowrap' }}
            />
          </div>
          <div className="text-sm text-gray-500">
            {searchLoading && <span className="loading loading-spinner loading-xs mr-1"></span>}
            {displayLines.length} {gettext('lines')}
          </div>
        </div>

        {/* Material Table */}
        <MaterialTable
          title=""
          columns={columns}
          data={displayLines}
          components={{
            Toolbar: () => (
              <Toolbar variant="dense" sx={{ pl: 1, pr: 1, minHeight: 48 }}>
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
                <Tooltip title={gettext('Add Transaction')} arrow placement="top">
                  <IconButton
                    size="small"
                    onClick={handleAddClick}
                    color="primary"
                    data-testid="add-transaction-btn"
                  >
                    <AddIcon />
                  </IconButton>
                </Tooltip>
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
            emptyRowsWhenPaging: false,
            rowStyle: (rowData) => {
              // Style uncategorized transactions with grey text in 'to_review' mode only
              if (filterMode === 'to_review' && rowData.category === null) {
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
