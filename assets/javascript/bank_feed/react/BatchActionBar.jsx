import React, { useState, useMemo } from 'react';
import {
  Autocomplete,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Menu,
  MenuItem,
  Paper,
  Slide,
  TextField,
  Typography,
} from '@mui/material';
import {
  Close as CloseIcon,
  Category as CategoryIcon,
  SwapHoriz as SwapHorizIcon,
  Person as PersonIcon,
  Description as DescriptionIcon,
  Archive as ArchiveIcon,
  Unarchive as UnarchiveIcon,
  ContentCopy as ContentCopyIcon,
  FileDownload as FileDownloadIcon,
} from '@mui/icons-material';

/* globals gettext */

/**
 * BatchActionBar - Floating action bar for batch operations on selected transactions.
 * Appears at the bottom of the screen when rows are selected.
 */
const BatchActionBar = ({
  selectedCount,
  selectedRows,
  allAccounts,
  bankFeedAccounts,
  onCategorize,
  onMoveAccount,
  onSetPayee,
  onSetDescription,
  onArchive,
  onUnarchive,
  onDuplicate,
  onExport,
  onClearSelection,
  showArchive = true,
  showUnarchive = false,
  filterMode = 'to_review',
}) => {
  // In archived view, only allow unarchive and export
  const isArchivedView = filterMode === 'archived';
  // Menu anchors
  const [categoryAnchor, setCategoryAnchor] = useState(null);
  const [accountAnchor, setAccountAnchor] = useState(null);

  // Dialog states
  const [payeeDialogOpen, setPayeeDialogOpen] = useState(false);
  const [descriptionDialogOpen, setDescriptionDialogOpen] = useState(false);
  const [payeeValue, setPayeeValue] = useState('');
  const [descriptionValue, setDescriptionValue] = useState('');

  // Category selection state
  const [selectedCategory, setSelectedCategory] = useState(null);

  // Create options array for category Autocomplete
  const categoryOptions = useMemo(() => {
    return allAccounts.map((account) => ({
      id: account.id,
      label: `${account.account_number} - ${account.name}`,
      accountNumber: account.account_number,
      name: account.name,
      firstLetter: String(account.account_number).charAt(0).toUpperCase(),
    })).sort((a, b) => -b.firstLetter.localeCompare(a.firstLetter));
  }, [allAccounts]);

  // Filter bank feed accounts (has_feed=true)
  const feedAccountOptions = useMemo(() => {
    return bankFeedAccounts.map((account) => ({
      id: account.id,
      label: account.name,
      name: account.name,
    }));
  }, [bankFeedAccounts]);

  // Handle category selection and close menu
  const handleCategorySelect = () => {
    if (selectedCategory) {
      onCategorize(selectedCategory.id);
      setCategoryAnchor(null);
      setSelectedCategory(null);
    }
  };

  // Handle account move
  const handleAccountSelect = (account) => {
    onMoveAccount(account.id);
    setAccountAnchor(null);
  };

  // Handle payee submit
  const handlePayeeSubmit = () => {
    if (payeeValue.trim()) {
      onSetPayee(payeeValue.trim());
      setPayeeDialogOpen(false);
      setPayeeValue('');
    }
  };

  // Handle description submit
  const handleDescriptionSubmit = () => {
    if (descriptionValue.trim()) {
      onSetDescription(descriptionValue.trim());
      setDescriptionDialogOpen(false);
      setDescriptionValue('');
    }
  };

  // Export to CSV
  const handleExport = () => {
    const headers = ['Date', 'Description', 'Merchant', 'Inflow', 'Outflow', 'Category', 'Account'];
    const csvRows = [headers.join(',')];

    selectedRows.forEach(row => {
      csvRows.push([
        row.postedDate,
        `"${(row.description || '').replace(/"/g, '""')}"`,
        `"${(row.merchantName || '').replace(/"/g, '""')}"`,
        row.inflow || '',
        row.outflow || '',
        row.category?.name || '',
        row.account?.name || '',
      ].join(','));
    });

    const blob = new Blob([csvRows.join('\n')], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `bank_transactions_${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
    URL.revokeObjectURL(url);

    if (onExport) {
      onExport();
    }
  };

  if (selectedCount === 0) return null;

  return (
    <>
      <Slide direction="up" in={selectedCount > 0}>
        <Paper
          elevation={6}
          sx={{
            position: 'fixed',
            bottom: 16,
            left: '50%',
            transform: 'translateX(-50%)',
            p: 2,
            display: 'flex',
            gap: 1,
            alignItems: 'center',
            zIndex: 1000,
            borderRadius: 2,
            maxWidth: '95vw',
            flexWrap: 'wrap',
            justifyContent: 'center',
          }}
        >
          <Typography variant="body2" sx={{ fontWeight: 'bold', mr: 1 }}>
            {selectedCount} {gettext('selected')}
          </Typography>

          {!isArchivedView && (
            <Button
              size="small"
              startIcon={<CategoryIcon />}
              onClick={(e) => setCategoryAnchor(e.currentTarget)}
            >
              {gettext('Categorize')}
            </Button>
          )}

          {!isArchivedView && (
            <Button
              size="small"
              startIcon={<SwapHorizIcon />}
              onClick={(e) => setAccountAnchor(e.currentTarget)}
            >
              {gettext('Move')}
            </Button>
          )}

          {!isArchivedView && (
            <Button
              size="small"
              startIcon={<PersonIcon />}
              onClick={() => setPayeeDialogOpen(true)}
            >
              {gettext('Set Payee')}
            </Button>
          )}

          {!isArchivedView && (
            <Button
              size="small"
              startIcon={<DescriptionIcon />}
              onClick={() => setDescriptionDialogOpen(true)}
            >
              {gettext('Set Description')}
            </Button>
          )}

          {showArchive && !isArchivedView && (
            <Button
              size="small"
              startIcon={<ArchiveIcon />}
              onClick={onArchive}
            >
              {gettext('Archive')}
            </Button>
          )}

          {showUnarchive && (
            <Button
              size="small"
              startIcon={<UnarchiveIcon />}
              onClick={onUnarchive}
            >
              {gettext('Unarchive')}
            </Button>
          )}

          {!isArchivedView && (
            <Button
              size="small"
              startIcon={<ContentCopyIcon />}
              onClick={onDuplicate}
            >
              {gettext('Duplicate')}
            </Button>
          )}

          <Button
            size="small"
            startIcon={<FileDownloadIcon />}
            onClick={handleExport}
          >
            {gettext('Export')}
          </Button>

          <IconButton size="small" onClick={onClearSelection}>
            <CloseIcon />
          </IconButton>
        </Paper>
      </Slide>

      {/* Category Selection Menu */}
      <Menu
        anchorEl={categoryAnchor}
        open={Boolean(categoryAnchor)}
        onClose={() => setCategoryAnchor(null)}
        PaperProps={{
          sx: { width: 350, maxHeight: 400, p: 2 },
        }}
      >
        <Box sx={{ p: 1 }}>
          <Autocomplete
            value={selectedCategory}
            onChange={(_event, newValue) => setSelectedCategory(newValue)}
            options={categoryOptions}
            groupBy={(option) => option.firstLetter}
            getOptionLabel={(option) => option.label}
            isOptionEqualToValue={(option, value) => option.id === value?.id}
            renderInput={(params) => (
              <TextField
                {...params}
                label={gettext('Select Category')}
                size="small"
                autoFocus
              />
            )}
            size="small"
          />
          <Box sx={{ mt: 2, display: 'flex', justifyContent: 'flex-end', gap: 1 }}>
            <Button onClick={() => setCategoryAnchor(null)}>{gettext('Cancel')}</Button>
            <Button
              variant="contained"
              onClick={handleCategorySelect}
              disabled={!selectedCategory}
            >
              {gettext('Apply')}
            </Button>
          </Box>
        </Box>
      </Menu>

      {/* Account Selection Menu */}
      <Menu
        anchorEl={accountAnchor}
        open={Boolean(accountAnchor)}
        onClose={() => setAccountAnchor(null)}
      >
        {feedAccountOptions.map((account) => (
          <MenuItem
            key={account.id}
            onClick={() => handleAccountSelect(account)}
          >
            {account.label}
          </MenuItem>
        ))}
      </Menu>

      {/* Payee Dialog */}
      <Dialog open={payeeDialogOpen} onClose={() => setPayeeDialogOpen(false)}>
        <DialogTitle>{gettext('Set Payee')}</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            margin="dense"
            label={gettext('Payee Name')}
            fullWidth
            value={payeeValue}
            onChange={(e) => setPayeeValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                handlePayeeSubmit();
              }
            }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPayeeDialogOpen(false)}>{gettext('Cancel')}</Button>
          <Button onClick={handlePayeeSubmit} variant="contained">
            {gettext('Apply')}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Description Dialog */}
      <Dialog open={descriptionDialogOpen} onClose={() => setDescriptionDialogOpen(false)}>
        <DialogTitle>{gettext('Set Description')}</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            margin="dense"
            label={gettext('Description')}
            fullWidth
            value={descriptionValue}
            onChange={(e) => setDescriptionValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                handleDescriptionSubmit();
              }
            }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDescriptionDialogOpen(false)}>{gettext('Cancel')}</Button>
          <Button onClick={handleDescriptionSubmit} variant="contained">
            {gettext('Apply')}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
};

export default BatchActionBar;
