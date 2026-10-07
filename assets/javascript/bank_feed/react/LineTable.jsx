import React, { Fragment, useEffect, useMemo, useRef, useState } from 'react';

import DateRangePicker from '../../common/DateRangePicker';
import EditTransactionModal from './EditTransactionModal';
import TransferMatchPanel from './TransferMatchPanel';
import { Toast } from '../../common/Toast';
import { Dropdown, MenuRow, ReconciledLock, SortArrow, TablePager } from './LineTableParts';
import { usePlaidLinkFlow } from './PlaidLinkButton';
import { formatCurrency } from '../../utilities/currency';
import { formatDate as formatDateUtc } from '../utils';
import { PAGE_SIZE_OPTIONS } from '../feedQuery';
import Icon from '../../common/Icon';

/* globals gettext, interpolate */

const NO_MATCHES = new Map();
// Stable default, so the rows don't re-render for a fresh `new Set()` each time
const NO_PENDING = new Set();

/** The possible-transfer suggestion a row belongs to, if any. */
const matchFor = (matchByTxId, row) => matchByTxId.get(row.importedTransactionId ?? row.imported_transaction_id);

// Column widths are fixed (the table is `table-fixed`) so the Description column
// absorbs whatever the others leave behind, and long payees or categories
// ellipsis rather than wrapping the row height.
const COLUMNS = [
  { key: 'select', label: '', width: 'w-12', sortable: false },
  { key: 'postedDate', label: gettext('Date'), width: 'w-[6rem]', sortable: true },
  { key: 'account', label: gettext('Account'), width: 'w-[9rem]', sortable: true, truncate: true },
  { key: 'payee', label: gettext('Payee'), width: 'w-[9rem]', sortable: true, truncate: true },
  { key: 'category', label: gettext('Category'), width: 'w-[9rem]', sortable: true, truncate: true },
  { key: 'inflow', label: gettext('Inflow'), width: 'w-[6rem]', sortable: true, align: 'text-right' },
  { key: 'outflow', label: gettext('Outflow'), width: 'w-[6rem]', sortable: true, align: 'text-right' },
  { key: 'description', label: gettext('Description'), sortable: true, truncate: true },
  { key: 'isReconciled', label: gettext('Reconciled'), width: 'w-[6.5rem]', sortable: false, align: 'text-center' },
];

/**
 * Whether a row has been categorized.
 *
 * A split is apportioned across several categories and therefore has no single
 * one, so its `category` is null -- the same shape an uncategorized row has.
 */
const isCategorized = (row) => Boolean(row.category) || Boolean(row.isSplit);

/**
 * What the category cell says on hover. A split has no single category, so it
 * lists the legs -- which answers the obvious question without opening the row.
 */
const categoryTitle = (row) => {
  if (row.isSplit) {
    return (row.splits || [])
      .map((leg) => `${leg.categoryName ?? leg.category_name}: ${formatCurrency(Math.abs(Number(leg.amount)))}`)
      .join(' · ');
  }
  return row.category ? row.category.name : gettext('Uncategorized');
};

/**
 * The account filter: every account on a feed, or any set of them. Grouped as
 * the account cards are (by account group), in the same order.
 */
