import React, { useState, useMemo } from 'react';
import {
  Alert,
  CircularProgress,
  MenuItem,
  Popover,
  Select,
  Snackbar,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
} from '@mui/material';
import { ThemeProvider, createTheme } from '@mui/material/styles';
import Cookies from 'js-cookie';
import { formatCurrency } from '../../utilities/currency';

/* globals gettext */

/**
 * ActualTooltip component - displays transaction details for a budget category
 * When clicked, shows a popover with a table of transactions and recategorize options.
 */
const ActualTooltip = ({
  categoryId,
  categoryName,
  amount,
  month,
  allAccounts,
  apiUrls,
  teamSlug,
}) => {
  const [anchorEl, setAnchorEl] = useState(null);
  const [transactions, setTransactions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [snackbar, setSnackbar] = useState({ open: false, message: '', severity: 'info' });

  // Create MUI theme that adapts to existing theme
  const theme = useMemo(() => {
    const isDarkMode = document.documentElement.classList.contains('dark') ||
                       window.matchMedia('(prefers-color-scheme: dark)').matches;
    return createTheme({
      palette: {
        mode: isDarkMode ? 'dark' : 'light',
      },
    });
  }, []);

  // Filter accounts to show only expense/income categories (exclude current category)
  const categoryOptions = useMemo(() => {
    return allAccounts
      .filter(account => {
        // SimpleAccountSerializer provides account_type directly
        const accountType = account.account_type || account.accountType;
        return accountType === 'expense' || accountType === 'income';
      })
      .filter(account => account.id !== parseInt(categoryId))
      .sort((a, b) => (a.account_number || a.accountNumber || 0) - (b.account_number || b.accountNumber || 0));
  }, [allAccounts, categoryId]);

  const handleClick = async (event) => {
    setAnchorEl(event.currentTarget);
    await fetchTransactions();
  };

  const handleClose = () => {
    setAnchorEl(null);
  };

  const fetchTransactions = async () => {
    setLoading(true);
    try {
      const response = await fetch(
        `${apiUrls.lines}?account=${categoryId}&month=${month}`,
        {
          credentials: 'same-origin',
        }
      );
      const data = await response.json();
      // Handle both paginated and non-paginated responses
      setTransactions(data.results || data);
    } catch (error) {
      console.error('Failed to fetch transactions:', error);
      setSnackbar({ open: true, message: gettext('Failed to load transactions'), severity: 'error' });
    } finally {
      setLoading(false);
    }
  };

  const handleRecategorize = async (lineId, newCategoryId) => {
    try {
      const response = await fetch(`${apiUrls.lines}${lineId}/recategorize/`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': Cookies.get('csrftoken'),
        },
        body: JSON.stringify({ new_category_id: newCategoryId }),
      });

      if (response.ok) {
        // Remove the recategorized transaction from local state
        setTransactions(transactions.filter(t => (t.line_id || t.lineId) !== lineId));
        setSnackbar({ open: true, message: gettext('Transaction recategorized'), severity: 'success' });
      } else {
        throw new Error('Failed to recategorize');
      }
    } catch (error) {
      console.error('Failed to recategorize:', error);
      setSnackbar({ open: true, message: gettext('Failed to recategorize'), severity: 'error' });
    }
  };

  function formatWeekDayDate(date) {
  // Get weekday (short)
  const weekday = new Intl.DateTimeFormat('en-US', { weekday: 'short' }).format(date);
  const day = date.getDate();

  // Determine ordinal suffix
  let suffix = 'th';
  if (day === 1 || day === 21 || day === 31) suffix = 'st';
  else if (day === 2 || day === 22) suffix = 'nd';
  else if (day === 3 || day === 23) suffix = 'rd';

  return `${weekday}, ${day}${suffix}`;
}

  // Calculate amount display based on inflow/outflow
  const getAmount = (tx) => {
    const inflow = parseFloat(tx.inflow) || 0;
    const outflow = parseFloat(tx.outflow) || 0;
    return inflow > 0 ? inflow : -outflow;
  };

  const open = Boolean(anchorEl);

  return (
    <ThemeProvider theme={theme}>
      <span
        className="font-mono cursor-pointer hover:underline hover:text-primary"
        onClick={handleClick}
        title={gettext('Click to view transaction details')}
      >
        {formatCurrency(parseFloat(amount))}
      </span>

      <Popover
        open={open}
        anchorEl={anchorEl}
        onClose={handleClose}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
        transformOrigin={{ vertical: 'top', horizontal: 'center' }}
      >
        <div className="p-4 min-w-[500px] max-w-[700px] max-h-[400px] overflow-auto">
          <h3 className="font-bold mb-2 text-lg">
            {categoryName} - {gettext('Transactions')}
          </h3>

          {loading ? (
            <div className="flex justify-center py-8">
              <CircularProgress size={32} />
            </div>
          ) : transactions.length > 0 ? (
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>{gettext('Date')}</TableCell>
                  <TableCell>{gettext('Payee')}</TableCell>
                  <TableCell>{gettext('Memo')}</TableCell>
                  <TableCell align="right">{gettext('Amount')}</TableCell>
                  <TableCell>{gettext('Recategorize')}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {transactions.map((tx) => {
                  const lineId = tx.line_id || tx.lineId;
                  return (
                    <TableRow key={lineId}>
                      <TableCell className="whitespace-nowrap">
                        {formatWeekDayDate(new Date(tx.date))}
                      </TableCell>
                      <TableCell className="max-w-[120px] truncate">
                        {tx.payee_name || tx.payeeName || '-'}
                      </TableCell>
                      <TableCell className="max-w-[150px] truncate" title={tx.description}>
                        {tx.description || '-'}
                      </TableCell>
                      <TableCell align="right" className="whitespace-nowrap font-mono">
                        {formatCurrency(getAmount(tx))}
                      </TableCell>
                      <TableCell>
                        <Select
                          size="small"
                          value=""
                          displayEmpty
                          onChange={(e) => handleRecategorize(lineId, e.target.value)}
                          sx={{ minWidth: 120, fontSize: '0.875rem' }}
                        >
                          <MenuItem value="" disabled>
                            {gettext('Move to...')}
                          </MenuItem>
                          {categoryOptions.map(account => (
                            <MenuItem key={account.id} value={account.id}>
                              {account.name}
                            </MenuItem>
                          ))}
                        </Select>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          ) : (
            <p className="text-gray-500 py-4 text-center">
              {gettext('No transactions found')}
            </p>
          )}

          <div className="mt-3 pt-2 border-t text-sm text-gray-500">
            {transactions.length} {transactions.length === 1 ? gettext('transaction') : gettext('transactions')} | {gettext('Total')}: {formatCurrency(parseFloat(amount))}
          </div>
        </div>
      </Popover>

      <Snackbar
        open={snackbar.open}
        autoHideDuration={3000}
        onClose={() => setSnackbar({ ...snackbar, open: false })}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert
          onClose={() => setSnackbar({ ...snackbar, open: false })}
          severity={snackbar.severity}
          sx={{ width: '100%' }}
        >
          {snackbar.message}
        </Alert>
      </Snackbar>
    </ThemeProvider>
  );
};

export default ActualTooltip;
