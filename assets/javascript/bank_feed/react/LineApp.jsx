/* globals gettext, interpolate */

import React, { useEffect, useState, useMemo, useCallback, useRef } from 'react';
import { Toast } from '../../common/Toast';

import AccountGrid from './AccountGrid';
import LineTable from './LineTable';
import PlaidLinkButton from './PlaidLinkButton';
import { CSVUploadWizard } from './CSVUploadWizard';
import BatchActionBar from './BatchActionBar';
import { getBatchOperationsApi, getTransactionApi } from '../bank_feed';
import { formatCurrency } from '../../utilities/currency';
import Icon from '../../common/Icon';
import { BankFeedRowFromJSON } from 'api-client';

/** How long the feed waits after its last write settles before re-reading it. */
const QUIET_REFRESH_DELAY_MS = 500;

/**
 * A date as the generated client parses one: `YYYY-MM-DD` at UTC midnight, which
 * is what `formatDateForInput` reads back as the same calendar day.
 */
const asRowDate = (value) => {
  if (!value) return value;
  return value instanceof Date ? value : new Date(String(value).slice(0, 10));
};

/**
 * The row as it will look once the edit lands, built from what the modal sent.
 *
 * Only what the table shows has to be right: the server's own row replaces this
 * one as soon as the save returns, and a quiet re-read follows that.
 */
const optimisticEditedRow = (row, data, accountsById) => {
  const legs = Array.isArray(data.splits) && data.splits.length > 0 ? data.splits : null;
  let category = null;
  if (!legs && data.category) {
    const id = data.category.id ?? data.category;
    category =
      row.category?.id === id
        ? row.category
        : { id, name: data.category.name ?? accountsById.get(id)?.name ?? '' };
  }
  return {
    ...row,
    postedDate: asRowDate(data.date) ?? row.postedDate,
    payee: data.payee ?? '',
    description: data.description ?? '',
    inflow: data.inflow || '0.00',
    outflow: data.outflow || '0.00',
    category,
    isSplit: Boolean(legs),
    splitCount: legs ? legs.length : 0,
    splits: legs
      ? legs.map((leg) => ({
          categoryId: leg.category,
          categoryName: accountsById.get(leg.category)?.name ?? '',
          amount: leg.amount,
        }))
      : [],
  };
};

/** Fields a bulk edit changes on a row that stays in this account's feed. */
const optimisticBulkEditedRow = (row, updates, accountsById) => {
  const next = { ...row };
  if (updates.payee) next.payee = updates.payee;
  if (updates.description) next.description = updates.description;
  if (updates.date) next.postedDate = asRowDate(updates.date);
  if (updates.category_id) {
    next.category = { id: updates.category_id, name: accountsById.get(updates.category_id)?.name ?? '' };
  }
  return next;
};

/**
 * LineApp - Main application component for managing lines
 * Manages account selection and bank feed operations
 */
