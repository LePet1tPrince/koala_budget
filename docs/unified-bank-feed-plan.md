# Unified bank feed

Goal: the Inbox (`/a/{team}/{book}/bankfeed/`) shows **one table of every bank-feed account's rows**, with an Account column. Bulk editing across accounts then comes from the feed's existing batch bar and endpoints, which already work per row.

Supersedes the earlier "bulk edit on the Transactions page" plan: editing the ledger directly is dropped. The Transactions page is unchanged.

Status: plan. Nothing here is built.

---

## 0. What exists

**Page.** `LineApp.jsx` shows the account cards (`AccountGrid`) as a picker; choosing one loads that account's rows and renders `LineTable.jsx`. Nothing shows until an account is chosen.

**Rows.** `GET bankfeed/api/feed/?account=<id>` (`BankFeedViewSet.list`, page size 200). The client follows every `next` page, then filters, counts, sorts and paginates in memory. `account` is already optional server-side: without it the endpoint returns every `BankTransaction` in the book. Each row already carries `account {id, name, institution}`.

**Batch.** `BatchActionBar.jsx` + `BulkEditModal.jsx` over `batch_edit`, `batch_archive`, `batch_unarchive`, `batch_delete`, `batch_duplicate`, `batch_unreconcile` — all take row ids, none take an account. Reconcile navigates to `reconcile/<selectedAccount>/?entries=…`.

**Everything that reads `selectedAccount`** (the list the pivot has to rehome):

| Where | Use |
|---|---|
| `LineApp.loadLines` | `account` query param |
| `LineApp.handleEditTransaction` | sends `account: selectedAccount.id` to `PUT feed/{id}/` |
| `LineApp.handleAddLine` | `account` of the new row |
| `LineApp.handleRefresh` | which Plaid item to sync |
| `LineApp` header | "Lines for X", categorized + reconciled balance, "reconciled through", Reconcile statement link, Plaid last-synced |
| `LineApp.handleBatchReconcile` | reconcile URL |
| `LineApp.handleOpenTransferLeg` | switches to the counterpart account |
| `CSVUploadWizard` | target account of the upload |
| `BatchActionBar` | reconciled balance → new preview |
| `LineTable` | renders nothing without it |

---

## 1. Phase 0 — one void state for a transaction and its bank rows

Ships first, on its own. The unified feed (§2) is built on the renamed field and its Voided view is the restore view.

### 1.1 The problem today

Two independent flags mean "doesn't count":

| | `JournalEntry.status == "void"` | `BankTransaction.is_archived` |
|---|---|---|
| Set by | Transactions page Void (edit modal), `journal-entries/{id}/void_entry/`, reconciliation undo (adjustment entry), transfer review "resolve" | Bank Feed Archive, reconciliation undo, transfer review "resolve" |
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
- Guard (unchanged rule, now applied to both): refused if any line on the entry is reconciled (`assert_entry_voidable`). All-or-nothing; the refusal names the rows (§2.8).
- Per-instance `save()` on entries (so `AuditLog` records the status change); rows in the same `transaction.atomic`.
- Callers switched to it: `simple_edit.set_status`, `JournalEntryViewSet.void_entry`, `BankFeedViewSet.batch_archive`/`batch_unarchive`, `transfer_resolve`, `reconciliation.services.session.undo`.

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
- Transfer review "resolve" becomes one `void()` call.
- Audit: new `AuditEvent` types `BULK_VOID`/`BULK_RESTORE` (audit migration); `BULK_ARCHIVE`/`BULK_UNARCHIVE` stay as choices for history.
- Portability format **v4**: `feed_is_archived`/`feed_archived_at` → `feed_is_void`/`feed_voided_at`; `entry_is_archived` and the line `is_archived` column dropped. `upgrade_3_to_4` renames the columns and applies 1.5's rules to the imported rows, so an old archive lands consistent; the manifest checksums still match because the rules are balance-neutral.
- Tests: the invariant holds after every write path (categorize, decategorize, split, transfer mirror create/move/remove, void, restore, resolve, reconciliation undo, CSV/Plaid/YNAB/portability import).
- **Restore view.** The unified feed's Voided view (§2.6) lists every voided bank row in the book, categorized or not; Restore there calls `voiding.restore`. Entries with **no** bank row (voided from the Transactions edit modal: manual entries, opening balances, tracking-account history) are in no feed → D3.

---

## 2. The unified table

### 2.1 Rows

- **All feed accounts, one list.** `GET feed/` with no `account` returns rows for accounts with `has_feed=False` too (accounts hidden from the Inbox by the accounts board checkbox keep their rows). → Server: without `account`, filter `account__has_feed=True`. With `account`, unchanged.
- **Multi-account filter.** `?account=1,2` (comma list). Single id keeps working, so the nav's `?account=<id>` links and the account page's "Open in Inbox" still land filtered.
- **Ordering.** `-posted_date, -created_at`, then `account` sort order, then `pk` — deterministic across pages.

### 2.2 Loading — the measured risk

The client loads every page before showing anything. Per account that was hundreds to a few thousand rows; the YNAB sample book has **6,860** feed rows across its accounts (~35 pages).

