/* globals gettext, ngettext, interpolate */

import React, { useEffect, useState, useMemo, useCallback, useRef } from 'react';
import { Toast } from '../../common/Toast';
import Combobox from '../../common/Combobox';
import Modal from '../../common/Modal';

import AccountGrid from './AccountGrid';
import LineTable from './LineTable';
import PlaidLinkButton from './PlaidLinkButton';
import { CSVUploadWizard } from './CSVUploadWizard';
import BatchActionBar from './BatchActionBar';
import { getBatchOperationsApi, getTransactionApi } from '../bank_feed';
import {
  NO_QUICK_FILTERS,
  filterParams,
  queryFromUrl,
  rowSetKey,
  summaryAsRow,
  writeQueryToUrl,
} from '../feedQuery';
import { formatCurrency } from '../../utilities/currency';
import Icon from '../../common/Icon';
import { BankFeedRowFromJSON } from 'api-client';

/** How long the feed waits after its last write settles before re-reading it. */
const QUIET_REFRESH_DELAY_MS = 500;
/** How long a row the page was asked to show keeps flashing. */
const HIGHLIGHT_MS = 2000;
/** The most rows "select all matching" takes (the server's `MAX_IDS`). */
const MAX_SELECTION = 1000;

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

/** Fields a bulk edit changes on a row that stays in view. */
const optimisticBulkEditedRow = (row, updates, accountsById) => {
  const next = { ...row };
  if (updates.payee) next.payee = updates.payee;
  if (updates.description) next.description = updates.description;
  if (updates.date) next.postedDate = asRowDate(updates.date);
  if (updates.category_id) {
    next.category = { id: updates.category_id, name: accountsById.get(updates.category_id)?.name ?? '' };
  }
  if (updates.account_id) {
    const account = accountsById.get(updates.account_id);
    next.account = { ...(row.account || {}), id: updates.account_id, name: account?.name ?? '' };
  }
  return next;
};

const isVoidRow = (r) => r.isVoid ?? r.is_void ?? false;
const isReconciledRow = (r) => r.isReconciled ?? r.is_reconciled ?? false;

/**
 * LineApp - the Inbox: every bank-feed account's rows in one table.
 *
 * The table is a window onto one server-side queryset. This component owns what
 * is being looked at (`query`: accounts, view, quick filters, dates, sort, page),
 * requests one page whenever it changes, and mirrors it into the URL. The cards
 * above the table are a filter, not a gate: with no account chosen the table
 * shows every account, with an Account column.
 */