const LineApp = ({ accounts: initialAccounts, allAccounts, allPayees, allAccountGroups, book, bankFeedClient, plaidClient, journalClient, uploadApi }) => {
  // Store accounts in state so we can update reconciled_balance after reconciliation
  const [accounts, setAccounts] = useState(initialAccounts);
  const [selectedAccount, setSelectedAccount] = useState(null);
  const [lines, setLines] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [showUploadWizard, setShowUploadWizard] = useState(false);

  // Account picker is expanded until an account is chosen, then it collapses
  // to a compact strip so the account list doesn't crowd the categorizing view
  const [isAccountPickerOpen, setIsAccountPickerOpen] = useState(true);

  // Batch selection state
  const [selectedIds, setSelectedIds] = useState(new Set());

  // Plaid sync status: ledger account id -> PlaidItem (for "last synced" display)
  const [plaidItemsByAccountId, setPlaidItemsByAccountId] = useState({});

  // Category suggestions: merchant/payee name -> {id, name} of last-used category
  const [categorySuggestions, setCategorySuggestions] = useState({});

  // View mode state (synced from LineTable): 'active' | 'archived'
  const [viewMode, setViewMode] = useState('active');

  // A row the table should page to and flash, set when jumping to the other leg
  // of a transfer: {journalEntryId | importedTransactionId, nonce, keepFilters?}
  const [focusRequest, setFocusRequest] = useState(null);

  // Possible duplicate transfers across the whole book (a pair has a leg in two
  // accounts, and the account cards count both), each with the server's
  // proposal for which leg Match keeps.
  const [matches, setMatches] = useState([]);

  // Rows with a write still on its way to the server, which the table marks as
  // saving. Counted, because the same row can carry more than one write.
  const pendingCountsRef = useRef(new Map());
  const [pendingIds, setPendingIds] = useState(() => new Set());
  // Writes in flight, and a counter bumped as each one starts: a background
  // re-read is only applied if nothing was written after it was requested,
  // or a slow read would undo an edit the user just made.
  const inFlightRef = useRef(0);
  const writeEpochRef = useRef(0);
  // Each row's last queued write, so two quick edits to one row reach the
  // server in the order they were made.
  const rowQueueRef = useRef(new Map());
  const quietRefreshTimerRef = useRef(null);
  const quietLoadSeqRef = useRef(0);

  const accountsById = useMemo(() => new Map((allAccounts || []).map((a) => [a.id, a])), [allAccounts]);

  // Snackbar state for batch operations
  const [snackbar, setSnackbar] = useState({
    open: false,
    message: '',
    severity: 'info',
  });

  // Accounts that have a feed of their own. A row categorized to one of these is
  // a transfer, and the only kind of row with another feed to link across to.
  const feedAccountIds = useMemo(() => new Set(accounts.map((a) => a.id)), [accounts]);

  // Batch operations API
  const batchApi = useMemo(() => getBatchOperationsApi(book.base), [book]);

  const loadMatches = useCallback(async () => {
    try {
      const data = await batchApi.transferSuggestions();
      setMatches(Array.isArray(data) ? data : []);
    } catch (err) {
      // A failed load shouldn't break the feed; the rows just show no chips.
      console.error('Failed to load possible transfers:', err);
    }
  }, [batchApi]);

  useEffect(() => {
    loadMatches();
  }, [loadMatches]);

  // Bank transaction id -> {pair, self, other}, for the row chips
  const matchByTxId = useMemo(() => {
    const map = new Map();
    matches.forEach((pair) => {
      map.set(pair.outflow.imported_transaction_id, { pair, self: pair.outflow, other: pair.inflow });
      map.set(pair.inflow.imported_transaction_id, { pair, self: pair.inflow, other: pair.outflow });
    });
    return map;
  }, [matches]);

  // Account id -> number of possible transfers with a leg there, for the cards
  const matchCountByAccount = useMemo(() => {
    const counts = new Map();
    matches.forEach((pair) => {
      [pair.outflow, pair.inflow].forEach((leg) => {
        const id = leg.account?.id;
        if (id != null) counts.set(id, (counts.get(id) || 0) + 1);
      });
    });
    return counts;
  }, [matches]);

  // Transaction API (create/update)
  const transactionApi = useMemo(() => getTransactionApi(book.base), [book]);

  // Show snackbar helper
  const showSnackbar = useCallback((message, severity = 'info') => {
    setSnackbar({ open: true, message, severity });
  }, []);

  // Close snackbar
  const handleCloseSnackbar = () => {
    setSnackbar({ ...snackbar, open: false });
  };

  const loadAccounts = useCallback(async () => {
    try {
      const updatedAccounts = await batchApi.fetchFeedAccounts();
      setAccounts(updatedAccounts);
      const current = selectedAccountRef.current;
      if (current) {
        const updated = updatedAccounts.find(a => a.id === current.id);
        if (updated) setSelectedAccount(updated);
      }
    } catch (err) {
      console.error('Failed to refresh account balances:', err);
    }
  }, [batchApi]);

  // Monotonic id so a slow response for a previously selected account can't
  // overwrite the rows of the currently selected one
  const loadRequestRef = useRef(0);
  const selectedAccountRef = useRef(null);
  selectedAccountRef.current = selectedAccount;

  // Load Plaid sync status (which item feeds each account, and when it last synced)
  const loadPlaidStatus = useCallback(async () => {
    try {
      const [accountsData, itemsData] = await Promise.all([
        plaidClient.plaidAccountsList({ ...book.params }),
        plaidClient.plaidItemsList({ ...book.params }),
      ]);
      const itemsById = {};
      (itemsData.results || []).forEach((item) => {
        itemsById[item.id] = item;
      });
      const map = {};
      (accountsData.results || []).forEach((pa) => {
        if (pa.account != null && itemsById[pa.item]) {
          map[pa.account] = itemsById[pa.item];
        }
      });
      setPlaidItemsByAccountId(map);
    } catch (err) {
      console.error('Failed to load Plaid sync status:', err);
    }
  }, [plaidClient, book]);

  useEffect(() => {
    loadPlaidStatus();
  }, [loadPlaidStatus]);

  // Load category suggestions (most recent category per merchant)
  useEffect(() => {
    bankFeedClient
      .bankFeedCategorySuggestions({ ...book.params })
      .then((rows) => {
        const map = {};
        (rows || []).forEach((s) => {
          map[s.merchantName] = { id: s.categoryId, name: s.categoryName };
        });
        setCategorySuggestions(map);
      })
      .catch((err) => console.error('Failed to load category suggestions:', err));
  }, [bankFeedClient, book]);

  // Load lines when an account is selected. Keyed on the id: refreshing the
  // balances hands back a new object for the same account, which must not
  // reload (and hide) the whole feed.
  useEffect(() => {
    if (selectedAccount) {
      loadLines(selectedAccount);
    } else {
      setLines([]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedAccount?.id]);

  // Every row of an account's feed, following pagination if the server returns
  // more than one page
  const fetchAllLines = async (account) => {
    const results = [];
    let data = await bankFeedClient.bankFeedFeedList({
      ...book.params,
      account: account.id,
    });
    results.push(...(data.results || []));
    while (data.next) {
      const nextPage = Number(new URL(data.next, window.location.origin).searchParams.get('page'));
      if (!nextPage) break;
      data = await bankFeedClient.bankFeedFeedList({
        ...book.params,
        account: account.id,
        page: nextPage,
      });
      results.push(...(data.results || []));
    }
    return results;
  };

  /**
   * Load an account's feed with the table hidden behind a spinner. Only for
   * opening an account, where there is nothing on screen to keep.
   */
  const loadLines = async (account = selectedAccountRef.current) => {
    if (!account) return;
    const requestId = ++loadRequestRef.current;
    setLoading(true);
    setError(null);
    try {
      const results = await fetchAllLines(account);
      if (loadRequestRef.current === requestId) {
        setLines(results);
      }
    } catch (err) {
      console.error('Failed to load lines:', err);
      if (loadRequestRef.current === requestId) {
        setError(err.message || gettext('Failed to load lines'));
      }
    } finally {
      if (loadRequestRef.current === requestId) {
        setLoading(false);
      }
    }
  };

  /**
   * Re-read the open feed without hiding it, after writes have settled.
   *
   * A write changes more than the rows it names -- the other leg of a transfer,
   * a split's mirror rows -- so the feed is re-read once things go quiet, but in
   * the background: the table stays up and usable, and the result is dropped if
   * the user has written anything since it was requested, or switched account.
   */
  const refreshLinesQuietly = async () => {
    const account = selectedAccountRef.current;
    if (!account) return;
    const loadId = loadRequestRef.current;
    const epoch = writeEpochRef.current;
    const seq = ++quietLoadSeqRef.current;
    try {
      const results = await fetchAllLines(account);
      const stillCurrent =
        seq === quietLoadSeqRef.current &&
        loadId === loadRequestRef.current &&
        epoch === writeEpochRef.current &&
        inFlightRef.current === 0 &&
        selectedAccountRef.current?.id === account.id;
      if (stillCurrent) setLines(results);
    } catch (err) {
      console.error('Failed to refresh lines:', err);
    }
  };

  /**
   * Re-read the feed, the account balances and the possible transfers once no
   * write is in flight -- categorizing, editing, archiving or importing can each
   * create or dissolve a pair.
   */
  const scheduleQuietRefresh = () => {
    clearTimeout(quietRefreshTimerRef.current);
    quietRefreshTimerRef.current = setTimeout(() => {
      if (inFlightRef.current > 0) return;
      loadAccounts();
      loadMatches();
      refreshLinesQuietly();
    }, QUIET_REFRESH_DELAY_MS);
  };

  useEffect(() => () => clearTimeout(quietRefreshTimerRef.current), []);

  const markPending = (ids, delta) => {
    const counts = pendingCountsRef.current;
    ids.forEach((id) => {
      const next = (counts.get(id) || 0) + delta;
      if (next > 0) counts.set(id, next);
      else counts.delete(id);
    });
    setPendingIds(new Set(counts.keys()));
  };

  /**
   * Apply a write to the table now and send it to the server in the background.
   *
   * `apply(row)` returns the row as it will look once the write lands, or null
   * when the row leaves this feed. The table shows that at once; the rows stay
   * marked as saving until the server answers. On success `onSuccess` may hand
   * back the server's own rows; on failure every row this write changed -- and
   * nothing has changed since -- goes back to how it was, and the server's
   * reason is shown. Either way the feed is quietly re-read once writes settle.
   *
   * Resolves once the write has settled; nothing has to wait for it.
   */
  const runWrite = ({ rowIds = [], apply = null, request, onSuccess = null, successMessage = null, errorMessage }) => {
    writeEpochRef.current += 1;
    inFlightRef.current += 1;
    const ids = new Set(rowIds);

    // The rows this write replaced, and what it replaced them with, so a
    // rollback only touches rows still showing this write's version.
    const before = new Map();
    const written = new Map();
    if (apply && ids.size > 0) {
      // Computed against the latest rows (an earlier write may not have
      // rendered yet), and once per row, so a re-run updater keeps identities.
      setLines((prev) =>
        prev.flatMap((row) => {
          if (!ids.has(row.id)) return [row];
          if (!written.has(row.id)) {
            before.set(row.id, row);
            written.set(row.id, apply(row));
          }
          const next = written.get(row.id);
          return next ? [next] : [];
        })
      );
    }
    markPending([...ids], 1);

    // Queue behind earlier writes to the same rows
    const queue = rowQueueRef.current;
    const ahead = Promise.all([...ids].map((id) => queue.get(id))).catch(() => {});
    const sent = ahead.then(() => request());
    const settled = sent.catch(() => {});
    ids.forEach((id) => queue.set(id, settled));

    return sent
      .then((result) => {
        const fresh = onSuccess ? onSuccess(result) : null;
        if (fresh && fresh.length) {
          const byId = new Map(fresh.map((row) => [row.id, row]));
          setLines((prev) =>
            prev.map((row) => {
              const server = byId.get(row.id);
              // A later write to this row is already on screen; its own
              // answer will bring the server's row.
              if (!server || (written.has(row.id) && written.get(row.id) !== row)) return row;
              return server;
            })
          );
        }
        if (successMessage) showSnackbar(successMessage, 'success');
      })
      .catch((err) => {
        console.error(errorMessage, err);
        setLines((prev) => {
          const present = new Set(prev.map((row) => row.id));
          const restored = prev.map((row) =>
            written.has(row.id) && written.get(row.id) === row ? before.get(row.id) : row
          );
          // Rows this write removed from the feed come back
          before.forEach((row, id) => {
            if (written.get(id) === null && !present.has(id)) restored.push(row);
          });
          return restored;
        });
        showSnackbar(err.message || errorMessage, 'error');
      })
      .finally(() => {
        inFlightRef.current -= 1;
        markPending([...ids], -1);
        ids.forEach((id) => {
          if (queue.get(id) === settled) queue.delete(id);
        });
        scheduleQuietRefresh();
      });
  };

  /**
   * Jump to the other leg of a transfer: the row for the same journal entry in
   * the category account's feed.
   *
   * The two legs share one journal entry, so the counterpart needs no extra data
   * from the server — switch to the category account and let the table find the
   * row carrying this entry id once its lines have loaded.
   */
  const handleOpenTransferLeg = useCallback(
    (row) => {
      // The category must be a feed account — that is what makes this a transfer
      // rather than a spending category, and what gives it a feed to open.
      const target = accounts.find((a) => a.id === row.category?.id);
      if (!target || !row.journalEntryId) return;
      setFocusRequest({ journalEntryId: row.journalEntryId, nonce: `${row.id}-${Date.now()}` });
      if (selectedAccountRef.current?.id === target.id) return;
      // Selection refers to rows of the account we are leaving
      setSelectedIds(new Set());
      setSelectedAccount(target);
      setIsAccountPickerOpen(false);
    },
    [accounts]
  );

  /**
   * Match a possible duplicate transfer: the server keeps one leg, archives the
   * other, and makes the kept one the transfer between both accounts.
   *
   * Goes through `runWrite` like every other feed write: this account's leg
   * shows the outcome at once (archived, or categorized as the transfer) and
   * comes back if the server refuses. The leg the server archives must be the
   * one the panel showed, or it answers 409 with the current proposal, which
   * replaces the stale one so the panel redraws with the new outcome.
   */
  const handleMatch = ({ pair, self, other }) => {
    const proposal = pair.proposal || {};
    const row = lines.find((l) => (l.importedTransactionId ?? l.imported_transaction_id) === self.imported_transaction_id);
    const archivesThis = proposal.archive_id === self.imported_transaction_id;
    return runWrite({
      rowIds: row ? [row.id] : [],
      apply: (r) =>
        archivesThis
          ? { ...r, isArchived: true }
          : { ...r, category: { id: other.account?.id, name: other.account?.name ?? '' }, isSplit: false },
      request: async () => {
        try {
          return await batchApi.transferMatch(
            self.imported_transaction_id,
            other.imported_transaction_id,
            proposal.archive_id
          );
        } catch (err) {
          if (err.status === 409 && err.data?.proposal) {
            const fresh = err.data.proposal;
            setMatches((prev) => prev.map((p) => (p === pair ? { ...p, proposal: fresh } : p)));
          }
          throw err;
        }
      },
      onSuccess: (result) => {
        const kept = result.kept_id === self.imported_transaction_id ? self : other;
        const archived = kept === self ? other : self;
        setMatches((prev) => prev.filter((p) => p !== pair));
        // In this account the transfer is now either the kept row or its mirror;
        // both carry the kept entry, so flash whichever is here once the quiet
        // re-read brings it in.
        setFocusRequest({
          journalEntryId: result.kept_journal_entry_id,
          nonce: `match-${result.kept_id}-${Date.now()}`,
          keepFilters: true,
        });
        showSnackbar(
          interpolate(gettext('Matched — kept the one in %s, archived the one in %s.'), [
            kept.account?.name ?? '',
            archived.account?.name ?? '',
          ]),
          'success'
        );
        return null;
      },
      errorMessage: gettext('Could not match these transactions.'),
    });
  };

  /** Not the same transfer: stop suggesting the pair, in both feeds. */
  const handleDismissMatch = async ({ self, other }) => {
    try {
      await batchApi.transferDismiss(self.imported_transaction_id, other.imported_transaction_id);
      setMatches((prev) =>
        prev.filter(
          (p) =>
            p.outflow.imported_transaction_id !== self.imported_transaction_id &&
            p.inflow.imported_transaction_id !== self.imported_transaction_id
        )
      );
      showSnackbar(gettext('Marked as not a match.'), 'info');
    } catch (err) {
      showSnackbar(err.message || gettext('Could not dismiss this suggestion.'), 'error');
    }
  };

  /** Open the other leg of a possible transfer in its own account's feed. */
  const handleOpenMatchCounterpart = useCallback(
    ({ other }) => {
      const target = accounts.find((a) => a.id === other.account?.id);
      if (!target) return;
      setFocusRequest({
        importedTransactionId: other.imported_transaction_id,
        nonce: `goto-${other.imported_transaction_id}-${Date.now()}`,
      });
      if (selectedAccountRef.current?.id === target.id) return;
      setSelectedIds(new Set());
      setSelectedAccount(target);
      setIsAccountPickerOpen(false);
    },
    [accounts]
  );

  const handleAccountSelect = (account) => {
    // Selection refers to rows of the previous account; don't let the batch
    // bar keep acting on rows that are no longer visible
    setSelectedIds(new Set());
    setSelectedAccount(account);
    setIsAccountPickerOpen(false);
  };

  // The Inbox nav submenu links straight to an account via ?account=<id>, so a
  // click there opens the feed with that account already selected instead of
  // landing back on the picker. Only applied once, on the first load of the
  // accounts list.
  const appliedAccountParamRef = useRef(false);
  useEffect(() => {
    if (appliedAccountParamRef.current || accounts.length === 0) return;
    const requestedId = Number(new URLSearchParams(window.location.search).get('account'));
    if (!requestedId) return;
    appliedAccountParamRef.current = true;
    const target = accounts.find((a) => a.id === requestedId);
    if (target) handleAccountSelect(target);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accounts]);

  /**
   * Refresh bank feed data from Plaid
   */
  const handleRefresh = async () => {
    if (!selectedAccount) return;

    setRefreshing(true);
    setError(null);

    try {
      // First, get all Plaid accounts and find one mapped to this ledger account
      const plaidAccountsData = await plaidClient.plaidAccountsList({
        ...book.params,
      });

      // Find Plaid account mapped to the selected ledger account
      const plaidAccount = plaidAccountsData.results?.find(
        (pa) => pa.account === selectedAccount.id
      );

      if (plaidAccount) {
        // Trigger sync task for this Plaid item
        await plaidClient.plaidItemsSync({
          ...book.params,
          id: plaidAccount.item,
        });

        // The sync runs in a background task with no completion signal, so
        // reload a few times while it (probably) finishes instead of assuming
        // it's done after a fixed 2s.
        const accountId = selectedAccount.id;
        for (const delay of [2000, 4000, 6000]) {
          await new Promise((resolve) => setTimeout(resolve, delay));
          if (selectedAccountRef.current?.id !== accountId) break;
          await loadLines();
        }
        await Promise.all([loadPlaidStatus(), loadMatches()]);
        setRefreshing(false);
      } else {
        // No Plaid account linked to this ledger account
        setError(gettext('This account is not linked to a bank feed.'));
        setRefreshing(false);
      }
    } catch (err) {
      console.error('Failed to refresh:', err);
      setError(gettext('Failed to refresh bank feed. Please try again.'));
      setRefreshing(false);
    }
  };

  /**
   * Handle successful Plaid Link - reload page to show new accounts
   */
  const handlePlaidSuccess = () => {
    window.location.reload();
  };

  /**
   * Categorize bank feed rows (for Plaid transactions)
   */
  const handleCategorize = async (rows, categoryAccountId) => {
    try {
      await bankFeedClient.bankFeedTransactionsCategorize({
        ...book.params,
        categorizeTransactionsRequest: {
          rows: rows,
          categoryId: categoryAccountId,
        },
      });

      // Re-read the bank feed and account balances in the background
      scheduleQuietRefresh();
    } catch (err) {
      console.error('Failed to categorize:', err);
      throw err;
    }
  };

  /**
   * Handle editing ledger transactions (redirect to journal entry edit)
   */
  const handleEditLedgerTransaction = (row) => {
    if (row.source === 'ledger' && row.journal_line_id) {
      // For now, we'll just reload the data
      // In the future, this could open an edit modal or redirect to journal entry edit
      console.log('Edit ledger transaction:', row);
      // TODO: Implement ledger transaction editing
    }
  };

  /**
   * Handle adding a new line (manual transaction)
   */
  const handleAddLine = async (lineData) => {
    try {
      // Use the new transaction API which creates BankTransaction + JournalEntry.
      // The modal waits for this one request -- a new row has no id to edit
      // until the server gives it one -- but not for the feed to be re-read.
      const created = await transactionApi.createTransaction({
        date: lineData.date,
        category: lineData.category,
        splits: lineData.splits ?? null,
        inflow: lineData.inflow || '0',
        outflow: lineData.outflow || '0',
        payee: lineData.payee || '',
        description: lineData.description || '',
        account: selectedAccount.id,
      });

      if (created) {
        const row = BankFeedRowFromJSON(created);
        setLines((prev) => (prev.some((l) => l.id === row.id) ? prev : [row, ...prev]));
      }
      writeEpochRef.current += 1;
      scheduleQuietRefresh();
    } catch (err) {
      console.error('Failed to add line:', err);
      throw err;
    }
  };

  /**
   * Handle editing a transaction from the edit modal.
   *
   * The row shows the edit straight away and the modal closes without waiting;
   * the update goes to the server in the background. A refused edit puts the row
   * back and says why.
   */
  const handleEditTransaction = (updatedData) => {
    const { id, date, category, splits, remove_split, inflow, outflow, payee, description } = updatedData;
    const accountId = selectedAccount.id;
    return runWrite({
      rowIds: [id],
      apply: (row) => optimisticEditedRow(row, updatedData, accountsById),
      request: () =>
        transactionApi.updateTransaction(id, {
          date: date,
          category: category,
          splits: splits ?? null,
          remove_split: remove_split ?? false,
          inflow: inflow || '0',
          outflow: outflow || '0',
          payee: payee || '',
          description: description || '',
          account: accountId,
        }),
      onSuccess: (json) => (json ? [BankFeedRowFromJSON(json)] : null),
      errorMessage: gettext('Failed to update transaction'),
    });
  };

  /**
   * Handle deleting a line
   */
  const handleDeleteLine = async (lineId) => {
    try {
      // Parse the composite ID
      const [source, id] = lineId.split('-');

      if (source === 'manual' || source === 'csv') {
        // Delete manual transaction - would need to find and delete the journal entry
        throw new Error('Deleting manual transactions not yet implemented');
      } else if (source === 'plaid') {
        // Cannot delete Plaid transactions
        throw new Error('Cannot delete Plaid transactions');
      } else if (source === 'ledger') {
        // Delete ledger transaction - would need to delete the journal entry
        throw new Error('Deleting ledger transactions not yet implemented');
      }

      await loadLines();
    } catch (err) {
      console.error('Failed to delete line:', err);
      throw err;
    }
  };

  // Batch operation handlers

  /**
   * Bulk edit selected transactions via the unified batch_edit endpoint.
   * @param {Object} updates - Fields to update (category_id, account_id, payee, description, date)
   */
  const handleBulkEdit = (updates) => {
    const ids = [...selectedIds];
    const accountId = selectedAccountRef.current?.id;
    setSelectedIds(new Set());
    runWrite({
      rowIds: ids,
      // Moved to another account, the rows leave this feed
      apply: (row) =>
        updates.account_id && updates.account_id !== accountId
          ? null
          : optimisticBulkEditedRow(row, updates, accountsById),
      request: () => batchApi.batchEdit(ids, updates),
      successMessage: gettext('Transactions updated successfully'),
      errorMessage: gettext('Failed to update transactions'),
    });
  };

  /**
   * Batch archive selected transactions
   */
  const handleBatchArchive = () => {
    const ids = [...selectedIds];
    setSelectedIds(new Set());
    runWrite({
      rowIds: ids,
      apply: (row) => ({ ...row, isArchived: true }),
      request: () => batchApi.batchArchive(ids),
      successMessage: gettext('Transactions archived successfully'),
      errorMessage: gettext('Failed to archive transactions'),
    });
  };

  /**
   * Batch unarchive selected transactions
   */
  const handleBatchUnarchive = () => {
    const ids = [...selectedIds];
    setSelectedIds(new Set());
    runWrite({
      rowIds: ids,
      apply: (row) => ({ ...row, isArchived: false }),
      request: () => batchApi.batchUnarchive(ids),
      successMessage: gettext('Transactions unarchived successfully'),
      errorMessage: gettext('Failed to unarchive transactions'),
    });
  };

  /**
   * Permanently delete selected archived transactions
   */
  const handleBatchDelete = () => {
    const ids = [...selectedIds];
    setSelectedIds(new Set());
    runWrite({
      rowIds: ids,
      apply: () => null,
      request: () => batchApi.batchDelete(ids),
      successMessage: gettext('Transactions permanently deleted'),
      errorMessage: gettext('Failed to delete transactions'),
    });
  };

  /**
   * Batch duplicate selected transactions
   */
  const handleBatchDuplicate = () => {
    const ids = [...selectedIds];
    setSelectedIds(new Set());
    runWrite({
      rowIds: ids,
      // The copies have no ids until the server makes them; the re-read brings them in
      request: () => batchApi.batchDuplicate(ids),
      successMessage: gettext('Transactions duplicated successfully'),
      errorMessage: gettext('Failed to duplicate transactions'),
    });
  };

  /**
   * Reconcile the selection against a statement: hand it to the reconcile page,
   * which opens (or resumes) the account's draft with these rows already ticked.
   * A feed row knows its journal entry, not its line, so entries are passed.
   */
  const handleBatchReconcile = (rows) => {
    if (!selectedAccount) return;
    const entries = (rows || [])
      .map((r) => r.journal_entry_id ?? r.journalEntryId)
      .filter(Boolean);
    const query = entries.length ? `?entries=${entries.join(',')}` : '';
    window.location.href = `${book.base}reconcile/${selectedAccount.id}/${query}`;
  };

  /**
   * Batch unreconcile selected transactions
   */
  const handleBatchUnreconcile = () => {
    const ids = [...selectedIds];
    setSelectedIds(new Set());
    runWrite({
      rowIds: ids,
      apply: (row) => ({ ...row, isReconciled: false, reconciledStatementDate: undefined }),
      request: () => batchApi.batchUnreconcile(ids),
      successMessage: gettext('Transactions unreconciled successfully'),
      errorMessage: gettext('Failed to unreconcile transactions'),
    });
  };

  /**
   * Handle selection change from table
   */
  const handleSelectionChange = (newSelectedIds) => {
    setSelectedIds(newSelectedIds);
  };

  /**
   * Human-friendly "last synced" label for the selected account's Plaid item
   */
  const formatLastSynced = (lastSyncedAt) => {
    if (!lastSyncedAt) return gettext('Never synced');
    const seconds = Math.floor((Date.now() - new Date(lastSyncedAt).getTime()) / 1000);
    if (seconds < 60) return gettext('Synced just now');
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${gettext('Synced')} ${minutes} ${gettext('min ago')}`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${gettext('Synced')} ${hours} ${gettext('hr ago')}`;
    const days = Math.floor(hours / 24);
    return `${gettext('Synced')} ${days} ${gettext('d ago')}`;
  };

  const selectedPlaidItem = selectedAccount ? plaidItemsByAccountId[selectedAccount.id] : null;

  /**
   * Get selected rows data
   */
  const selectedRows = useMemo(() => {
    return lines.filter(l => selectedIds.has(l.id));
  }, [lines, selectedIds]);

  /**
   * Determine which archive/unarchive button to show based on selection
   */
  // Handle both camelCase (from generated API client) and snake_case (raw API)
  const isArchived = (r) => r.isArchived ?? r.is_archived ?? false;
  const isReconciled = (r) => r.isReconciled ?? r.is_reconciled ?? false;

  const showArchiveButton = useMemo(() => {
    // Show archive only if any selected row is not archived and not reconciled
    return selectedRows.some(r => !isArchived(r) && !isReconciled(r));
  }, [selectedRows]);

  const showUnarchiveButton = useMemo(() => {
    // Show unarchive if any selected row is archived
    return selectedRows.some(r => isArchived(r));
  }, [selectedRows]);

  return (
    <div className="space-y-6">
      {/* Account Selection Cards */}
      <section className="app-card">
        <div className="flex justify-between items-center mb-4">
          <button
            type="button"
            className="flex items-center gap-2 min-w-0"
            onClick={() => setIsAccountPickerOpen((open) => !open)}
            aria-expanded={isAccountPickerOpen}
            data-testid="account-picker-toggle"
          >
            <Icon name={isAccountPickerOpen ? 'chevron-down' : 'chevron-right'} className="inline-block w-3.5 h-3.5 shrink-0 text-base-content/70" />
            <h2 className="text-xl mb-1">{gettext('Select Account')}</h2>
            {!isAccountPickerOpen && selectedAccount && (
              <span className="text-sm font-normal text-base-content/70 truncate">
                — {selectedAccount.name}
              </span>
            )}
          </button>
          <div className="flex gap-2 items-center">
            <a
              href={`${book.base}bankfeed/categorize/`}
              className="btn btn-primary btn-sm gap-1"
              data-testid="categorize-mode-btn"
            >
              ⚡ {gettext('Categorize Mode')}
            </a>
          </div>
        </div>
        {isAccountPickerOpen && (
          accounts.length === 0 ? (
            <div className="alert alert-warning">
              <Icon name="exclamation-triangle" className="inline-block shrink-0 w-4 h-4" />
              <span>
                {gettext('No accounts with bank feeds found. Please link a bank account to get started.')}
              </span>
              <PlaidLinkButton
                book={book}
                allAccounts={allAccounts}
                onSuccess={handlePlaidSuccess}
                plaidClient={plaidClient}
              />
            </div>
          ) : (
            <AccountGrid accounts={accounts}
               selectedAccount={selectedAccount}
               handleAccountSelect={handleAccountSelect}
               matchCountByAccount={matchCountByAccount} />
          )
        )}
      </section>

      {/* Lines Table */}
      {selectedAccount && (
        <section className="app-card">
          <div className="flex justify-between items-center mb-2">
            <h2 className="text-xl mb-1">
              {gettext('Lines for')} {selectedAccount.name}
            </h2>
            {pendingIds.size > 0 && (
              <span
                className="ml-auto mr-3 inline-flex items-center gap-1.5 text-xs text-base-content/70"
                role="status"
                data-testid="feed-saving"
              >
                <span className="loading loading-spinner loading-xs" aria-hidden="true" />
                {gettext('Saving…')}
              </span>
            )}
            {selectedPlaidItem && (
              <span className="text-xs text-base-content/70" title={selectedPlaidItem.institutionName}>
                {refreshing
                  ? gettext('Syncing…')
                  : formatLastSynced(selectedPlaidItem.lastSyncedAt)}
              </span>
            )}
          </div>
          <div className="flex flex-wrap gap-x-6 gap-y-1 mb-4 text-sm">
            <span className="text-base-content/70">
              {gettext('Categorized balance')}:{' '}
              <span className="font-semibold text-base-content">
                {formatCurrency(selectedAccount.categorized_balance ?? selectedAccount.balance)}
              </span>
            </span>
            <span className="text-base-content/70">
              {gettext('Reconciled balance')}:{' '}
              <span className="font-semibold text-base-content">
                {formatCurrency(selectedAccount.reconciled_balance ?? 0)}
              </span>
              {selectedAccount.last_statement_date ? (
                <span className="ml-2" data-testid="reconciled-through">
                  {gettext('reconciled through')}{' '}
                  {new Date(`${selectedAccount.last_statement_date}T00:00:00`).toLocaleDateString()}{' '}
                  {selectedAccount.last_statement_intact ? (
                    <span className="badge badge-soft badge-success badge-xs">{gettext('Intact')}</span>
                  ) : (
                    <span className="badge badge-soft badge-warning badge-xs">{gettext('Changed')}</span>
                  )}
                </span>
              ) : (
                selectedAccount.latest_reconciled_date && (
                  <span className="text-base-content/70 ml-2">
                    {gettext('as of')} {new Date(selectedAccount.latest_reconciled_date).toLocaleDateString()}
                  </span>
                )
              )}
            </span>
            <a
              className="btn btn-outline btn-xs"
              href={`${book.base}reconcile/${selectedAccount.id}/`}
              data-testid="reconcile-statement-btn"
            >
              {gettext('Reconcile statement')}
            </a>
          </div>
          {error && (
            <div className="alert alert-error mb-4">
              <Icon name="exclamation-circle" className="inline-block shrink-0 w-4 h-4" />
              <span>{error}</span>
            </div>
          )}
          {loading && (
            <div className="flex justify-center items-center py-4">
              <span className="loading loading-spinner loading-lg"></span>
            </div>
          )}
          <LineTable
            lines={lines}
            selectedAccount={selectedAccount}
            allAccounts={allAccounts}
            allPayees={allPayees}
            categorySuggestions={categorySuggestions}
            book={book}
            onAdd={handleAddLine}
            onDelete={handleDeleteLine}
            onEditTransaction={handleEditTransaction}
            selectedIds={selectedIds}
            onSelectionChange={handleSelectionChange}
            onFilterModeChange={setViewMode}
            hidden={loading}
            onUploadClick={() => setShowUploadWizard(true)}
            onRefresh={handleRefresh}
            refreshing={refreshing}
            uploadDisabled={loading}
            plaidClient={plaidClient}
            onLinkSuccess={handlePlaidSuccess}
            onOpenTransferLeg={handleOpenTransferLeg}
            feedAccountIds={feedAccountIds}
            focusRequest={focusRequest}
            pendingIds={pendingIds}
            matchByTxId={matchByTxId}
            onMatch={handleMatch}
            onDismissMatch={handleDismissMatch}
            onOpenMatchCounterpart={handleOpenMatchCounterpart}
          />
        </section>
      )}

      {/* CSV Upload Wizard Modal */}
      {showUploadWizard && selectedAccount && (
        <CSVUploadWizard
          selectedAccount={selectedAccount}
          allAccounts={allAccounts}
          allAccountGroups={allAccountGroups}
          uploadApi={uploadApi}
          onComplete={(result) => {
            setShowUploadWizard(false);
            // Bring in the newly imported transactions without hiding the feed
            writeEpochRef.current += 1;
            scheduleQuietRefresh();
            if (result) {
              const created = result.created_count ?? result.createdCount ?? 0;
              const skipped = result.skipped_count ?? result.skippedCount ?? 0;
              const parts = [`${created} ${gettext('transactions imported')}`];
              if (skipped > 0) {
                parts.push(`${skipped} ${gettext('skipped')}`);
              }
              showSnackbar(parts.join(', '), 'success');
            }
          }}
          onCancel={() => setShowUploadWizard(false)}
        />
      )}

      {/* Batch Action Bar */}
      <BatchActionBar
        selectedCount={selectedIds.size}
        selectedRows={selectedRows}
        allAccounts={allAccounts}
        allPayees={allPayees}
        bankFeedAccounts={accounts}
        onBulkEdit={handleBulkEdit}
        onArchive={handleBatchArchive}
        onUnarchive={handleBatchUnarchive}
        onDelete={handleBatchDelete}
        onDuplicate={handleBatchDuplicate}
        onReconcile={handleBatchReconcile}
        onUnreconcile={handleBatchUnreconcile}
        onClearSelection={() => setSelectedIds(new Set())}
        showArchive={showArchiveButton}
        showUnarchive={showUnarchiveButton}
        viewMode={viewMode}
        selectedAccount={selectedAccount}
      />

      {/* Batch operation result. The 6s hold is carried over from the Snackbar
          this replaces — long enough to read a failure message. */}
      <Toast
        open={snackbar.open}
        message={snackbar.message}
        severity={snackbar.severity}
        onClose={handleCloseSnackbar}
        autoHideMs={6000}
        testId="batch-toast"
      />
    </div>
  );
};

export default LineApp;
