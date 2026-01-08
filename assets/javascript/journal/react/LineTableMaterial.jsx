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
import { Alert, Autocomplete, Snackbar, TextField } from '@mui/material';
/* globals gettext */
import React, { useMemo, useState } from 'react';
import { ThemeProvider, createTheme } from '@mui/material/styles';

import DateRangePicker from '../../common/DateRangePicker';
import MaterialTable from '@material-table/core';
import { formatCurrency } from '../../utilities/currency';

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

  // Format date for display
  const formatDate = (dateString) => {
    if (!dateString) return '';
    return new Date(dateString).toLocaleDateString();
  };

  // Create options array for Autocomplete (grouped by account number first letter)
  const categoryOptions = useMemo(() => {
    return allAccounts.map((account) => ({
      id: account.account_id,
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

  // Filter lines by selected date range
  const filteredLines = useMemo(() => {
    if (!filterStart && !filterEnd) return lines;
    const s = filterStart ? new Date(filterStart) : null;
    const e = filterEnd ? new Date(filterEnd) : null;
    // make end of day inclusive
    const eInclusive = e ? new Date(e.getFullYear(), e.getMonth(), e.getDate(), 23, 59, 59, 999) : null;
    return lines.filter((l) => {
      if (!l.date) return false;
      const d = new Date(l.date);
      if (s && d < s) return false;
      if (eInclusive && d > eInclusive) return false;
      return true;
    });
  }, [lines, filterStart, filterEnd]);

  // Define columns for Material-Table
  const columns = [
    {
      title: gettext('Date'),
      field: 'date',
      type: 'date',
      render: (rowData) => formatDate(rowData.date),
      validate: (rowData) => rowData.date ? true : { isValid: false, helperText: gettext('Date is required') },
    },
    {
      title: gettext('Category'),
      field: 'category',
      render: (rowData) => {
        const categoryId = rowData.category;
        const account = allAccounts.find((a) => a.account_id === categoryId);
        return account ? `${account.account_number} - ${account.name}` : '';
      },
      validate: (rowData) => rowData.category ? true : { isValid: false, helperText: gettext('Category is required') },
      editComponent: (props) => {
        // Find the currently selected option
        const selectedOption = categoryOptions.find(opt => opt.id === props.value) || null;

        return (
          <Autocomplete
            value={selectedOption}
            onChange={(_event, newValue) => {
              props.onChange(newValue ? newValue.id : '');
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
              // Clear inflow when outflow is set
              props.rowData.inflow = '0';
            }
          }}
        />
      ),
    },
    {
      title: gettext('Description'),
      field: 'description',
    },
    {
      title: gettext('Payee'),
      field: 'payee',
      lookup: payeeLookup,
      emptyValue: '',
    },
    {
      title: gettext('Cleared'),
      field: 'isCleared',
      type: 'boolean',
      render: (rowData) => rowData.isCleared ? <CheckIcon color="success" /> : '',
    },
    {
      title: gettext('Reconciled'),
      field: 'isReconciled',
      type: 'boolean',
      render: (rowData) => rowData.isReconciled ? <CheckIcon color="success" /> : '',
    },
  ];

  // Validate row data
  const validateRowData = (rowData) => {
    // Check required fields
    if (!rowData.date) {
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
      // Prepare data for API
      const lineData = {
        date: newData.date,
        account: selectedAccount?.account_id || '',
        category: newData.category,
        inflow: newData.inflow || '',
        outflow: newData.outflow || '',
        description: newData.description || '',
        payee: newData.payee || '',
        isCleared: !!newData.isCleared,
        isReconciled: !!newData.isReconciled,
      };

      await onAdd(lineData);
      showSnackbar(gettext('Line added successfully'), 'success');
    } catch (error) {
      console.error('Failed to add line:', error);
      showSnackbar(gettext('Failed to add line'), 'error');
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
        date: newData.date,
        account: newData.account,
        category: newData.category,
        inflow: newData.inflow || '',
        outflow: newData.outflow || '',
        description: newData.description || '',
        payee: newData.payee || '',
        isCleared: !!newData.isCleared,
        isReconciled: !!newData.isReconciled,
      };

      await onUpdate(oldData.lineId, lineData);
      showSnackbar(gettext('Line updated successfully'), 'success');
    } catch (error) {
      console.error('Failed to update line:', error);
      showSnackbar(gettext('Failed to update line'), 'error');
      throw error;
    }
  };

  // Handle delete row
  const handleRowDelete = async (oldData) => {
    try {
      await onDelete(oldData.lineId);
      showSnackbar(gettext('Line deleted successfully'), 'success');
    } catch (error) {
      console.error('Failed to delete line:', error);
      showSnackbar(gettext('Failed to delete line'), 'error');
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
              labelRowsSelect: gettext('lines'),
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