- Phase 1 first step: time `GET feed/` for all pages on the YNAB sample (server time per page, total wall time, JS heap).
- Change loading regardless: render page 1 as soon as it arrives, fetch pages 2..N **in parallel** (the first response's `count` gives N), show "Loading 1,200 of 6,860…" in the toolbar, and keep counts/filters marked provisional until done.
- **Budget:** first rows < 1 s, full load < 3 s on the sample. If missed → D1 (move filtering/sorting/counting server-side, as the Transactions page did). Not built speculatively: it rewrites the filter, count and selection logic the e2e suite pins.
- **Reload after actions.** Every batch action calls `loadLines()` — today one account, after the pivot the whole book. Replace with a targeted refresh: new `GET feed/?ids=…` (cap 500) re-reads the affected rows plus their transfer siblings (`linked_legs`), patched into state; deletes drop ids; duplicates append. Full reload only for CSV upload, Plaid refresh and transfer-review resolve.

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

- Quick Filters (To Review / Reconciled / Uncategorized) and their counts span the filtered accounts. With all accounts, the Uncategorized count equals the Inbox badge (both: `has_feed` accounts, no entry, not void) — tested.
- **Voided view** (after Phase 0; "Archived" today) spans the filtered accounts: every voided bank row in the book in one list. Restore lives here.
- Date range, sort and paging unchanged.

### 2.7 Transfers: both legs in one table

A transfer between two feed accounts is one entry with a row in each account (primary + mirror). Per-account views never showed both; the unified view does.

- **Shown twice, deliberately.** Each row is a fact about its own account and reconciles independently. Collapsing them would break the per-account reading of the table and the per-row reconcile flag.
- **Totals.** With both legs selected, In and Out each include the transfer; Net is unaffected (the legs cancel). The summary strip shows that as is.
- **Transfer link (⇄).** If the counterpart row is under the current filters: scroll and flash it in place, no account switch. Otherwise: add the counterpart's account to the filter, then the existing clear-filters → page → flash logic.
- **Batch actions with both legs selected:**
  - Bulk category: re-pointing a mirror to a non-feed category is refused (`would_orphan_primary`), so "set category" on a selection that includes mirrors fails. → `BulkEditModal` says "k transfer mirror rows selected — they follow their original" and the request **skips** mirror rows whose primary is also selected; mirrors selected alone are still refused.
  - Void/Restore: legs already move together (`linked_legs`); a selected sibling is skipped as already done.
  - Delete (voided view): removes both legs and the entry already.
  - **Duplicate: skip mirror rows.** Duplicating a mirror creates an uncategorized copy in the counterpart account; categorizing both copies double-counts the transfer. A mirror is not something the bank reported.
  - Bulk move account: a row moved into the account its category already is gets both lines on one account (self-transfer). `_apply_batch_edit` does not catch this. → Refuse it: "A transaction cannot be moved to the account it is categorized to."

### 2.8 Batch bar across accounts

- **Bulk Edit, Void/Restore, Delete, Duplicate, Export, Unreconcile:** unchanged, per row.
- **Reconcile:** no change to what it does. It needs one account for the hand-off URL → enabled only when every selected row is in one account; otherwise disabled with "Select rows from one account to reconcile".
- **Reconciled balance → new** preview: shown only when the selection is in one account, using that account.
- **Export:** gains an Account column.
- **Refusals name rows.** Every batch endpoint is all-or-nothing and returns the first error without saying which row. Across accounts that is harder to act on. → `400 {error, refused: [{id, error}]}`; the bar shows "k of n can't …" with **Deselect them**.

---

## 3. Decisions needed

| # | Question | Recommendation |
|---|---|---|
| D1 | Full load misses the budget on the YNAB sample. | Then move filtering, sorting, counts and paging server-side (the Transactions page pattern) and keep the client contract; decide only after measuring. |
| D2 | Default view on arrival: all accounts, or the last account viewed? | All accounts. Remember the filter per book in `localStorage` only if users ask. |
| D3 | Voided entries with no bank row have no restore view. | Remove Void from the Transactions edit modal for entries with no bank row (Delete covers manual entries); the feed is the one place for void/restore. |

---

## 4. Phases

**Phase 0 — one void state (§1).** Rename, field removals, data migration with balance assertion, `voiding.py`, model backstops, callers switched, `counted_entries()` simplified, Archived → Voided in the feed, portability v4, `void_consistency`.

**Phase 1 — server + loading.** `has_feed` filter and multi-id `account`; deterministic ordering; `?ids=` refresh; refusals that name rows; self-transfer move refused; mirror skipping in bulk category and duplicate. Measure §2.2 → settles D1.

**Phase 2 — the unified page.** Account column + filter, cards as filter, URL state, per-account controls (§2.4), `row.account.id` on edit, parallel loading, targeted refresh, transfer link in place, batch bar rules (§2.8).

**Phase 3 (only if D1 says so) — server-side filtering.**

---

## 5. Tests

**Backend:**
- Phase 0: as in §1.6 — invariant after every write path, migration balance-neutral, portability v3 → v4, structure test.
- `GET feed/` without `account`: only `has_feed` accounts; `?account=1,2`; ordering stable across pages; `?ids=` returns those rows and their siblings; another book's ids never returned (isolation tables).
- `batch_edit` move into the category account → refused; category on primary + mirror → mirror skipped; mirror alone → refused.
- `batch_duplicate` skips mirrors.
- Refusal payload names every refused row; nothing written.
- Uncategorized count (all accounts) == `inbox_count`.

**E2E** (`e2e/tests/test_bank_feed.py`, POM `e2e/pages/bank_feed.py`), contract-first:
- Existing 21 tests keep passing: `click_account_card` becomes "filter to this account", which is what they rely on.
- Landing shows rows from two accounts with the Account column; filtering to one hides the column and shows the header balances.
- Select rows in two accounts → Bulk Edit category → both updated, each in its own account.
- Edit a row while viewing all accounts → it stays in its account (guards §2.5).
- Transfer: both legs visible; ⇄ flashes the other leg without changing the filter.
- Reconcile disabled for a two-account selection, enabled for one.
- Add Transaction with all accounts requires an account; CSV upload asks for one.
- Voided view lists voided rows from every account; Restore returns them.
