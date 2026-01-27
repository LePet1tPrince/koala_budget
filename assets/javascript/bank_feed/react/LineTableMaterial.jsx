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
import { Alert, Box, Checkbox, IconButton, Snackbar, ToggleButton, ToggleButtonGroup, Toolbar, Tooltip, Typography } from '@mui/material';
import React, { useEffect, useMemo, useState } from 'react';
import { ThemeProvider, createTheme } from '@mui/material/styles';

import DateRangePicker from '../../common/DateRangePicker';
import EditTransactionModal from './EditTransactionModal';
import MaterialTable from '@material-table/core';
import { formatCurrency } from '../../utilities/currency';

/* globals gettext */







/**
 * LineTableMaterial component - displays and edits lines using Material-Table
 * Drop-in replacement for LineTable component
 */
const LineTableMaterial = ({
  lines,
  selectedAccount,
  allAccounts,
  onAdd,
  onDelete,
  onEditTransaction,
  selectedIds = new Set(),
  onSelectionChange,
  onFilterModeChange,
}) => {
  // Date range filter state (YYYY-MM-DD strings)
  const [filterStart, setFilterStart] = useState('');
  const [filterEnd, setFilterEnd] = useState('');

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
    // Clear selected transactions when switching views
    if (onSelectionChange) {
      onSelectionChange(new Set());
    }
    // Notify parent of filter mode change
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

  // Format date for display (handles both Date objects and strings)
  const formatDate = (dateValue) => {
    if (!dateValue) return '';
    const date = dateValue instanceof Date ? dateValue : new Date(dateValue);
    return date.toLocaleDateString();
  };

  // Check if a row can be edited (at least payee/description can always be edited)
  const canEdit = () => {
    // All transactions can be edited for payee/description
    // Even Plaid transactions can have payee/description updated
    return true;
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

    // Apply date range filter
    if (filterStart || filterEnd) {
      const s = filterStart ? new Date(filterStart) : null;
      const e = filterEnd ? new Date(filterEnd) : null;
      // make end of day inclusive
      const eInclusive = e ? new Date(e.getFullYear(), e.getMonth(), e.getDate(), 23, 59, 59, 999) : null;
      filtered = filtered.filter((l) => {
        if (!l.postedDate) return false;
        const d = l.postedDate instanceof Date ? l.postedDate : new Date(l.postedDate);
        if (s && d < s) return false;
        if (eInclusive && d > eInclusive) return false;
        return true;
      });
    }

    return filtered;
  }, [lines, filterStart, filterEnd, filterMode]);

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
      title: gettext('Payee'),
      field: 'payee',
      render: (rowData) => rowData.payee || '',
    },
    {
      title: gettext('Description'),
      field: 'description',
    },
    // Edit action column
    {
      title: '',
      field: 'actions',
      width: 50,
      sorting: false,
      render: (rowData) => (
        <Tooltip title={gettext('Edit')} arrow placement="top">
          <IconButton
            size="small"
            onClick={(e) => {
              e.stopPropagation();
              handleEditClick(rowData);
            }}
            disabled={!canEdit(rowData)}
          >
            <EditIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      ),
      headerStyle: { width: 50, paddingLeft: 4, paddingRight: 4 },
      cellStyle: { width: 50, paddingLeft: 4, paddingRight: 4 },
    },
    {
      title: '',
      field: 'source',
      width: 30,
      render: (rowData) => {
        const source = rowData.source;
        let letter = 'S';
        let tooltip = gettext('System transaction');
        let color = 'gray';

        if (source === 'plaid') {
          letter = 'P';
          tooltip = gettext('Plaid transaction');
          color = 'blue';
        } else if (source === 'csv') {
          letter = 'U';
          tooltip = gettext('Uploaded transaction');
          color = 'orange';
        } else if (source === 'manual') {
          letter = 'M';
          tooltip = gettext('Manual transaction');
          color = 'purple';
        } else if (source === 'ledger') {
          letter = 'L';
          tooltip = gettext('Ledger transaction');
          color = 'green';
        }

        return (
          <Tooltip title={tooltip} arrow placement="top">
            <span className={`inline-flex items-center justify-center w-5 h-5 rounded text-xs font-semibold bg-${color}-100 text-${color}-700 cursor-default`}>
              {letter}
            </span>
          </Tooltip>
        );
      },
      headerStyle: { width: 30, paddingLeft: 4, paddingRight: 4 },
      cellStyle: { width: 30, paddingLeft: 4, paddingRight: 4 },
    },
  ];

  // Handle delete row
  const handleRowDelete = async (oldData) => {
    try {
      await onDelete(oldData.id);
      showSnackbar(gettext('Transaction deleted successfully'), 'success');
    } catch (error) {
      console.error('Failed to delete transaction:', error);
      showSnackbar(gettext('Failed to delete transaction'), 'error');
      throw error;
    }
  };

  if (!selectedAccount) {
    return (
      <div className="alert alert-info">
        <i className="fa fa-info-circle"></i>
        <span>{gettext('Please select an account to view lines')}</span>
      </div>
    );
  }

  return (
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
            <ToggleButton value="to_review">{gettext('To Review')}</ToggleButton>
            <ToggleButton value="reconciled">{gettext('Reconciled')}</ToggleButton>
            <ToggleButton value="archived">{gettext('Archived')}</ToggleButton>
          </ToggleButtonGroup>
        </div>

        {/* Date Range Filter */}
        <div className="flex items-center justify-between">
          <div>
            <DateRangePicker
              startDate={filterStart}
              endDate={filterEnd}
              onApply={(s, e) => {
                setFilterStart(s);
                setFilterEnd(e);
              }}
            />
          </div>
          <div className="text-sm text-gray-500">
            {filteredLines.length} {gettext('lines')}
          </div>
        </div>

        {/* Material Table */}
        <MaterialTable
          title=""
          columns={columns}
          data={filteredLines}
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
          options={{
            actionsColumnIndex: -1,
            pageSize: 10,
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
                };
              }
              return {};
            },
          }}
          editable={{
            onRowDelete: handleRowDelete,
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
              labelDisplayedRows: gettext('lines'),
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
  );
};

export default LineTableMaterial;