const AccountFilter = ({ accounts, selected, onChange }) => {
  const [open, setOpen] = useState(false);
  const chosen = new Set(selected);
  const label =
    selected.length === 0
      ? gettext('All accounts')
      : selected.length === 1
        ? accounts.find((a) => a.id === selected[0])?.name ?? gettext('1 account')
        : interpolate(gettext('%s accounts'), [selected.length]);

  const groups = [];
  accounts.forEach((account) => {
    const name = account.account_group_name ?? account.accountGroupName ?? '';
    const last = groups[groups.length - 1];
    if (last && last.name === name) last.accounts.push(account);
    else groups.push({ name, accounts: [account] });
  });

  const toggle = (id) => {
    const next = chosen.has(id) ? selected.filter((a) => a !== id) : [...selected, id];
    // Every account ticked is the same as none: say "All accounts" rather than a list.
    onChange(next.length === accounts.length ? [] : next);
  };

  return (
    <Dropdown
      open={open}
      onOpenChange={setOpen}
      panelClassName="max-h-80 overflow-y-auto"
      trigger={({ toggle: toggleOpen, open: isOpen }) => (
        <button
          type="button"
          className={`btn btn-sm ${selected.length ? 'btn-primary' : 'btn-outline'} max-w-[14rem]`}
          aria-haspopup="menu"
          aria-expanded={isOpen}
          onClick={toggleOpen}
          data-testid="account-filter-btn"
        >
          <span className="truncate">{label}</span>
          <span aria-hidden="true">▾</span>
        </button>
      )}
    >
      {({ close }) => (
        <>
          <MenuRow
            testId="account-filter-all"
            checked={selected.length === 0}
            label={gettext('All accounts')}
            onClick={() => {
              onChange([]);
              close();
            }}
          />
          {groups.map((group) => (
            <Fragment key={group.name}>
              <div className="px-3 pt-2 pb-1 text-xs font-semibold uppercase text-base-content/70">{group.name}</div>
              {group.accounts.map((account) => (
                <MenuRow
                  key={account.id}
                  testId={`account-filter-${account.id}`}
                  checked={chosen.has(account.id)}
                  label={account.name}
                  onClick={() => toggle(account.id)}
                />
              ))}
            </Fragment>
          ))}
        </>
      )}
    </Dropdown>
  );
};

/**
 * The bank feed table: one page of the Inbox, as the server filtered, sorted and
 * paged it (`apps/bank_feed/services/feed_query.py`).
 *
 * Presentational. What is being looked at -- accounts, view, quick filters,
 * dates, sort, page -- belongs to `LineApp`, which requests one page whenever it
 * changes; every control here reports a change rather than applying it.
 */
