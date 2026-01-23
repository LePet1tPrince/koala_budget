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
import { Alert, Autocomplete, Snackbar, TextField, ToggleButton, ToggleButtonGroup } from '@mui/material';
import React, { useMemo, useState } from 'react';
import { ThemeProvider, createTheme } from '@mui/material/styles';

import DateRangePicker from '../../common/DateRangePicker';
import MaterialTable from '@material-table/core';
import { ProperCase } from '../utils';
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
  allPayees,
  onAdd,
  onUpdate,
  onDelete,
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

  // Create options array for Autocomplete (grouped by account number first letter)
  const categoryOptions = useMemo(() => {
    return allAccounts.map((account) => ({
      id: account.id,
      label: `${account.account_number} - ${account.name}`,
      accountNumber: account.account_number,
      name: account.name,
      firstLetter: String(account.account_number).charAt(0).toUpperCase(),
    })).sort((a, b) => -b.firstLetter.localeCompare(a.firstLetter));
  }, [allAccounts]);

  const payeeLookup = useMemo(() => {
    const lookup = { '': gettext('None') };
    allPayees.forEach((payee) => {
      lookup[payee.id] = payee.name;
    });
    return lookup;
  }, [allPayees]);

  // Check if a row is read-only (Plaid transactions cannot be edited)
  const isReadOnly = (rowData) => {
    return rowData.source === 'plaid';
  };

  // Filter lines by selected date range and filter mode
  const filteredLines = useMemo(() => {
    if (!Array.isArray(lines)) return [];
    let filtered = lines;

    // Apply filter mode (Feed/Reconciled/Archived)
    if (filterMode === 'to_review') {
      // To Review: not reconciled and not archived
      filtered = filtered.filter((l) => !l.isReconciled && !l.isArchived);
    } else if (filterMode === 'completed') {
      // Reconciled: reconciled and not archived
      filtered = filtered.filter((l) => l.isReconciled && !l.isArchived);
    } else if (filterMode === 'archived') {
      // Archived: not implemented yet, show all for now
      filtered = filtered.filter((l) => l.isArchived);
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

  // Define columns for Material-Table
  const columns = [
    {
      title: gettext('Date'),
      field: 'postedDate',
      type: 'date',
      render: (rowData) => formatDate(rowData.postedDate),
      validate: (rowData) => rowData.postedDate ? true : { isValid: false, helperText: gettext('Date is required') },
      editable: (rowData) => !isReadOnly(rowData),
    },
    {
      title: gettext('Category'),
      field: 'category',
      render: (rowData) => {
        const category = rowData.category;
        return category ? gettext(category.name) : gettext('Uncategorized');
      },
      validate: (rowData) => rowData.category ? true : { isValid: false, helperText: gettext('Category is required') },
      editComponent: (props) => {
        // Find the currently selected option
        const currentCategory = props.rowData.category;
        const selectedOption = currentCategory ? categoryOptions.find(opt => opt.id === currentCategory.id) : null;

        return (
          <Autocomplete
            value={selectedOption}
            onChange={(_event, newValue) => {
              props.onChange(newValue ? { id: newValue.id, account_number: newValue.accountNumber, name: newValue.name } : null);
            }}
            options={categoryOptions}
            groupBy={(option) => option.firstLetter}
            getOptionLabel={(option) => option.label}
            isOptionEqualToValue={(option, value) => option.id === value.id}
            renderInput={(params) => (
              <TextField
                {...params}
                label={gettext('Category')}
                size="small"
                error={!props.value}
                helperText={!props.value ? gettext('Category is required') : ''}
              />
            )}
            size="small"
          />
        );
      },
      editable: (rowData) => !isReadOnly(rowData),
    },
    {
      title: gettext('Inflow'),
      field: 'inflow',
      type: 'numeric',
      render: (rowData) => {
        const value = rowData.inflow;
        return value && parseFloat(value) > 0 ? formatCurrency(value) : '';
      },
      editComponent: (props) => (
        <input
          type="number"
          step="0.01"
          value={props.value || ''}
          onChange={(e) => props.onChange(e.target.value)}
          onBlur={() => {
            if (props.value && parseFloat(props.value) > 0) {
              // Clear outflow when inflow is set
              props.rowData.outflow = '0';
            }
          }}
        />
      ),
      editable: (rowData) => !isReadOnly(rowData),
    },
    {
      title: gettext('Outflow'),
      field: 'outflow',
      type: 'numeric',
      render: (rowData) => {
        const value = rowData.outflow;
        return value && parseFloat(value) > 0 ? formatCurrency(value) : '';
      },
      editComponent: (props) => (
        <input
          type="number"
          step="0.01"
          value={props.value || ''}
          onChange={(e) => props.onChange(e.target.value)}
          onBlur={() => {
            if (props.value && parseFloat(props.value) > 0) {
              // Clear inflow when inflow is set
              props.rowData.inflow = '0';
            }
          }}
        />
      ),
      editable: (rowData) => !isReadOnly(rowData),
    },
    {
      title: gettext('Description'),
      field: 'description',
      editable: (rowData) => !isReadOnly(rowData),
    },
    {
      title: gettext('Source'),
      field: 'source',
      render: (rowData) => {
        const source = rowData.source;
        let label = ProperCase(source);
        let color = 'gray';

        if (source === 'plaid') {
          // label = 'Plaid';
          color = 'blue';
        } else if (source === 'ledger') {
          // label = 'Ledger';
          color = 'green';
        } else if (source === 'manual') {
          // label = 'Manual';
          color = 'orange';
        }

        return (
          <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-${color}-100 text-${color}-800`}>
            {label}
          </span>
        );
      },
      editable: 'never',
    },
  ];

  // Validate row data
  const validateRowData = (rowData) => {
    // Check required fields
    if (!rowData.postedDate) {
      return gettext('Date is required');
    }
    if (!rowData.category) {
      return gettext('Category is required');
    }

    // Validate that exactly one of inflow or outflow is specified
    const hasInflow = rowData.inflow && parseFloat(rowData.inflow) > 0;
    const hasOutflow = rowData.outflow && parseFloat(rowData.outflow) > 0;

    if (!hasInflow && !hasOutflow) {
      return gettext('Either inflow or outflow is required');
    }
    if (hasInflow && hasOutflow) {
      return gettext('Cannot have both inflow and outflow');
    }

    return null;
  };

  // Handle add row
  const handleRowAdd = async (newData) => {
    const error = validateRowData(newData);
    if (error) {
      showSnackbar(error, 'error');
      throw new Error(error);
    }

    try {
      // Prepare data for API - map bank feed format to expected format
      const lineData = {
        date: newData.postedDate,
        category: newData.category?.id || newData.category,
        inflow: newData.inflow || '',
        outflow: newData.outflow || '',
        description: newData.description || '',
        payee: '', // Not used in bank feed format
      };

      await onAdd(lineData);
      showSnackbar(gettext('Transaction added successfully'), 'success');
    } catch (error) {
      console.error('Failed to add transaction:', error);
      showSnackbar(gettext('Failed to add transaction'), 'error');
      throw error;
    }
  };

  // Handle update row
  const handleRowUpdate = async (newData, oldData) => {
    const error = validateRowData(newData);
    if (error) {
      showSnackbar(error, 'error');
      throw new Error(error);
    }

    try {
      // Prepare data for API
      const lineData = {
        date: newData.postedDate,
        category: newData.category?.id || newData.category,
        inflow: newData.inflow || '',
        outflow: newData.outflow || '',
        description: newData.description || '',
        payee: '', // Not used in bank feed format
        source: newData.source,
      };

      await onUpdate(oldData.id, lineData);
      showSnackbar(gettext('Transaction updated successfully'), 'success');
    } catch (error) {
      console.error('Failed to update transaction:', error);
      showSnackbar(gettext('Failed to update transaction'), 'error');
      throw error;
    }
  };

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
          }}
          editable={{
            onRowAdd: handleRowAdd,
            onRowUpdate: handleRowUpdate,
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