const LineApp = ({
  accounts: initialAccounts,
  allAccounts,
  allPayees,
  allAccountGroups,
  book,
  bankFeedClient,
  plaidClient,
  uploadApi,
}) => {
  // Store accounts in state so balances can be refreshed after writes
  const [accounts, setAccounts] = useState(initialAccounts);
  const [query, setQuery] = useState(() => queryFromUrl());
  const queryRef = useRef(query);
  queryRef.current = query;

  // The page on screen, as the server returned it
  const [lines, setLines] = useState([]);
  const [total, setTotal] = useState(0);
  const [counts, setCounts] = useState(null);
  const [initialLoading, setInitialLoading] = useState(true);
  const [refetching, setRefetching] = useState(false);
  const [error, setError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);

  // CSV upload: the account it goes to, chosen first when the Inbox shows several
  const [uploadAccount, setUploadAccount] = useState(null);
  const [choosingUploadAccount, setChoosingUploadAccount] = useState(false);
  const [uploadChoice, setUploadChoice] = useState(null);

  // Account cards start open on the whole Inbox and collapsed on a filtered view
  const [isAccountPickerOpen, setIsAccountPickerOpen] = useState(() => query.accounts.length === 0);

  // Selection across pages: id -> the row as last seen (a full row from a page,
  // or a summary from "select all matching" -- the batch bar reads either).
  const [selection, setSelection] = useState(() => new Map());
  const [selectingAll, setSelectingAll] = useState(false);

  // Plaid sync status: ledger account id -> PlaidItem (for "last synced" display)
  const [plaidItemsByAccountId, setPlaidItemsByAccountId] = useState({});

  // Category suggestions: merchant/payee name -> {id, name} of last-used category
  const [categorySuggestions, setCategorySuggestions] = useState({});

  // A row the page was asked to show -- the other side of a transfer -- flashes
  const [highlightId, setHighlightId] = useState(null);

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
  const loadSeqRef = useRef(0);

  const accountsById = useMemo(() => new Map((allAccounts || []).map((a) => [a.id, a])), [allAccounts]);
  const feedAccountsById = useMemo(() => new Map(accounts.map((a) => [a.id, a])), [accounts]);

  // The one account the Inbox is filtered to, if it is filtered to exactly one:
  // its header, balances, Reconcile link and Plaid refresh apply then.
  const selectedAccount = query.accounts.length === 1 ? feedAccountsById.get(query.accounts[0]) ?? null : null;

  // Snackbar state for batch operations
  const [snackbar, setSnackbar] = useState({ open: false, message: '', severity: 'info', action: null });

  // Accounts that have a feed of their own. A row categorized to one of these is
  // a transfer, and the only kind of row with another feed to link across to.
  const feedAccountIds = useMemo(() => new Set(accounts.map((a) => a.id)), [accounts]);

  const batchApi = useMemo(() => getBatchOperationsApi(book.base), [book]);
  const transactionApi = useMemo(() => getTransactionApi(book.base), [book]);

  const showSnackbar = useCallback((message, severity = 'info', action = null) => {
    setSnackbar({ open: true, message, severity, action });
  }, []);
  const handleCloseSnackbar = () => setSnackbar((s) => ({ ...s, open: false }));

  // --- possible transfers ----------------------------------------------

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
    const result = new Map();
    matches.forEach((pair) => {
      [pair.outflow, pair.inflow].forEach((leg) => {
        const id = leg.account?.id;
        if (id != null) result.set(id, (result.get(id) || 0) + 1);
      });
    });
    return result;
  }, [matches]);

  // Legs of possible transfers in the accounts being looked at: the quick filter's badge
  const transferCount = useMemo(() => {
    const scope = query.accounts.length ? new Set(query.accounts) : null;
    return matches.reduce(
      (n, pair) => n + [pair.outflow, pair.inflow].filter((leg) => !scope || scope.has(leg.account?.id)).length,
      0
    );
  }, [matches, query.accounts]);

  // --- balances, Plaid, suggestions ------------------------------------

  const loadAccounts = useCallback(async () => {
    try {
      setAccounts(await batchApi.fetchFeedAccounts());
    } catch (err) {
      console.error('Failed to refresh account balances:', err);
    }
  }, [batchApi]);

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

  // --- the page ------------------------------------------------------------

  /**
   * Read one page of `q` from the server. `quiet` keeps the table as it is
   * while reading and drops the answer if anything was written meanwhile (a
   * background refresh after writes); otherwise the table dims until it lands.
   * A later request always wins over an earlier one.
   */
  const fetchPage = useCallback(
    async (q, { quiet = false } = {}) => {
      const seq = ++loadSeqRef.current;
      const epoch = writeEpochRef.current;
      if (!quiet) setRefetching(true);
      try {
        const response = await bankFeedClient.bankFeedFeedListRaw({
          ...book.params,
          ...filterParams(q),
          page: q.page + 1,
          counts: true,
        });
        const json = await response.raw.json();
        if (seq !== loadSeqRef.current) return;
        if (quiet && (epoch !== writeEpochRef.current || inFlightRef.current > 0)) return;
        setLines((json.results || []).map(BankFeedRowFromJSON));
        setTotal(json.count ?? 0);
        setCounts(json.counts ?? null);
        setError(null);
      } catch (err) {
        if (seq !== loadSeqRef.current) return;
        // Past the last page: rows left the view (voided, moved, deleted). Step back.
        if (err?.response?.status === 404 && q.page > 0) {
          setQuery((prev) => (prev.page === q.page ? { ...prev, page: prev.page - 1 } : prev));
          return;
        }
        console.error('Failed to load the feed:', err);
        if (!quiet) setError(gettext('Failed to load transactions. Please try again.'));
      } finally {
        if (seq === loadSeqRef.current) {
          setRefetching(false);
          setInitialLoading(false);
        }
      }
    },
    [bankFeedClient, book]
  );

  useEffect(() => {
    fetchPage(query);
    writeQueryToUrl(query);
  }, [query, fetchPage]);

  // A different set of rows (accounts, view, filters, dates) is a different
  // selection: rows selected under the old one may not be in the new one.
  const setKey = rowSetKey(query);
  useEffect(() => {
    setSelection(new Map());
  }, [setKey]);

  /** Change what the table is looking at. Anything but the page returns to page 1. */
  const updateQuery = useCallback((patch) => {
    setQuery((prev) => {
      const next = { ...prev, ...patch };
      if (!('page' in patch)) next.page = 0;
      return next;
    });
  }, []);

  useEffect(() => {
    if (highlightId == null) return undefined;
    const timer = setTimeout(() => setHighlightId(null), HIGHLIGHT_MS);
    return () => clearTimeout(timer);
  }, [highlightId]);

  /**
   * Re-read the page, the account balances and the possible transfers once no
   * write is in flight -- a write changes more than the rows it names (the
   * other leg of a transfer, a split's mirror rows), so the page is re-read in
   * the background, keeping the table up and usable.
   */
  const scheduleQuietRefresh = useCallback(() => {
    clearTimeout(quietRefreshTimerRef.current);
    quietRefreshTimerRef.current = setTimeout(() => {
      if (inFlightRef.current > 0) return;
      loadAccounts();
      loadMatches();
      fetchPage(queryRef.current, { quiet: true });
    }, QUIET_REFRESH_DELAY_MS);
  }, [loadAccounts, loadMatches, fetchPage]);

  useEffect(() => () => clearTimeout(quietRefreshTimerRef.current), []);

  const markPending = (ids, delta) => {
    const pending = pendingCountsRef.current;
    ids.forEach((id) => {
      const next = (pending.get(id) || 0) + delta;
      if (next > 0) pending.set(id, next);
      else pending.delete(id);
    });
    setPendingIds(new Set(pending.keys()));
  };

  /** Drop rows from the selection -- the ones a refused batch named, say. */
  const deselect = useCallback((ids) => {
    const drop = new Set(ids.map(String));
    setSelection((prev) => new Map([...prev].filter(([id]) => !drop.has(id))));
  }, []);

  /**
   * Apply a write to the table now and send it to the server in the background.
   *
   * `apply(row)` returns the row as it will look once the write lands, or null
   * when the row leaves the view. The table shows that at once; the rows stay
   * marked as saving until the server answers. On success `onSuccess` may hand
   * back the server's own rows and the selection the write acted on is cleared;
   * on failure every row this write changed -- and nothing has changed since --
   * goes back to how it was, and the server's reason is shown. A refusal that
   * names rows keeps the selection and offers to deselect them. Either way the
   * page is quietly re-read once writes settle.
   */
  const runWrite = ({
    rowIds = [],
    apply = null,
    request,
    onSuccess = null,
    successMessage = null,
    errorMessage,
    clearsSelection = false,
  }) => {
    writeEpochRef.current += 1;
    inFlightRef.current += 1;
    const ids = new Set(rowIds);

    // The rows this write replaced, and what it replaced them with, so a
    // rollback only touches rows still showing this write's version.
    const before = new Map();
    const written = new Map();
    if (apply && ids.size > 0) {
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
        if (clearsSelection) deselect([...ids]);
        if (successMessage) showSnackbar(successMessage, 'success');
      })
      .catch((err) => {
        console.error(errorMessage, err);
        setLines((prev) => {
          const present = new Set(prev.map((row) => row.id));
          const restored = prev.map((row) =>
            written.has(row.id) && written.get(row.id) === row ? before.get(row.id) : row
          );
          // Rows this write removed from the view come back
          before.forEach((row, id) => {
            if (written.get(id) === null && !present.has(id)) restored.push(row);
          });
          return restored;
        });
        const refused = err?.data?.refused;
        if (Array.isArray(refused) && refused.length && ids.size > 1) {
          const refusedIds = refused.map((r) => String(r.id));
          showSnackbar(
            interpolate(gettext('%s of %s can’t take this: %s'), [refused.length, ids.size, refused[0].error]),
            'error',
            <button
              type="button"
              className="btn btn-xs"
              onClick={() => {
                deselect(refusedIds);
                handleCloseSnackbar();
              }}
              data-testid="deselect-refused"
            >
              {gettext('Deselect them')}
            </button>
          );
        } else {
          showSnackbar(err.message || errorMessage, 'error');
        }
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

  // --- jumping to a row ----------------------------------------------------

  /**
   * Show one row: go to the page it is on and flash it.
   *
   * `target` names the row (`{row}`) or a transfer's other leg (`{journalEntry,
   * inAccount}`). If the current filters hide it, open its own account with the
   * filters cleared (and the voided view if it is void) -- unless `keepFilters`,
   * for a courtesy flash not worth undoing the user's view for.
   */
  const showRow = useCallback(
    async (target, { accountId = null, keepFilters = false } = {}) => {
      const locate = (q) => bankFeedClient.bankFeedLocate({ ...book.params, ...filterParams(q), ...target });
      try {
        const current = queryRef.current;
        const found = await locate(current);
        if (found.id == null) return;
        if (found.page != null) {
          setQuery((prev) => ({ ...prev, page: found.page - 1 }));
          setHighlightId(String(found.id));
          return;
        }
        if (keepFilters) return;
        const opened = {
          ...current,
          accounts: accountId != null ? [accountId] : current.accounts,
          view: found.is_void ? 'voided' : 'active',
          quickFilters: NO_QUICK_FILTERS,
          startDate: '',
          endDate: '',
          page: 0,
        };
        const again = await locate(opened);
        setIsAccountPickerOpen(false);
        setQuery({ ...opened, page: again.page != null ? again.page - 1 : 0 });
        if (again.page != null) setHighlightId(String(again.id));
      } catch (err) {
        console.error('Failed to find the row:', err);
      }
    },
    [bankFeedClient, book]
  );

  /** The other leg of a transfer: the same entry's row in the category account. */
  const handleOpenTransferLeg = useCallback(
    (row) => {
      const target = row.category?.id;
      if (!feedAccountIds.has(target) || !row.journalEntryId) return;
      showRow({ journalEntry: row.journalEntryId, inAccount: target }, { accountId: target });
    },
    [feedAccountIds, showRow]
  );

  /** Open the other leg of a possible transfer. */
  const handleOpenMatchCounterpart = useCallback(
    ({ other }) => showRow({ row: other.imported_transaction_id }, { accountId: other.account?.id }),
    [showRow]
  );

  /**
   * Match a possible duplicate transfer: the server keeps one leg, voids the
   * other, and makes the kept one the transfer between both accounts.
   *
   * Goes through `runWrite` like every other feed write: the legs on screen
   * show the outcome at once (voided, or categorized as the transfer) and come
   * back if the server refuses. The leg the server voids must be the one the
   * panel showed, or it answers 409 with the current proposal, which replaces
   * the stale one so the panel redraws with the new outcome.
   */
  const handleMatch = ({ pair, self, other }) => {
    const proposal = pair.proposal || {};
    const legIds = [self.imported_transaction_id, other.imported_transaction_id];
    const onScreen = lines.filter((l) => legIds.includes(l.importedTransactionId ?? l.imported_transaction_id));
    return runWrite({
      rowIds: onScreen.map((r) => r.id),
      apply: (r) => {
        const txId = r.importedTransactionId ?? r.imported_transaction_id;
        if (txId === proposal.archive_id) return queryRef.current.view === 'voided' ? { ...r, isVoid: true } : null;
        const voidedLeg = txId === self.imported_transaction_id ? other : self;
        return { ...r, category: { id: voidedLeg.account?.id, name: voidedLeg.account?.name ?? '' }, isSplit: false };
      },
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
        const voided = kept === self ? other : self;
        setMatches((prev) => prev.filter((p) => p !== pair));
        showRow({ row: result.kept_id }, { keepFilters: true });
        showSnackbar(
          interpolate(gettext('Matched — kept the one in %s, voided the one in %s.'), [
            kept.account?.name ?? '',
            voided.account?.name ?? '',
          ]),
          'success'
        );
        return null;
      },
      errorMessage: gettext('Could not match these transactions.'),
    });
  };

  /** Not the same transfer: stop suggesting the pair. */
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

  // --- account cards ---------------------------------------------------

  /** A card filters the Inbox to its account; clicking it again shows every account. */
  const handleAccountSelect = (account) => {
    const only = query.accounts.length === 1 && query.accounts[0] === account.id;
    updateQuery({ accounts: only ? [] : [account.id] });
    if (!only) setIsAccountPickerOpen(false);
  };

  // --- Plaid -----------------------------------------------------------

  /**
   * Sync from Plaid: the filtered account's bank, or every linked bank when the
   * Inbox shows several accounts. The sync runs in a background task with no
   * completion signal, so the page is re-read a few times while it finishes.
   */
  const handleRefresh = async () => {
    setRefreshing(true);
    setError(null);
    try {
      let itemIds;
      if (selectedAccount) {
        const plaidAccountsData = await plaidClient.plaidAccountsList({ ...book.params });
        const plaidAccount = plaidAccountsData.results?.find((pa) => pa.account === selectedAccount.id);
        if (!plaidAccount) {
          setError(gettext('This account is not linked to a bank feed.'));
          return;
        }
        itemIds = [plaidAccount.item];
      } else {
        const items = await plaidClient.plaidItemsList({ ...book.params });
        itemIds = (items.results || []).map((item) => item.id);
        if (itemIds.length === 0) {
          setError(gettext('No bank is linked yet. Use “Link Bank Account” to connect one.'));
          return;
        }
      }
      await Promise.all(itemIds.map((id) => plaidClient.plaidItemsSync({ ...book.params, id })));
      for (const delay of [2000, 4000, 6000]) {
        await new Promise((resolve) => setTimeout(resolve, delay));
        await fetchPage(queryRef.current, { quiet: true });
      }
      await Promise.all([loadPlaidStatus(), loadMatches(), loadAccounts()]);
    } catch (err) {
      console.error('Failed to refresh:', err);
      setError(gettext('Failed to refresh bank feed. Please try again.'));
    } finally {
      setRefreshing(false);
    }
  };

  /** Handle successful Plaid Link - reload page to show new accounts */
  const handlePlaidSuccess = () => {
    window.location.reload();
  };

  // --- single-row writes -------------------------------------------------

  /**
   * Add a transaction (manual feed row). The modal waits for this one request --
   * a new row has no id to edit until the server gives it one -- but not for the
   * page to be re-read.
   */
  const handleAddLine = async (lineData) => {
    const accountId = lineData.account ?? selectedAccount?.id;
    const created = await transactionApi.createTransaction({
      date: lineData.date,
      category: lineData.category,
      splits: lineData.splits ?? null,
      inflow: lineData.inflow || '0',
      outflow: lineData.outflow || '0',
      payee: lineData.payee || '',
      description: lineData.description || '',
      account: accountId,
    });
    const q = queryRef.current;
    const inView = q.view === 'active' && (q.accounts.length === 0 || q.accounts.includes(accountId));
    if (created && inView && q.page === 0) {
      const row = BankFeedRowFromJSON(created);
      setLines((prev) => (prev.some((l) => l.id === row.id) ? prev : [row, ...prev]));
      setTotal((n) => n + 1);
    }
    writeEpochRef.current += 1;
    scheduleQuietRefresh();
  };

  /**
   * Edit a transaction from the edit modal. The row shows the edit straight away
   * and the modal closes without waiting. It stays in its own account: the
   * update is sent with the row's account, whichever accounts the Inbox shows.
   */
  const handleEditTransaction = (updatedData, row) => {
    const { id, date, category, splits, remove_split, inflow, outflow, payee, description } = updatedData;
    const accountId = row?.account?.id ?? lines.find((l) => String(l.id) === String(id))?.account?.id;
    return runWrite({
      rowIds: [id],
      apply: (r) => optimisticEditedRow(r, updatedData, accountsById),
      request: () =>
        transactionApi.updateTransaction(id, {
          date,
          category,
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

  // --- selection and batch writes ----------------------------------------

  const selectedIds = useMemo(() => new Set(selection.keys()), [selection]);
  // Rows on this page are read fresh from the page; the rest as they were selected
  const linesById = useMemo(() => new Map(lines.map((l) => [l.id, l])), [lines]);
  const selectedRows = useMemo(
    () => [...selection.values()].map((row) => linesById.get(row.id) ?? row),
    [selection, linesById]
  );

  const handleToggleRows = (rows, checked) => {
    setSelection((prev) => {
      const next = new Map(prev);
      rows.forEach((row) => (checked ? next.set(row.id, row) : next.delete(row.id)));
      return next;
    });
  };

  const handleSelectAllMatching = async () => {
    setSelectingAll(true);
    try {
      const data = await bankFeedClient.bankFeedSelection({ ...book.params, ...filterParams(queryRef.current) });
      const next = new Map();
      (data.results || []).map(summaryAsRow).forEach((row) => next.set(row.id, linesById.get(row.id) ?? row));
      setSelection(next);
    } catch (err) {
      console.error('Failed to select every matching row:', err);
      showSnackbar(gettext('Could not select every matching transaction.'), 'error');
    } finally {
      setSelectingAll(false);
    }
  };

  const pageSelected = lines.length > 0 && lines.every((l) => selection.has(l.id));
  let selectAllMatching = null;
  if (pageSelected && selection.size < total && total > lines.length) {
    selectAllMatching =
      total > MAX_SELECTION
        ? { tooMany: true }
        : { offer: true, busy: selectingAll, onSelect: handleSelectAllMatching };
  }

  /** Every selected row in full, fetching those that were selected as summaries. */
  const getExportRows = async () => {
    const missing = selectedRows.filter((row) => row.summaryOnly).map((row) => row.id);
    const fetched = new Map();
    for (let i = 0; i < missing.length; i += 200) {
      const response = await bankFeedClient.bankFeedFeedListRaw({
        ...book.params,
        ids: missing.slice(i, i + 200).join(','),
        pageSize: 200,
      });
      const json = await response.raw.json();
      (json.results || []).map(BankFeedRowFromJSON).forEach((row) => fetched.set(row.id, row));
    }
    return selectedRows.map((row) => fetched.get(row.id) ?? row);
  };

  // The one account every selected row is in, if there is one: reconciling and
  // the reconciled-balance preview are about one account's statement.
  const selectionAccount = useMemo(() => {
    const ids = new Set(selectedRows.map((r) => r.account?.id));
    return ids.size === 1 ? feedAccountsById.get([...ids][0]) ?? null : null;
  }, [selectedRows, feedAccountsById]);

  const handleBulkEdit = (updates) => {
    const ids = [...selectedIds];
    const q = queryRef.current;
    runWrite({
      rowIds: ids,
      // Moved to an account the Inbox isn't showing, the rows leave the view
      apply: (row) =>
        updates.account_id && q.accounts.length && !q.accounts.includes(updates.account_id)
          ? null
          : optimisticBulkEditedRow(row, updates, accountsById),
      request: () => batchApi.batchEdit(ids, updates),
      successMessage: interpolate(ngettext('Transaction updated', '%s transactions updated', ids.length), [ids.length]),
      errorMessage: ngettext('Failed to update the transaction', 'Failed to update the transactions', ids.length),
      clearsSelection: true,
    });
  };

  // Voiding in the active view, or restoring in the voided one, takes the rows out of view
  const handleBatchVoid = () => {
    const ids = [...selectedIds];
    runWrite({
      rowIds: ids,
      apply: (row) => (queryRef.current.view === 'voided' ? { ...row, isVoid: true } : null),
      request: () => batchApi.batchVoid(ids),
      successMessage: interpolate(ngettext('Transaction voided', '%s transactions voided', ids.length), [ids.length]),
      errorMessage: ngettext('Failed to void the transaction', 'Failed to void the transactions', ids.length),
      clearsSelection: true,
    });
  };

  const handleBatchRestore = () => {
    const ids = [...selectedIds];
    runWrite({
      rowIds: ids,
      apply: (row) => (queryRef.current.view === 'voided' ? null : { ...row, isVoid: false }),
      request: () => batchApi.batchRestore(ids),
      successMessage: interpolate(ngettext('Transaction restored', '%s transactions restored', ids.length), [
        ids.length,
      ]),
      errorMessage: ngettext('Failed to restore the transaction', 'Failed to restore the transactions', ids.length),
      clearsSelection: true,
    });
  };

  /** Permanently delete selected voided transactions */
  const handleBatchDelete = () => {
    const ids = [...selectedIds];
    runWrite({
      rowIds: ids,
      apply: () => null,
      request: () => batchApi.batchDelete(ids),
      successMessage: interpolate(
        ngettext('Transaction permanently deleted', '%s transactions permanently deleted', ids.length),
        [ids.length]
      ),
      errorMessage: ngettext('Failed to delete the transaction', 'Failed to delete the transactions', ids.length),
      clearsSelection: true,
    });
  };

  const handleBatchDuplicate = () => {
    const ids = [...selectedIds];
    runWrite({
      rowIds: ids,
      // The copies have no ids until the server makes them; the re-read brings them in
      request: () => batchApi.batchDuplicate(ids),
      // The server answers with the copies it made: a reconciled row is not
      // copied, and a transfer with both legs selected is copied once.
      onSuccess: (created) => {
        const made = Array.isArray(created) ? created.length : 0;
        if (made === 0) {
          showSnackbar(
            ngettext(
              'This transaction could not be duplicated.',
              'None of these transactions could be duplicated.',
              ids.length
            ),
            'warning'
          );
          return null;
        }
        showSnackbar(
          made === ids.length
            ? interpolate(ngettext('Transaction duplicated', '%s transactions duplicated', made), [made])
            : interpolate(gettext('Duplicated %s of %s transactions'), [made, ids.length]),
          'success'
        );
        // Show the copy: under some sorts it lands on another page than its original
        showRow({ row: created[0].id }, { keepFilters: true });
        return null;
      },
      errorMessage: ngettext('Failed to duplicate the transaction', 'Failed to duplicate the transactions', ids.length),
      clearsSelection: true,
    });
  };

  /**
   * Reconcile the selection against a statement: hand it to the reconcile page,
   * which opens (or resumes) the account's draft with these rows already ticked.
   * Only offered when every selected row is in one account.
   */
  const handleBatchReconcile = (rows) => {
    if (!selectionAccount) return;
    const entries = (rows || []).map((r) => r.journal_entry_id ?? r.journalEntryId).filter(Boolean);
    const qs = entries.length ? `?entries=${entries.join(',')}` : '';
    window.location.href = `${book.base}reconcile/${selectionAccount.id}/${qs}`;
  };

  const handleBatchUnreconcile = () => {
    const ids = [...selectedIds];
    runWrite({
      rowIds: ids,
      apply: (row) => ({ ...row, isReconciled: false, reconciledStatementDate: undefined }),
      request: () => batchApi.batchUnreconcile(ids),
      successMessage: interpolate(ngettext('Transaction unreconciled', '%s transactions unreconciled', ids.length), [
        ids.length,
      ]),
      errorMessage: ngettext(
        'Failed to unreconcile the transaction',
        'Failed to unreconcile the transactions',
        ids.length
      ),
      clearsSelection: true,
    });
  };

  const showVoidButton = useMemo(
    () => selectedRows.some((r) => !isVoidRow(r) && !isReconciledRow(r)),
    [selectedRows]
  );
  const showRestoreButton = useMemo(() => selectedRows.some((r) => isVoidRow(r)), [selectedRows]);

  // --- CSV upload ----------------------------------------------------------

  const handleUploadClick = () => {
    if (selectedAccount) {
      setUploadAccount(selectedAccount);
    } else {
      setUploadChoice(null);
      setChoosingUploadAccount(true);
    }
  };

  const uploadOptions = useMemo(() => accounts.map((a) => ({ id: a.id, label: a.name, name: a.name })), [accounts]);

  /** Human-friendly "last synced" label for a Plaid item */
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
  const heading = selectedAccount
    ? `${gettext('Lines for')} ${selectedAccount.name}`
    : query.accounts.length > 1
      ? interpolate(gettext('%s accounts'), [query.accounts.length])
      : gettext('All accounts');

  return (
    <div className="space-y-6">
      {/* Account cards: a filter on the table below, not a gate in front of it */}
      <section className="app-card">
        <div className="flex justify-between items-center mb-4">
          <button
            type="button"
            className="flex items-center gap-2 min-w-0"
            onClick={() => setIsAccountPickerOpen((open) => !open)}
            aria-expanded={isAccountPickerOpen}
            data-testid="account-picker-toggle"
          >
            <Icon
              name={isAccountPickerOpen ? 'chevron-down' : 'chevron-right'}
              className="inline-block w-3.5 h-3.5 shrink-0 text-base-content/70"
            />
            <h2 className="text-xl mb-1">{gettext('Accounts')}</h2>
            {!isAccountPickerOpen && selectedAccount && (
              <span className="text-sm font-normal text-base-content/70 truncate">— {selectedAccount.name}</span>
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
        {isAccountPickerOpen &&
          (accounts.length === 0 ? (
            <div className="alert alert-warning">
              <Icon name="exclamation-triangle" className="inline-block shrink-0 w-4 h-4" />
              <span>{gettext('No accounts with bank feeds found. Please link a bank account to get started.')}</span>
              <PlaidLinkButton
                book={book}
                allAccounts={allAccounts}
                onSuccess={handlePlaidSuccess}
                plaidClient={plaidClient}
              />
            </div>
          ) : (
            <AccountGrid
              accounts={accounts}
              selectedAccount={selectedAccount}
              handleAccountSelect={handleAccountSelect}
              matchCountByAccount={matchCountByAccount}
            />
          ))}
      </section>

      {accounts.length > 0 && (
        <section className="app-card">
          <div className="flex justify-between items-center mb-2">
            <h2 className="text-xl mb-1" data-testid="feed-heading">
              {heading}
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
                {refreshing ? gettext('Syncing…') : formatLastSynced(selectedPlaidItem.lastSyncedAt)}
              </span>
            )}
            {!selectedAccount && refreshing && (
              <span className="text-xs text-base-content/70">{gettext('Syncing…')}</span>
            )}
          </div>
          {selectedAccount && (
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
          )}
          {error && (
            <div className="alert alert-error mb-4">
              <Icon name="exclamation-circle" className="inline-block shrink-0 w-4 h-4" />
              <span>{error}</span>
            </div>
          )}
          {initialLoading ? (
            <div className="flex justify-center items-center py-4">
              <span className="loading loading-spinner loading-lg"></span>
            </div>
          ) : (
            <LineTable
              lines={lines}
              total={total}
              counts={counts}
              query={query}
              onQueryChange={updateQuery}
              accounts={accounts}
              showAccountColumn={query.accounts.length !== 1}
              refetching={refetching}
              allAccounts={allAccounts}
              allPayees={allPayees}
              categorySuggestions={categorySuggestions}
              book={book}
              defaultAccountId={selectedAccount?.id ?? null}
              onAdd={handleAddLine}
              onEditTransaction={handleEditTransaction}
              selectedIds={selectedIds}
              onToggleRows={handleToggleRows}
              selectAllMatching={selectAllMatching}
              onUploadClick={handleUploadClick}
              onRefresh={handleRefresh}
              refreshing={refreshing}
              uploadDisabled={initialLoading}
              plaidClient={plaidClient}
              onLinkSuccess={handlePlaidSuccess}
              onOpenTransferLeg={handleOpenTransferLeg}
              feedAccountIds={feedAccountIds}
              highlightId={highlightId}
              pendingIds={pendingIds}
              transferCount={transferCount}
              matchByTxId={matchByTxId}
              onMatch={handleMatch}
              onDismissMatch={handleDismissMatch}
              onOpenMatchCounterpart={handleOpenMatchCounterpart}
            />
          )}
        </section>
      )}

      {/* CSV upload: which account, when the Inbox shows several */}
      <Modal
        open={choosingUploadAccount}
        onClose={() => setChoosingUploadAccount(false)}
        size="sm"
        title={gettext('Upload to which account?')}
        testId="upload-account-dialog"
        actions={
          <>
            <button type="button" className="btn btn-sm" onClick={() => setChoosingUploadAccount(false)}>
              {gettext('Cancel')}
            </button>
            <button
              type="button"
              className="btn btn-sm btn-primary"
              disabled={!uploadChoice}
              onClick={() => {
                setChoosingUploadAccount(false);
                setUploadAccount(feedAccountsById.get(uploadChoice.id) ?? null);
              }}
              data-testid="upload-account-continue"
            >
              {gettext('Continue')}
            </button>
          </>
        }
      >
        <Combobox
          label={gettext('Account')}
          value={uploadChoice}
          onChange={setUploadChoice}
          options={uploadOptions}
          placeholder={gettext('Choose an account')}
          testId="upload-account"
        />
      </Modal>

      {uploadAccount && (
        <CSVUploadWizard
          selectedAccount={uploadAccount}
          allAccounts={allAccounts}
          allAccountGroups={allAccountGroups}
          uploadApi={uploadApi}
          onComplete={(result) => {
            setUploadAccount(null);
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
          onCancel={() => setUploadAccount(null)}
        />
      )}

      <BatchActionBar
        selectedCount={selectedIds.size}
        selectedRows={selectedRows}
        allAccounts={allAccounts}
        allPayees={allPayees}
        bankFeedAccounts={accounts}
        onBulkEdit={handleBulkEdit}
        onVoid={handleBatchVoid}
        onRestore={handleBatchRestore}
        onDelete={handleBatchDelete}
        onDuplicate={handleBatchDuplicate}
        onReconcile={handleBatchReconcile}
        onUnreconcile={handleBatchUnreconcile}
        onClearSelection={() => setSelection(new Map())}
        showVoid={showVoidButton}
        showRestore={showRestoreButton}
        viewMode={query.view}
        selectedAccount={selectionAccount}
        getExportRows={getExportRows}
      />

      {/* Batch operation result. Held 6s -- long enough to read a failure message. */}
      <Toast
        open={snackbar.open}
        message={snackbar.message}
        severity={snackbar.severity}
        onClose={handleCloseSnackbar}
        autoHideMs={6000}
        action={snackbar.action}
        testId="batch-toast"
      />
    </div>
  );
};

export default LineApp;