const LineTable = ({
  lines,
  total,
  counts,
  query,
  onQueryChange,
  accounts = [],
  showAccountColumn = true,
  refetching = false,
  allAccounts,
  allPayees = [],
  categorySuggestions = {},
  book,
  defaultAccountId = null,
  onAdd,
  onEditTransaction,
  selectedIds = new Set(),
  onToggleRows,
  selectAllMatching,
  onUploadClick,
  onRefresh,
  refreshing = false,
  uploadDisabled = false,
  plaidClient,
  onLinkSuccess,
  onOpenTransferLeg,
  feedAccountIds = new Set(),
  highlightId = null,
  transferCount = 0,
  matchByTxId = NO_MATCHES,
  onMatch,
  onDismissMatch,
  onOpenMatchCounterpart,
  pendingIds = NO_PENDING,
}) => {
  const [quickFiltersOpen, setQuickFiltersOpen] = useState(false);
  const [actionsOpen, setActionsOpen] = useState(false);

  // Plaid "Link Bank Account" flow, triggered from the dropdown menu below
  const { handleClick: handleLinkBankClick, loading: linkBankLoading, modal: linkBankModal } = usePlaidLinkFlow({
    book,
    allAccounts,
    onSuccess: onLinkSuccess,
    plaidClient,
  });

  const [snackbar, setSnackbar] = useState({ open: false, message: '', severity: 'info' });

  const voided = query.view === 'voided';
  const quickFilters = query.quickFilters;

  // The feed row whose possible-transfer panel is open (one at a time)
  const [openMatchId, setOpenMatchId] = useState(null);

  // Edit modal state
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editingTransaction, setEditingTransaction] = useState(null);
  const [modalMode, setModalMode] = useState('edit'); // 'create' | 'edit'

  // Id of the row whose checkbox was last clicked, used as the anchor for
  // shift-click range selection (within the page on screen)
  const [lastCheckedId, setLastCheckedId] = useState(null);
  useEffect(() => setLastCheckedId(null), [lines]);

  const tableBodyRef = useRef(null);

  // The table scrolls sideways on narrow screens, but a possible-transfer panel
  // under a row must stay readable: it is pinned to the left edge and sized to
  // the visible width of the scroll area, not the full width of the table.
  const scrollRef = useRef(null);
  const [scrollWidth, setScrollWidth] = useState(null);
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(() => setScrollWidth(el.clientWidth));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // A row the page was asked to show (the other side of a transfer): scroll to
  // it once it is on screen. The flash itself is the `feed-row-flash` class.
  useEffect(() => {
    if (highlightId == null) return;
    requestAnimationFrame(() => {
      tableBodyRef.current
        ?.querySelector(`[data-testid="feed-row-${highlightId}"]`)
        ?.scrollIntoView({ block: 'center', behavior: 'smooth' });
    });
  }, [highlightId, lines]);

  const columns = useMemo(
    () => COLUMNS.filter((col) => col.key !== 'account' || showAccountColumn),
    [showAccountColumn]
  );
  const accountsById = useMemo(() => new Map(accounts.map((a) => [a.id, a])), [accounts]);

  const setQuickFilters = (next) => onQueryChange({ quickFilters: next });
  const toggleQuickFilter = (key) => {
    const next = { ...quickFilters, [key]: !quickFilters[key] };
    if (key === 'toReview' && next.toReview) next.reconciled = false;
    if (key === 'reconciled' && next.reconciled) next.toReview = false;
    setQuickFilters(next);
  };
  const activeQuickFilterCount = Object.values(quickFilters).filter(Boolean).length;

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
      // Not awaited: the row already shows the edit and is marked as saving,
      // so the modal closes at once. A refusal is reported by the feed.
      onEditTransaction(data, editingTransaction);
    }
  };

  const toggleSort = (key) => {
    const sort = query.sort;
    onQueryChange({
      sort: sort.key === key ? { key, dir: sort.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'asc' },
    });
  };

  // Handle row selection. Shift-click extends the selection to every row
  // between the last-clicked checkbox and this one (in displayed order, on this page).
  const handleRowSelect = (row, checked, shiftKey) => {
    if (!onToggleRows) return;
    if (shiftKey && lastCheckedId !== null) {
      const ids = lines.map((l) => l.id);
      const anchorIndex = ids.indexOf(lastCheckedId);
      const targetIndex = ids.indexOf(row.id);
      if (anchorIndex !== -1 && targetIndex !== -1) {
        const [start, end] = anchorIndex < targetIndex ? [anchorIndex, targetIndex] : [targetIndex, anchorIndex];
        onToggleRows(lines.slice(start, end + 1), checked);
        setLastCheckedId(row.id);
        return;
      }
    }
    onToggleRows([row], checked);
    setLastCheckedId(row.id);
  };

  const pageSelected = lines.length > 0 && lines.every((l) => selectedIds.has(l.id));
  const somePageSelected = lines.some((l) => selectedIds.has(l.id)) && !pageSelected;
  const pageCount = Math.max(1, Math.ceil(total / query.pageSize));

  return (
    <div>
      <div className="space-y-4">
        {/* Toolbar: accounts, quick filters, voided view, date filter, and actions */}
        <div className="flex flex-wrap items-center gap-2">
          <AccountFilter
            accounts={accounts}
            selected={query.accounts}
            onChange={(next) => onQueryChange({ accounts: next })}
          />

          <Dropdown
            open={quickFiltersOpen}
            onOpenChange={setQuickFiltersOpen}
            trigger={({ toggle, open }) => (
              <button
                type="button"
                className={`btn btn-sm ${activeQuickFilterCount > 0 ? 'btn-primary' : 'btn-outline'}`}
                disabled={voided}
                aria-haspopup="menu"
                aria-expanded={open}
                onClick={toggle}
                data-testid="quick-filters-btn"
              >
                {gettext('Quick Filters')}
                {activeQuickFilterCount > 0 && <span className="badge badge-sm">{activeQuickFilterCount}</span>}
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
                  count={counts?.to_review ?? 0}
                  countClass="badge-warning badge-outline"
                  onClick={() => toggleQuickFilter('toReview')}
                />
                <MenuRow
                  testId="filter-reconciled"
                  checked={quickFilters.reconciled}
                  label={gettext('Reconciled')}
                  count={counts?.reconciled ?? 0}
                  countClass="badge-success badge-outline"
                  onClick={() => toggleQuickFilter('reconciled')}
                />
                <MenuRow
                  testId="filter-uncategorized"
                  checked={quickFilters.uncategorized}
                  label={gettext('Uncategorized')}
                  count={counts?.uncategorized ?? 0}
                  countClass="badge-outline"
                  onClick={() => toggleQuickFilter('uncategorized')}
                />
                <MenuRow
                  testId="filter-transfers"
                  checked={quickFilters.transfers}
                  label={gettext('Possible transfers')}
                  count={transferCount}
                  countClass="badge-warning badge-outline"
                  onClick={() => toggleQuickFilter('transfers')}
                />
                {activeQuickFilterCount > 0 && (
                  <>
                    <div className="my-1 border-t border-base-300" />
                    <MenuRow
                      label={gettext('Clear filters')}
                      onClick={() => {
                        setQuickFilters({ toReview: false, reconciled: false, uncategorized: false, transfers: false });
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
            className={`btn btn-sm ${voided ? 'btn-neutral' : 'btn-outline'}`}
            onClick={() => onQueryChange({ view: voided ? 'active' : 'voided' })}
            aria-pressed={voided}
            data-testid="filter-voided"
          >
            {gettext('Voided')}
            <span className="badge badge-sm badge-ghost">{counts?.voided ?? 0}</span>
          </button>

          <div className="mx-1 h-6 w-px bg-base-300" />

          <DateRangePicker
            startDate={query.startDate}
            endDate={query.endDate}
            onApply={(s, e) => onQueryChange({ startDate: s || '', endDate: e || '' })}
          />
          <span className="whitespace-nowrap text-sm text-base-content/70" data-testid="feed-total">
            {total} {gettext('lines')}
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
          {/* Select-all strip: the checkbox takes this page; selecting everything
              the filters match is offered once the page is full. */}
          <div className="flex flex-wrap items-center gap-2 border-b border-base-300 px-3 py-2">
            <input
              type="checkbox"
              className="checkbox checkbox-sm rounded-sm"
              checked={pageSelected}
              ref={(el) => {
                if (el) el.indeterminate = somePageSelected;
              }}
              onChange={(e) => onToggleRows?.(lines, e.target.checked)}
              aria-label={gettext('Select all on this page')}
              data-testid="select-all"
            />
            {selectedIds.size > 0 && (
              <span className="text-sm text-primary" data-testid="selected-count">
                {selectedIds.size} {gettext('selected')}
              </span>
            )}
            {selectAllMatching?.offer && (
              <button
                type="button"
                className="btn btn-link btn-xs"
                onClick={selectAllMatching.onSelect}
                disabled={selectAllMatching.busy}
                data-testid="select-all-matching"
              >
                {selectAllMatching.busy
                  ? gettext('Selecting…')
                  : interpolate(gettext('Select all %s matching'), [total])}
              </button>
            )}
            {selectAllMatching?.tooMany && (
              <span className="text-xs text-base-content/70" data-testid="select-all-too-many">
                {gettext('Narrow the filters to select more than 1,000 transactions.')}
              </span>
            )}
            {refetching && (
              <span
                className="loading loading-spinner loading-xs ml-auto text-base-content/50"
                role="status"
                aria-label={gettext('Loading')}
                data-testid="feed-refetching"
              />
            )}
          </div>

          <div className="overflow-x-auto" ref={scrollRef}>
            {/* The fixed columns add up to ~45rem (~54 with Account); the floor keeps
                ~10rem for Description (and its "Match found" chip) on a narrow screen,
                where the table scrolls sideways instead of squeezing that column. */}
            <table
              className={`table table-sm table-quiet table-fixed w-full ${
                showAccountColumn ? 'min-w-[65rem]' : 'min-w-[56rem]'
              } ${refetching ? 'opacity-60' : ''}`}
              data-testid="feed-table"
            >
              <thead>
                <tr>
                  {columns.map((col) => (
                    <th key={col.key} className={`truncate ${col.width || ''} ${col.align || ''}`}>
                      {col.sortable ? (
                        <button
                          type="button"
                          className="group inline-flex items-center gap-1 hover:text-base-content"
                          onClick={() => toggleSort(col.key)}
                          data-testid={`sort-${col.key}`}
                        >
                          {col.label}
                          <SortArrow active={query.sort.key === col.key} direction={query.sort.dir} />
                        </button>
                      ) : (
                        col.label
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody ref={tableBodyRef}>
                {lines.map((row) => {
                  // Uncategorized rows are muted outside the voided view.
                  const muted = !voided && !isCategorized(row);
                  const reconciled = row.isReconciled ?? row.is_reconciled ?? false;
                  // A row categorized to another feed account is a transfer: the
                  // same journal entry also has a row in that account's feed.
                  const isTransfer = !!row.category && feedAccountIds.has(row.category.id) && !!row.journalEntryId;
                  // A possible duplicate transfer: the voided view never has one
                  // (void rows aren't candidates), so no chip there.
                  const match = voided ? null : matchFor(matchByTxId, row);
                  const matchOpen = !!match && openMatchId === row.id;
                  const panelId = `transfer-match-panel-${row.id}`;
                  const saving = pendingIds.has(row.id);
                  const account = accountsById.get(row.account?.id) ?? row.account;
                  return (
                    <Fragment key={row.id}>
                      <tr
                        className={`cursor-pointer ${muted ? 'text-base-content/50' : ''} ${
                          row.id === highlightId ? 'feed-row-flash' : ''
                        }`}
                        onClick={() => handleEditClick(row)}
                        aria-busy={saving || undefined}
                        data-testid={`feed-row-${row.id}`}
                      >
                        <td className="w-12" onClick={(e) => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            className="checkbox checkbox-sm rounded-sm"
                            checked={selectedIds.has(row.id)}
                            onChange={(e) => handleRowSelect(row, e.target.checked, e.nativeEvent.shiftKey)}
                            aria-label={gettext('Select row')}
                          />
                        </td>
                        <td className="whitespace-nowrap">{formatDate(row.postedDate)}</td>
                        {showAccountColumn && (
                          <td
                            className="truncate"
                            title={[account?.name, account?.institution?.name ?? account?.institution_name]
                              .filter(Boolean)
                              .join(' · ')}
                            data-testid={`feed-row-account-${row.id}`}
                          >
                            {account?.name ?? ''}
                          </td>
                        )}
                        <td className="truncate" title={row.payee || ''}>
                          {row.payee || ''}
                        </td>
                        <td className="truncate" title={categoryTitle(row)}>
                          <span className="inline-flex w-full items-center gap-1">
                            {row.isSplit ? (
                              <span className="badge badge-ghost badge-sm shrink-0" data-testid={`split-badge-${row.id}`}>
                                {interpolate(gettext('Split (%s)'), [row.splitCount])}
                              </span>
                            ) : (
                              <span className="truncate">
                                {row.category ? gettext(row.category.name) : gettext('Uncategorized')}
                              </span>
                            )}
                            {isTransfer && (
                              <button
                                type="button"
                                className="btn btn-ghost btn-xs shrink-0 px-1 text-primary"
                                title={`${gettext('Go to the other side of this transfer in')} ${row.category.name}`}
                                aria-label={`${gettext('Go to the other side of this transfer in')} ${row.category.name}`}
                                data-testid={`transfer-link-${row.id}`}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  if (onOpenTransferLeg) onOpenTransferLeg(row);
                                }}
                              >
                                <Icon name="arrow-right-left" className="h-3.5 w-3.5" />
                              </button>
                            )}
                          </span>
                        </td>
                        <td className="money whitespace-nowrap text-right">
                          {row.inflow && parseFloat(row.inflow) > 0 ? formatCurrency(row.inflow) : ''}
                        </td>
                        <td className="money whitespace-nowrap text-right">
                          {row.outflow && parseFloat(row.outflow) > 0 ? formatCurrency(row.outflow) : ''}
                        </td>
                        <td title={row.description || ''}>
                          <span className="flex min-w-0 items-center gap-1">
                            {match && (
                              <button
                                type="button"
                                className={`badge badge-sm shrink-0 gap-1 cursor-pointer ${
                                  matchOpen ? 'badge-warning' : 'badge-warning badge-soft'
                                }`}
                                title={interpolate(gettext('Possible transfer with %s — review'), [
                                  match.other.account?.name ?? '',
                                ])}
                                aria-label={interpolate(gettext('Possible transfer with %s'), [
                                  match.other.account?.name ?? '',
                                ])}
                                aria-expanded={matchOpen}
                                aria-controls={matchOpen ? panelId : undefined}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setOpenMatchId(matchOpen ? null : row.id);
                                }}
                                data-testid={`transfer-match-chip-${row.id}`}
                              >
                                <Icon name="arrow-right-left" className="h-3 w-3" />
                                {gettext('Match found')}
                              </button>
                            )}
                            {/* A split has no per-leg memo, so the marker beside the
                                description is what identifies one without opening it. */}
                            {row.isSplit && (
                              <span className="badge badge-ghost badge-sm shrink-0">{gettext('Split')}</span>
                            )}
                            <span className="truncate">{row.description || ''}</span>
                          </span>
                        </td>
                        <td className="text-center">
                          {saving ? (
                            <span
                              className="loading loading-spinner loading-xs text-base-content/50"
                              title={gettext('Saving…')}
                              data-testid={`row-saving-${row.id}`}
                            />
                          ) : (
                            <ReconciledLock reconciled={reconciled} />
                          )}
                        </td>
                      </tr>
                      {matchOpen && (
                        <tr className="cursor-default">
                          <td colSpan={columns.length} className="bg-base-100 p-2">
                            <div
                              className="sticky left-0"
                              style={scrollWidth ? { width: `${scrollWidth - 16}px` } : undefined}
                            >
                              <TransferMatchPanel
                                id={panelId}
                                match={match}
                                onMatch={onMatch}
                                onDismiss={onDismissMatch}
                                onGoTo={onOpenMatchCounterpart}
                                onClose={() => {
                                  setOpenMatchId(null);
                                  tableBodyRef.current
                                    ?.querySelector(`[data-testid="transfer-match-chip-${row.id}"]`)
                                    ?.focus();
                                }}
                              />
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
                {lines.length === 0 && !refetching && (
                  <tr>
                    <td colSpan={columns.length} className="py-8 text-center text-base-content/70">
                      {gettext('No transactions to show')}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <TablePager
            page={query.page}
            pageCount={pageCount}
            pageSize={query.pageSize}
            pageSizeOptions={PAGE_SIZE_OPTIONS}
            total={total}
            onPageChange={(page) => onQueryChange({ page })}
            onPageSizeChange={(pageSize) => onQueryChange({ pageSize })}
          />
        </div>
      </div>

      <EditTransactionModal
        open={editModalOpen}
        onClose={handleEditModalClose}
        transaction={editingTransaction}
        allAccounts={allAccounts}
        allPayees={allPayees}
        categorySuggestions={categorySuggestions}
        book={book}
        onSave={handleEditSave}
        mode={modalMode}
        feedAccounts={accounts}
        defaultAccountId={defaultAccountId}
      />

      <Toast
        testId="feed-toast"
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
