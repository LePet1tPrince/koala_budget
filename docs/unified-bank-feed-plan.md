# Unified bank feed

Goal: the Inbox (`/a/{team}/{book}/bankfeed/`) shows **one table of every bank-feed account's rows**, with an Account column. Bulk editing across accounts then comes from the feed's existing batch bar and endpoints, which already work per row.

Supersedes the earlier "bulk edit on the Transactions page" plan: editing the ledger directly is dropped. The Transactions page is unchanged.

Status: Phases 0–2 built. Rebased on `develop` at `9b98927` (#247); §0.1 lists what landed there since the plan was written and what it changed here. §6 lists where the build departed from this plan. Open: the `EXPLAIN`/index check (§2.1) and D3.

---

## 0. What exists

**Page.** `LineApp.jsx` shows the account cards (`AccountGrid`) as a picker; choosing one loads that account's rows and renders `LineTable.jsx`. Nothing shows until an account is chosen.

**Rows.** `GET bankfeed/api/feed/?account=<id>` (`BankFeedViewSet.list`, page size 200). `LineApp.fetchAllLines` shows page 1 at once, then fetches every remaining page four at a time (#247) and the table filters, counts, sorts and paginates them in memory. `account` is already optional server-side: without it the endpoint returns every `BankTransaction` in the book. Each row already carries `account {id, name, institution}`. `?uncategorized=1` exists and Categorize Mode uses it with the default page size.

**Writes** (#246). `LineApp.runWrite()` applies a write to the rows on screen at once, sends it in the background, swaps in the server's row or rolls back on refusal, and `scheduleQuietRefresh()` re-reads balances, possible transfers and the feed once writes settle (`refreshLinesQuietly`, which re-fetches every page).

**Possible transfers** (#245). `GET transfers/` loads candidate pairs book-wide with the server's proposal; a row in a pair gets a "Match found" chip and `TransferMatchPanel`; a "Possible transfers" quick filter (`filter-transfers`) and a count on each account card are computed client-side from that list. `POST transfers/match` replaced `transfers/resolve`; `services/transfer_match.py::archive_duplicate` voids the duplicate's entry and archives its rows.

**Batch.** `BatchActionBar.jsx` + `BulkEditModal.jsx` over `batch_edit`, `batch_archive`, `batch_unarchive`, `batch_delete`, `batch_duplicate`, `batch_unreconcile` — all take row ids, none take an account. Reconcile navigates to `reconcile/<selectedAccount>/?entries=…`.

**Everything that reads `selectedAccount`** (the list the pivot has to rehome):

| Where | Use |
|---|---|
| `LineApp.loadLines` | `account` query param |
| `LineApp.handleEditTransaction` | sends `account: selectedAccount.id` to `PUT feed/{id}/` |
| `LineApp.handleAddLine` | `account` of the new row |
| `LineApp.handleRefresh` | which Plaid item to sync |
| `LineApp.handleOpenMatchCounterpart`, `handleMatch` (focus after match) | switches to the other leg's account |
| `LineApp.handleBulkEdit` | whether a moved row leaves the view |
| `LineApp` header | "Lines for X", categorized + reconciled balance, "reconciled through", Reconcile statement link, Plaid last-synced |
| `LineApp.handleBatchReconcile` | reconcile URL |
| `LineApp.handleOpenTransferLeg` | switches to the counterpart account |
| `CSVUploadWizard` | target account of the upload |
| `BatchActionBar` | reconciled balance → new preview |
| `LineTable` | renders nothing without it |

### 0.1 Changes on `develop` since the plan (#243–#247) and their effect

| Change | Effect on this plan |
|---|---|
| #247 first page early + parallel page fetch | Superseded by server paging (§2.1): `fetchAllLines`, `loadingMore` and the append logic go. |
| #246 background writes (`runWrite`, quiet refresh) | Kept. Optimistic updates apply to the page on screen; the quiet refresh re-reads **that page** and its counts instead of the whole feed (§2.2). |
| #245 inline transfer match | Phase 0: `archive_duplicate` becomes a `voiding.void` caller (`transfers/resolve` no longer exists). §2.1: "Possible transfers" becomes a server filter. §2.7: "Go to other side" and the post-match flash use `feed/locate/`. |
| `?uncategorized=1` used by Categorize Mode | §2.1 keeps the endpoint's default page size at 200 so Categorize Mode is untouched; the Inbox sends `page_size` explicitly. |
| Portability format is v4 (`hidden_from_budget`, #242) | Phase 0's format bump is **v5** (`upgrade_4_to_5`). |
| Audit migration `0012` (#243) | Phase 0's audit migration is `0013`. |
| #243 goal-linked accounts, #244 CSV sign default | No effect. |

---

## 1. Phase 0 — one void state for a transaction and its bank rows

Ships first, on its own. The unified feed (§2) is built on the renamed field and its Voided view is the restore view.

### 1.1 The problem today

Two independent flags mean "doesn't count":

| | `JournalEntry.status == "void"` | `BankTransaction.is_archived` |
|---|---|---|
| Set by | Transactions page Void (edit modal), `journal-entries/{id}/void_entry/`, reconciliation undo (adjustment entry), transfer match (`archive_duplicate`) | Bank Feed Archive, reconciliation undo, transfer match (`archive_duplicate`) |
| Effect on balances | entry excluded | the linked entry excluded (`counted_entries()` subquery) |
| Effect on the other flag | none | none |

So a voided entry's bank row stays in the Inbox looking categorized, an archived row's entry stays `posted`, and two of the four writers already set both by hand.

### 1.2 The invariant

For every `BankTransaction` linked to a `JournalEntry`:

> `row.is_void == (entry.status == "void")`

This covers **every** row on the entry — the primary, a transfer's mirror, and each mirror of a split's transfer legs — so a transfer is void in both feeds or in neither.

A row with **no** entry (uncategorized) has its own `is_void`: voiding a duplicate bank import that was never categorized is still needed. An entry with **no** row (manual, opening balance, YNAB tracking-account history) has only its status.

### 1.3 Rename: `BankTransaction.is_archived` → `is_void`

- `is_archived` → `is_void`, `archived_at` → `voided_at` (`RenameField`, no data copy).
- The field is inherited from `apps.utils.models.BaseModel`. Django lets an abstract parent's field be removed in the child (`is_archived = None`, `archived_at = None`), so `BankTransaction` declares its own `is_void` / `voided_at` and removes the inherited pair. `BaseModel.archive()`, `restore()` and `is_active` read `is_archived`, so `BankTransaction` overrides them (`is_active` → `not is_void`; `archive()`/`restore()` raise, pointing at the voiding service) — the only current caller, reconciliation undo, moves to the service.
- Other models keep `is_archived` (accounts, groups, goals — archiving those is real).
- **Transactions are not archived either.** `JournalEntry` also inherits `is_archived`/`archived_at`, and `JournalLine` declares its own `is_archived`; nothing reads any of the three (only `apps.portability` carries them). Remove them the same way, so "void" is the only word for "doesn't count" on either model.
- Scope of the rename (every `BankTransaction` read of `is_archived`): `bank_feed` views (feed-account activity, batch archive/unarchive/delete, transfer resolve), serializers, admin, `context_processors.inbox_count`, `services/transfer_detection`, `services/similar_transactions`, `reconciliation/services/candidates` + `session.undo`, `monthly_review/services/health` + `review`, `portability` (schema/read/export/apply). Frontend: `bank_feed.js`, `LineApp.jsx`, `LineTable.jsx`, `BatchActionBar.jsx`, `CategorizeMode.jsx`. E2E: `factories.py`, `pages/bank_feed.py`, `tests/test_books.py`.

### 1.4 One writer

New `apps/journal/services/voiding.py`, the only code that changes void state:

- `void(entries=(), rows=())` / `restore(entries=(), rows=())`. A row resolves to its entry; an entry expands to all its rows. Uncategorized rows are handled alone.
- Guard (unchanged rule, now applied to both): refused if any line on the entry is reconciled (`assert_entry_voidable`). All-or-nothing; the refusal names the rows (§2.9).
- Per-instance `save()` on entries (so `AuditLog` records the status change); rows in the same `transaction.atomic`.
- Callers switched to it: `simple_edit.set_status`, `JournalEntryViewSet.void_entry`, `BankFeedViewSet.batch_archive`/`batch_unarchive`, `transfer_match.archive_duplicate`, `reconciliation.services.session.undo`.

**Backstop in the models**, so a caller that skips the service cannot drift:

- `BankTransaction.save()`: when linked, `is_void` is copied from the entry. For a linked row the entry's status is the truth and the row's flag is a stored copy (kept stored, not derived, because a dozen feed queries filter on it).
- `JournalEntry.save()`: when `status` changes, `bank_feed_transactions` are updated to match.
- Linking rules: categorizing a void row is refused ("Restore it first"); a void entry cannot be edited (already true in `simple_edit`, added to the feed's `update`/`batch_edit`/`categorize`). Unlinking (de-categorize, delete) leaves the row's flag as it was.
- `QuerySet.update()` and `bulk_create` bypass `save()`. A structure test (like `apps/books/tests/test_structure.py`'s AST scan) refuses `.update(status=…)` on `JournalEntry` and `.update(is_void=…)` on `BankTransaction` outside `voiding.py`; the bulk writers (`apps.ynab_import` apply, `apps.portability` apply) assert the invariant over what they wrote before committing.

### 1.5 Data migration

Bring existing data into line, then rely on the invariant:

1. Row archived, entry `posted` → entry `void`, every row on it void.
2. Entry `void`, a row not archived → every row on it void.
3. Transfer legs that disagree → all void.

**Balance-neutral by construction:** `counted_entries()` already excludes an entry that is void *or* behind an archived row, so every entry this touches was already out of every balance. The migration asserts it: net worth and each account's balance before = after, or it aborts. It prints how many entries/rows changed and how many carry reconciled lines (already excluded; nothing moves). Reverse: rename back; the status changes stay (still excluded under the old rule).

A `manage.py void_consistency [--book slug] [--fix]` command runs the same check on demand and in CI fixtures.

### 1.6 Consequences

- `counted_entries()` becomes `~Q(status=void)`; the `BankTransaction` subquery leaves every balance, report and budget query.
- Bank Feed: the **Archived** view becomes **Voided** (`filter-voided`), Archive/Unarchive become **Void/Restore**, endpoints `batch_void`/`batch_restore` (renamed; the api-client is patched/regenerated). The old reconciled rule "silently skip a plain reconciled row" becomes a refusal naming it.
- Transfer match's `archive_duplicate` becomes one `void()` call.
- Audit: new `AuditEvent` types `BULK_VOID`/`BULK_RESTORE` (audit migration `0013`); `BULK_ARCHIVE`/`BULK_UNARCHIVE` stay as choices for history.
- Portability format **v5**: `feed_is_archived`/`feed_archived_at` → `feed_is_void`/`feed_voided_at`; `entry_is_archived` and the line `is_archived` column dropped. `upgrade_4_to_5` renames the columns and applies 1.5's rules to the imported rows, so an old archive lands consistent; the manifest checksums still match because the rules are balance-neutral.
- Tests: the invariant holds after every write path (categorize, decategorize, split, transfer mirror create/move/remove, void, restore, resolve, reconciliation undo, CSV/Plaid/YNAB/portability import).
- **Restore view.** The unified feed's Voided view (§2.6) lists every voided bank row in the book, categorized or not; Restore there calls `voiding.restore`. Entries with **no** bank row (voided from the Transactions edit modal: manual entries, opening balances, tracking-account history) are in no feed → D3.

---

## 2. The unified table

### 2.1 One query, paged on the server

Today the client fetches **every** page of an account's rows (200 per request) and then filters, counts, sorts and pages in memory. Across all accounts that is the whole book on every visit (the YNAB sample: 6,860 rows, ~35 requests). Instead the table becomes a window onto **one queryset**, the same pattern as the Transactions page: the client asks for one page, the server does the rest.

`GET bankfeed/api/feed/` — one `BankTransaction` queryset for the book:

```
BankTransaction.objects.filter(book=book, account__has_feed=True)   # accounts hidden from the Inbox drop out
  .filter(account_id__in=…)                                         # ?account=1,2  (absent = all)
  .filter(is_void=…)                                                # ?view=active|voided
  .annotate(row_reconciled=Exists(JournalLine: same entry, same account, is_reconciled))
  .filter(<quick filters>, <date range>)
  .order_by(<sort>, "-created_at", "-pk")                            # pk tie-break: no row on two pages
  [offset:offset + page_size]
```

| Param | Values | Replaces (client-side today) |
|---|---|---|
| `account` | comma list of ids; absent = all feed accounts | the selected card |
| `view` | `active` (default) · `voided` | the Archived toggle |
| `to_review` / `reconciled` | `1` (mutually exclusive, 400 if both) | Quick Filters |
| `uncategorized` | `1` → `journal_entry IS NULL` | Quick Filters |
| `transfers` | `1` → rows in a possible-transfer pair (`find_transfer_candidates`, computed only when this filter is on) | "Possible transfers" quick filter |
| `start_date` / `end_date` | ISO dates on `posted_date` | date range picker |
| `sort` / `dir` | `date`, `account`, `payee`, `category`, `inflow`, `outflow`, `description` · `asc`/`desc` | column header sort |
| `page` / `page_size` | `page_size` ∈ 10, 25, 50, 100, 200; default stays 200 for Categorize Mode, the Inbox always sends it | `TablePager` |

Response: `{count, next, previous, results, counts}`.

- **`counts`** = `{to_review, reconciled, uncategorized, voided}` for the account filter alone, ignoring quick filters, date range and view — exactly what the menu badges show today. One `aggregate()` with `Count(filter=…)` per key, on the same base queryset. Sent only with `?counts=1`, so Categorize Mode does not pay for it. The "Possible transfers" badge stays client-side: it is derived from the book-wide pair list the page already loads for the chips.
- **Sort keys that need annotation**, applied only when that column is sorted (as `apps/journal/filters.py::annotations_for` does):
  - `category`: uncategorized → `""`; a split → `"Split"`; a transfer mirror → the primary row's account name; otherwise the name of the entry's line whose account is not the row's account (scalar `Subquery`). Matches what the cell renders.
  - `inflow` / `outflow`: `Case` on the sign of `amount`.
  - `account`: board order (`account__account_group__sort_order`, `account__sort_order`), not alphabetical.
- **Cost per request is constant**, not proportional to the book: one `COUNT`, one page query, the existing prefetches (lines, reconciliation, sibling rows), one counts aggregate — about ten queries for 25 rows or 200. Pinned by an `assertNumQueries` test that runs against 10 and 1,000 rows.
- **Index.** Run `EXPLAIN` on the YNAB sample for the default order; if Postgres sorts the whole book, add `Index(fields=["book", "is_void", "-posted_date", "-created_at"])`.
- Backward compatible: `?account=<id>` alone and Categorize Mode's `?uncategorized=1` return what they do today.

### 2.2 The client

- `LineTable.jsx` stops filtering, counting, sorting and paging: `filteredLines`, `filterCounts`, `sortedLines` and the page slice go. Filter, sort and page state lift into `LineApp`, which requests one page whenever any of them changes (the Transactions page's `transactions-app.jsx` shape). A request token drops out-of-order responses.
- Changing a filter or the sort returns to page 1. Filters, sort and page go in the URL (`history.replaceState`), so reload and Back land on the same page of the same view.
- **After an action**: `runWrite` (#246) is kept — the row on screen changes at once and rolls back on refusal. `refreshLinesQuietly` re-reads the current page and its counts (one request) instead of every page; `scheduleQuietRefresh` still re-reads balances and possible transfers too. If the page is now past the last one (rows voided or deleted away), step back to the last page. A row an edit moves out of the current filters leaves the page optimistically, as a bulk move does today.
- `TablePager` reads `count` from the server instead of `sortedLines.length`.
- Paging moves from instant to one round trip. Show the previous page dimmed with a spinner rather than blanking the table.

### 2.3 Account column and filter

- New `account` column after Date: account name, institution in the `title`. Sortable (board order, i.e. `sort_order`, not alphabetical). `table-fixed` width `w-[9rem]`, truncating.
- **Hidden when exactly one account is filtered** — it would repeat one name on every row, and the width goes back to Description.
- **Account filter** in the toolbar: multi-select dropdown (accounts grouped as the cards are, by account group), "All accounts" default. Changing it clears the selection (same rule as the quick filters). Reflected in the URL (`history.replaceState`), so reload and Back keep it.
- **Cards become a filter**, not a gate. Clicking a card filters to that account (clicking it again returns to all); multi-select via the dropdown. The card grid stays collapsible as today. Onboarding's import coach mark targets `[data-testid^="account-card-"]` — unchanged.

### 2.4 Per-account controls

| Control | All accounts | Exactly one account filtered |
|---|---|---|
| Header | "All accounts" + row count | today's header: name, categorized + reconciled balance, reconciled through, Reconcile statement, last synced |
| Add Transaction | modal gains an **Account** picker (feed accounts), required | picker preset to that account |
| Upload CSV | wizard gains an account step first | preset, step skipped |
| Refresh (Plaid) | syncs every Plaid item in the book | syncs that account's item (today) |
| Link Bank Account, Categorize Mode, Transfer review | unchanged (book-wide already) | unchanged |

### 2.5 Editing a row

- **`handleEditTransaction` must send the row's own account.** It sends `selectedAccount.id`, and `PUT feed/{id}/` treats `account` as the row's account — so with no selected account it fails, and with the wrong one it **moves the row**. Fix: `row.account.id`. Same for every other `selectedAccount` read in §0 that acts on a row.
- The modal is unchanged otherwise; it already works per row.

### 2.6 Views and filters across accounts

- Quick Filters (To Review / Reconciled / Uncategorized) and their counts are server-side (§2.1) and span the filtered accounts. With all accounts, the Uncategorized count equals the Inbox badge (both: `has_feed` accounts, no entry, not void) — tested.
- **Voided view** (`view=voided`; "Archived" today) spans the filtered accounts: every voided bank row in the book in one paged list. Restore lives here.

### 2.7 Transfers: both legs in one table

A transfer between two feed accounts is one entry with a row in each account (primary + mirror). Per-account views never showed both; the unified view does.

- **Shown twice, deliberately.** Each row is a fact about its own account and reconciles independently. Collapsing them would break the per-account reading of the table and the per-row reconcile flag.
- **Totals.** With both legs selected, In and Out each include the transfer; Net is unaffected (the legs cancel). The summary strip shows that as is.
- **Transfer link (⇄), match panel "Go to other side", and the flash after Match.** The counterpart may be on another page. New `GET feed/locate/?journal_entry=<id>&account=<counterpart account>&<current filters, sort, page_size>` returns `{id, page}`, computed with `Window(RowNumber(), order_by=<the list's ordering>)` over the same queryset — or `{id, page: null}` when the current filters hide it. Found → go to that page, scroll, flash. Hidden → the existing behaviour: switch the account filter to the counterpart, clear quick filters and dates, view from the row's void state, then locate again.
- **Batch actions with both legs selected:**
  - Bulk category: re-pointing a mirror to a non-feed category is refused (`would_orphan_primary`), so "set category" on a selection that includes mirrors fails. → `BulkEditModal` says "k transfer mirror rows selected — they follow their original" and the request **skips** mirror rows whose primary is also selected; mirrors selected alone are still refused.
  - Void/Restore: legs already move together (`linked_legs`); a selected sibling is skipped as already done.
  - Delete (voided view): removes both legs and the entry already.
  - **Duplicate: skip mirror rows.** Duplicating a mirror creates an uncategorized copy in the counterpart account; categorizing both copies double-counts the transfer. A mirror is not something the bank reported.
  - Bulk move account: a row moved into the account its category already is gets both lines on one account (self-transfer). `_apply_batch_edit` does not catch this. → Refuse it: "A transaction cannot be moved to the account it is categorized to."

### 2.8 Selection across pages

With server paging the client only holds the page on screen, so selection can no longer be "every filtered row in memory".

- **Selection is a map of id → row summary**, kept across page changes; it is what `BatchActionBar` reads (In/Out/Net, reconciled state, which buttons apply), so rows selected on page 1 still count while viewing page 3.
- **Header checkbox = this page.** When the whole page is ticked and `count` exceeds it, a strip offers **"Select all 1,240 matching"** → `GET feed/selection/?<current filters>` returns the summary fields (`id, account_id, inflow, outflow, is_reconciled, is_void, category_id, is_split, is_transfer_mirror, journal_entry_id, reconciled_statement_date`) for every match via `values()` — no serializer, no prefetch. Cap 1,000; above it the strip reads "Narrow the filters to select more than 1,000".
- Cleared when a filter or the view changes (as today); kept across sort and page changes (the set of rows is the same).
- Batch write endpoints get `max_length=1,000` on `ids`; each row is a per-instance save with audit signals, so this bounds the request time.
- Shift-click ranges stay within the page.

### 2.9 Batch bar across accounts

- **Bulk Edit, Void/Restore, Delete, Duplicate, Export, Unreconcile:** unchanged, per row.
- **Reconcile:** no change to what it does. It needs one account for the hand-off URL → enabled only when every selected row is in one account; otherwise disabled with "Select rows from one account to reconcile".
- **Reconciled balance → new** preview: shown only when the selection is in one account, using that account.
- **Export:** CSV of the selected rows. Rows selected on other pages are only summaries, so export fetches them in full first (`GET feed/?ids=…`, same cap); the CSV gains an Account column.
- **Refusals name rows.** Every batch endpoint is all-or-nothing and returns the first error without saying which row. Across accounts and pages that is harder to act on. → `400 {error, refused: [{id, error}]}`; the bar shows "k of n can't …" with **Deselect them**.

---

## 3. Decisions needed

| # | Question | Recommendation |
|---|---|---|
| D1 | ~~Load every row client-side, or page on the server?~~ | **Decided:** one server-side queryset, paged (§2.1). |
| D2 | ~~Default view on arrival: all accounts, or the last account viewed?~~ | **Decided:** all accounts; the URL carries the filter, so a bookmark or Back keeps it. |
| D3 | Voided entries with no bank row have no restore view. | Remove Void from the Transactions edit modal for entries with no bank row (Delete covers manual entries); the feed is the one place for void/restore. |

---

## 4. Phases

**Phase 0 — one void state (§1).** Rename, field removals, data migration with balance assertion, `voiding.py`, model backstops, callers switched, `counted_entries()` simplified, Archived → Voided in the feed, portability v6, `void_consistency`.

**Phase 1 — server.** List endpoint params, sort annotations, `counts`, pagination (§2.1); `feed/selection/`, `feed/locate/`, `?ids=`; id caps; refusals that name rows; self-transfer move refused; mirror skipping in bulk category and duplicate; `EXPLAIN` and index. Old client keeps working throughout (`?account=<id>` with every page still returns the same rows).

**Phase 2 — the unified page.** `LineTable` made presentational, state in `LineApp` + URL, Account column + filter, cards as filter, per-account controls (§2.4), `row.account.id` on edit, page refetch after actions, transfer locate, cross-page selection + "select all matching", batch bar rules (§2.9).

---

## 5. Tests

**Backend:**
- Phase 0: as in §1.6 — invariant after every write path, migration balance-neutral, portability v3 → v4, structure test.
- `GET feed/` without `account`: only `has_feed` accounts; `?account=1,2`.
- **Filter semantics ported from the client:** the cases `e2e/tests/test_bank_feed.py`'s filter matrix pins (to review, reconciled, uncategorized, split counted as categorized, voided view, date range) as a server `TestCase` table, so the move off the client changes no row's membership.
- `counts` ignore quick filters, dates and view; equal the old client counts on the same data.
- Every sort key, including `category` for uncategorized / split / mirror rows, matches the rendered cell; `asc` and `desc`.
- Paging: walking every page returns every row exactly once, for each sort; `page_size` outside the allowed set → 400.
- `assertNumQueries` constant at 10 and 1,000 rows.
- `feed/selection/` returns all matches up to 1,000 and refuses above; `feed/locate/` returns the right page under each sort and `null` when filtered out; `?ids=` capped.
- Another book's rows never returned by any of them (isolation tables).
- `batch_edit` move into the category account → refused; category on primary + mirror → mirror skipped; mirror alone → refused.
- `batch_duplicate` skips mirrors.
- Refusal payload names every refused row; nothing written.
- Uncategorized count (all accounts) == `inbox_count`.

**E2E** (`e2e/tests/test_bank_feed.py`, POM `e2e/pages/bank_feed.py`), contract-first:
- Existing 21 tests keep passing untouched: `click_account_card` becomes "filter to this account", and the filter-matrix tests now exercise the server filters through the same UI.
- Paging: next page shows the next rows; page size change; filter change returns to page 1; URL restores the page on reload.
- Select rows on page 1 and page 2 → bar counts both; "Select all N matching" → bulk edit applies to rows never shown.
- Landing shows rows from two accounts with the Account column; filtering to one hides the column and shows the header balances.
- Select rows in two accounts → Bulk Edit category → both updated, each in its own account.
- Edit a row while viewing all accounts → it stays in its account (guards §2.5).
- Transfer: ⇄ on a leg whose counterpart is on another page goes to that page and flashes it, without changing the filter.
- Reconcile disabled for a two-account selection, enabled for one.
- Add Transaction with all accounts requires an account; CSV upload asks for one.
- Voided view lists voided rows from every account; Restore returns them.

---

## 6. What the build changed

- **`locate/` numbered the wrong set.** Filtering the window-annotated queryset by `pk` puts the `pk` condition in the same `WHERE` the `ROW_NUMBER()` runs over, so every row was "row 1" and every jump landed on page 1. Phase 1's test missed it because its fixture fit on one page of 10. `feed_query.position_of()` now numbers the whole list in an inner query and picks the row in an outer one (raw SQL over `QuerySet.query.sql_with_params()`; Django's QUALIFY emulation moves only window conditions out). The test now spreads the fixture over several pages and checks four sorts.
- **Add Transaction always shows the Account picker**, preset to the filtered account when there is exactly one — rather than hiding it then. One form for both cases, and the account a new row lands in is always visible.
- **CSV upload** with several accounts shown opens an "Upload to which account?" dialog (`upload-account-dialog`) before the wizard, instead of a wizard step; with one account filtered it goes straight to the wizard.
- **Bulk edit with mirrors selected**: the server skips a mirror whose primary is also selected (Phase 1); a mirror selected alone is refused and named, and the batch bar's toast offers **Deselect them**. `BulkEditModal` does not count mirrors up front.
- Default page size **25** (`DEFAULT_PAGE_SIZE` in `assets/javascript/bank_feed/feedQuery.js`); the server's default stays 200 so Categorize Mode's request is unchanged.
