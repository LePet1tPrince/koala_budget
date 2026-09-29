# Transactions page: bulk edit

Goal: the Transactions page gets the Bank Feed's multi-select and batch actions, with each action meaning the right thing for a **journal entry** rather than a **feed row**.

Status: plan. Nothing here is built.

**Out of scope: reconciling and unreconciling.** The Bank Feed bar's Reconcile and Unreconcile are not ported, and this feature adds no reconciliation endpoint or button. Reconciliation stays on the reconcile page and the Bank Feed. Reconciled lines still constrain the actions that *are* ported (the existing guards in `apps.reconciliation.services.guards` refuse edits, deletes and voids that would change a reconciled line); that is unchanged.

---

## 1. Starting point

### 1.1 What the Bank Feed has

`assets/javascript/bank_feed/react/BatchActionBar.jsx` + `BulkEditModal.jsx`, endpoints on `BankFeedViewSet` (`apps/bank_feed/views.py`).

| Action | Endpoint | Unit acted on | Shown when |
|---|---|---|---|
| Bulk Edit (date, category, move account, payee, description) | `PATCH feed/batch_edit/` | `BankTransaction` (+ its entry) | active view |
| Archive | `POST feed/batch_archive/` | `BankTransaction.is_archived` (both transfer legs) | any selected row unarchived and unreconciled |
| Unarchive | `POST feed/batch_unarchive/` | same | any selected row archived |
| Delete (permanent) | `POST feed/batch_delete/` | archived `BankTransaction` + its entry + mirror legs | archived view |
| Reconcile *(not ported)* | none; navigates to `reconcile/<account>/?entries=…` | selection → draft statement ticks | no row reconciled, all categorized |
| Unreconcile *(not ported)* | `POST feed/batch_unreconcile/` | bank-account line `is_reconciled=False` | all selected reconciled |
| Duplicate | `POST feed/batch_duplicate/` | new uncategorized `BankTransaction`, no entry | no row reconciled |
| Export | client-side CSV of selected rows | — | always |
| Summary strip | client | In / Out / Net, reconciled balance → new | always |

Selection (`LineTable.jsx`): checkbox column, header select-all over the filtered rows, shift-click ranges, cleared on view/filter change and after each batch op.

### 1.2 What the Transactions page already has

Batch editing was designed in when the edit modal shipped; it is not wired to a selection.

- `apps/journal/services/simple_edit.py`: `TransactionEdits` (every field `UNSET` by default), `apply_edits_bulk` (plans every entry before writing any, one `transaction.atomic`), `delete_transaction`, `set_status`.
- `TransactionViewSet` (`apps/journal/views.py`): `PATCH transactions/edit/`, `POST transactions/batch_delete/`, `POST transactions/batch_status/` — all take `ids` lists, all-or-nothing, 400 with `{error}`.
- `TransactionEditModal.jsx`: takes a `transactions` array; `shared()` yields `MIXED` for disagreeing fields; `buildUpdates()` sends only changed, non-`MIXED` fields. In batch mode it hides Date and the amounts and shows "Leave blank to keep each one" placeholders.
- `transactions-app.jsx`: `editing` is already an array; `absorb()` patches rows in place or refetches when an edit touched a filtered/sorted column.

Missing: a selection, a batch bar, the data a bar needs per row, and the actions with no journal equivalent yet (duplicate, export).

### 1.3 The structural difference

| | Bank Feed | Transactions |
|---|---|---|
| Row | one `BankTransaction` in one account | one `JournalEntry`, across all accounts |
| Uncategorized rows | yes (no entry) | no (no entry → not on the ledger) |
| Transfer | two rows (primary + mirror), one entry | one row |
| Void / archived | archived view; void entries still listed | both excluded by `counted_entries()` |
| Loading | whole account client-side | 200/page, infinite scroll, server-side filters |
| "Account" | the feed being viewed | `resolve_sides()` home line, per row |

Every implication below follows from one of these rows.

---

## 2. Per-operation implications

### 2.1 Bulk edit — Date

- **Plaid rows.** `simple_edit._check_bank_rules` refuses a date change on a Plaid-sourced row; `BankFeedViewSet._apply_batch_edit` does not. Same transaction, two answers. → Align (§4, D2).
- **Reconciled rows.** `assert_date_change_allowed` refuses moving past the completed statement's date. Per-row, depends on the new date — cannot be known from capabilities up front; only the server can say.
- **Budget month.** `_write` saves the entry before lines and re-saves untouched lines on a date move, so budget links follow. Already correct for batches.
- **Transfers.** `_sync_bank_row` → `sync_transfer` moves the mirror's date. Correct.
- **Filters.** A date edit under an active date range or date filter/sort refetches (`absorb`). Already handled.
- **UI.** Enable the Date field in batch mode. When `k` of `n` rows cannot take a date (Plaid, void), show the field disabled with "k of n selected are dated by your bank" + a "Deselect them" button, instead of silently disabling (today `can` is `every()` with no explanation).

### 2.2 Bulk edit — Payee / Memo

- Low risk: `entry.payee`/`description` + feed row `merchant_name`/`description`, mirror kept in step by `sync_transfer`.
- **Clearing.** In batch mode blank means "keep", so a mixed payee cannot be cleared (Bank Feed has the same gap). → Add an explicit "Clear for all" toggle per field that sends `payee: ""` / `description: ""`. The server already treats `""` as clear.
- **Payee creation.** `_payee()` `get_or_create`s once per entry; fine (same name → same row).
- Bank memo overwritten on feed rows: `similar_transactions` and transfer detection read `description`/`merchant_name`. Bulk-renaming 200 rows changes future suggestions. Acceptable; it is the user's intent.

### 2.3 Bulk edit — Account (move)

Meaning on this page: move the **home line** (`resolve_sides`) to another money account; for a bank-backed row the feed row moves with it.

- **Target must have a feed** if any selected row is bank-backed (`_target_account` → `is_transfer_target`). Otherwise any asset/liability. → Options list: feed accounts only when the selection contains a bank-backed row; all asset/liability otherwise.
- **Reconciled home line** refused (`assert_line_mutable`). Capability `can_edit_account` already covers it.
- **Self-transfer.** Moving a row to the account its category already is (e.g. a Checking → Savings transfer moved to Savings) puts both lines on one account. Today `write_lines` catches it only indirectly (`len(home_lines) != 1` → "This transaction's ledger entry cannot be split automatically.") — correct outcome, wrong message. The Bank Feed's `_apply_batch_edit` does **not** catch it at all (moves the line; entry nets to zero on one account). → Explicit check in `_plan`: "A transaction cannot be moved to the account it is categorized to." Fix the Bank Feed path too.
- **Unusual shapes.** For `normal=False` entries the home side is a guess (`resolve_sides` rule 5). Moving 50 guessed sides is how money silently changes accounts. → Refuse account moves in batch for `normal=False` rows; single-row editing keeps its warning banner.
- **Plaid rows.** Neither page refuses moving a Plaid row, but its `PlaidTransaction` stays mapped to the original account; Plaid `modified` updates then target a row living elsewhere. → D2.
- **Transfers.** Moving the primary moves one side; the mirror stays in the counterpart feed. `sync_transfer` handles it.

### 2.4 Bulk edit — Category

- **Splits.** `_target_legs` refuses a single category on a split unless `remove_split`. → Batch modal: if the selection contains splits, the Category field shows "k split transactions selected" with a checkbox "Replace their splits with this category" (sends `remove_split: true`). Unchecked + category chosen → Save disabled with that reason. Never implied.
- **Category == row's account** refused per row ("cannot be categorized to the account it is in"). With a mixed-account selection this is easy to hit (set "Savings" on rows that include Savings rows). → Needs row-level refusal reporting (§3.3).
- **System accounts** refused (`assert_category_allowed`, `keep_ids` = each entry's own legs). Pickers already exclude them.
- **Transfers created in bulk.** Categorizing to a feed account creates a mirror row per entry in that account's feed. If the other bank already reported those transfers, every one is now double-counted. → Confirmation line: "This adds k rows to Savings' Inbox." After save, if `transfers/` suggestions exist for the target account, the toast links to transfer review.
- **Transfers removed in bulk.** Re-categorizing a transfer to an expense deletes the mirror. If the mirror's line is reconciled, `write_lines` refuses (`assert_line_removable`, "The other side of this transfer is already reconciled…"). → Capability must reflect it (§3.2).
- **Budget actuals / Unassigned** change immediately; the Unassigned pill re-reads after any non-GET (`unassigned-pill.js`). Nothing to add.

### 2.5 Bulk edit — Amount / splits

Not offered in batch. Amounts and legs are per-transaction; the Bank Feed has no bulk amount either. Keep hidden.

### 2.6 Delete

`delete_transaction`: a bank-backed entry is **de-categorized** (entry deleted, feed row back to the Inbox as uncategorized, mirrors deleted); anything else is deleted outright.

- **Mixed outcome.** A select-all over YNAB-imported history would push hundreds of rows into the Inbox. → Confirm dialog states both counts: "k will be deleted. m came from your bank and go back to the Inbox as uncategorized." Needs a per-row `bank_backed` flag (§3.2).
- **Reconciled** — `assert_entry_removable` refuses if **any** line is reconciled (including the other side of a transfer). Capability `can_delete` today checks only the home line → modal offers Delete, server refuses. → Fix capability (§3.2).
- **Bank Feed's permanent delete** (deletes the `BankTransaction`) is not ported. The ledger page does not destroy what the bank reported.
- No undo. Audit: per-line `AuditLog` rows fire; add `BULK_DELETE` with `scope: transactions` (exists for n > 1).

### 2.7 Void / Restore (the ledger's Archive)

The Bank Feed's Archive has no direct counterpart: archived entries are already invisible here, so **Unarchive is unreachable** and **Archive would duplicate Void** (both remove the entry from every balance).

- **Void is the batch "exclude" action.** `set_status`, refused for any reconciled line (`assert_entry_voidable`).
- **Bank-backed rows.** Voiding leaves the feed row linked to a void entry; the feed does not filter void entries, so the Inbox shows it as categorized and counted-looking while it counts toward nothing. → D1.
- **List behaviour.** `rows_for` returns voided rows and `absorb` patches them in place, so voided rows stay on screen with a Void badge until the next refetch. Keep that (it is what makes Restore reachable) and put **Undo** on the toast (`Toast` has an `action` slot) → `batch_status {status: posted}`.
- **Audit.** `batch_status` logs no bulk event. Add `BULK_VOID` / `BULK_RESTORE` (audit migration for the choices).

### 2.8 Reconcile / Unreconcile

Not ported (see scope note). The bar has no Reconcile or Unreconcile button, and no hand-off to `reconcile/<account>/`. Reconciled rows appear in a selection like any other; the guards decide what each ported action may do to them (§2.1, §2.3, §2.4, §2.6, §2.7).

### 2.9 Duplicate

Bank Feed: copies the `BankTransaction` **uncategorized, without an entry** (lands in the Inbox). A ledger duplicate must copy the **entry**.

- New `simple_edit.duplicate_transaction(entry, *, book)`: new `JournalEntry` (same date, payee, description, status `posted`, `SOURCE_MANUAL`), lines via `write_lines` (same account, legs, total). Copies are never reconciled or cleared, `reconciliation=None`.
- **Bank-backed original** → also create a `BankTransaction` (`SOURCE_MANUAL`, `raw={"duplicated_from_entry": id}`) in the home account linked to the copy, then `sync_transfer`. Otherwise the copy moves the feed account's balance with no row in its feed, and the feed and ledger disagree.
- **Transfer without a feed row** → plain copy; mirrors only follow feed rows.
- **Split** → all legs copied; a split's transfer legs get mirrors via `sync_transfer`.
- **Refused:** `SOURCE_RECONCILIATION` entries (system adjustments), void entries, `UnsupportedEntry` shapes.
- **Effect:** balances, budget actuals and Unassigned move immediately. Toast: "k duplicated" + action "Edit copies" (opens the batch modal on the new ids). Single-row duplicate opens the editor on the copy.
- Audit: `BULK_DUPLICATE` with `scope: transactions`.

### 2.10 Export

- Client-side CSV of the selected **loaded** rows (same as the Bank Feed). Columns: Date, Payee, Memo, Account, Category, Amount (signed from the account's side: out negative), Source, Status. A split exports one line per leg with the transaction's shared columns repeated.
- Needs home account + signed legs per row (§3.2).
- "Export everything matching the current filters" is the existing server export (`reports:export_transactions`) extended with the page's filter params — separate change, not in this plan.

### 2.11 Selection summary strip

- In / Out / Net only mean something relative to one account (a transfer is both). → Show `k selected · Total $X` always; show In / Out / Net only when every selected row has the same home account, computed from that account's side.
- Drop the "reconciled balance → new" preview: there is no reconcile action here.

---

## 3. Design

### 3.1 Selection

- Checkbox column first (`stopPropagation`, so the row click still opens the editor). Header checkbox = all **loaded** rows, indeterminate when partial. Shift-click ranges. Selection survives load-more.
- Cleared when search, date range, column filters or sort change (the selected rows may no longer be the ones on screen) and after every batch action.
- Deleted rows leave the selection; refetched rows no longer present leave it.
- Extract the selection logic from `LineTable.jsx` into `common/useRowSelection.js` (ids, toggle, range, select-all, clear) and use it from both tables.
- Cap: `MAX_BATCH_IDS = 500` on every transactions id serializer (`max_length`). Above it, the bar's actions disable with "Select at most 500".
- "Select all k matching" (beyond loaded rows) is Phase 4: the client sends the filter params, the server resolves ids. Not needed for the first ship.

### 3.2 Row data

The bar decides availability without a round trip per row, and the batch modal needs account/category ids. Extend `TransactionRowSerializer` with one block computed from `resolve_sides`:

```
edit: {
  editable,                      # False when resolve_sides raises UnsupportedEntry
  account: {id, name},           # home line
  category_id,                   # null for a split
  normal,                        # resolve_sides().normal
  bank_backed, bank_source,      # non-mirror feed row, its source
  capabilities: {...}            # same dict as TransactionDetailSerializer
}
```

- Queryset: add `lines__account__account_group` and `bank_feed_transactions` to the list prefetch — two extra queries per page, not per row.
- **One capability function.** Move `get_capabilities` into `simple_edit.capabilities_for(entry, sides)` and use it from both serializers, so the bar, the modal and the writer read the same predicates. Correct it to match the guards:
  - `can_delete`, `can_void`: no reconciled line **anywhere** on the entry (today: home line only — diverges from `assert_entry_removable`).
  - `can_edit_category`: false when a non-home line is reconciled (write_lines refuses dropping it).
  - `can_edit_account`: also false for `normal=False` in batch (§2.3).
- The single-row editor still fetches `transactions/{id}/` (legs, history). The batch modal opens straight from row data.

### 3.3 Refusals that name rows

Today the first failing entry aborts the batch with one message and no id, so the user cannot tell which of 80 rows to deselect.

- `_plan` failures are collected, not raised one by one: `apply_edits_bulk` plans every entry, gathers `(entry_id, message)` pairs, and raises `BatchRefused(failures)` if any.
- Response: `400 {error: "<first message>", refused: [{id, error}], refused_count}`. Same shape for `batch_delete`, `batch_status`, `batch_duplicate`.
- Client: error line in the modal/bar reads "k of n can't take this change: <message>" with **Deselect them** (removes those ids and keeps the modal open) and highlights those rows.
- Still all-or-nothing; nothing is written unless every row passes.

### 3.4 Bar

- Extract the chrome of `BatchActionBar.jsx` (fixed bottom surface, summary strip, action row, clear ×) into `common/SelectionBar.jsx`. `BatchActionBar` keeps its buttons and props; its e2e tests address buttons by accessible name and must pass untouched.
- New `transactions/TransactionsBatchBar.jsx`: Edit · Duplicate · Void / Restore · Delete · Export · ×. No Reconcile / Unreconcile.
- Availability from `edit.capabilities` across the selection: a button is enabled when **any** row can take the action, and the confirm step says how many will be refused; the server refuses the batch until they are deselected (§3.3).

### 3.5 Modal

Changes to `TransactionEditModal.jsx` in batch mode:

- Date field shown (§2.1).
- Payee / Memo "Clear for all" toggles (§2.2).
- Account options narrowed by the selection (§2.3).
- Split checkbox under Category (§2.4).
- Footer Delete / Void hidden in batch (the bar owns them; one confirm flow per action).
- Error area renders `refused` (§3.3).

### 3.6 Endpoints

| Endpoint | New / changed |
|---|---|
| `GET transactions/` | rows gain `edit` block |
| `PATCH transactions/edit/` | collected refusals; `max_length` |
| `POST transactions/batch_delete/` | collected refusals |
| `POST transactions/batch_status/` | collected refusals; `BULK_VOID`/`BULK_RESTORE`; D1 |
| `POST transactions/batch_duplicate/` | new → `{results: rows}` |

The new endpoint goes into `apps/books/tests/test_isolation.py` (`WRITES`). `transactionsApi.js` gains `duplicate`.

---

## 4. Decisions needed

| # | Question | Recommendation |
|---|---|---|
| D1 | Voiding a bank-backed transaction leaves its feed row showing as categorized, while the entry counts toward nothing. | Void also **archives** the entry's feed rows (primary + mirrors); Restore unarchives them. The feed's transfer `resolve` already voids + archives together. Applies to single-row void too. |
| D2 | Plaid rows: Transactions refuses a date change, the Bank Feed's `batch_edit` allows it; neither refuses an account move. | Refuse both on both pages: Plaid owns the date, amount and account of a Plaid row. Put the rule in `_check_bank_rules` and call it from `batch_edit`. |
| D3 | Select-all scope. | Loaded rows only for Phases 1–3; "select all matching" in Phase 4 if asked for. |

---

## 5. Phases

**Phase 1 — rules and row data (backend only).**
`capabilities_for` shared + corrected; `edit` block on rows; collected refusals (`BatchRefused`); self-transfer check (both pages); D1, D2; `MAX_BATCH_IDS`; audit event types + migration. Tests first for each divergence (they fail on `develop`).

**Phase 2 — selection, bar, edit, delete, void, export.**
`useRowSelection`, `SelectionBar` extraction, `TransactionsBatchBar`, modal batch changes, summary strip, client CSV.

**Phase 3 — duplicate.**
`duplicate_transaction`, `batch_duplicate` endpoint, bar button.

**Phase 4 (optional) — select all matching; server export of current filters.**

---

## 6. Tests

**Backend** (`apps/journal/tests/`, `TestCase` + `setUpTestData`):

- Each action: happy path on 2+ entries; all-or-nothing with one refusable row (nothing written; `refused` names it); another book's id → refused as missing.
- Date: Plaid row refused (both endpoints after D2); reconciled past statement refused; budget link follows the month for every line.
- Account: self-transfer refused (both pages); bank-backed → non-feed target refused; `normal=False` refused in batch.
- Category: split without `remove_split` refused, with it collapsed; to-feed-account creates one mirror per entry; off a transfer with a reconciled counterpart refused.
- Delete: bank-backed → feed row uncategorized, mirrors gone; manual → entry gone; any reconciled line → refused.
- Void/Restore: D1 archive/unarchive of feed rows; reconciled refused.
- Duplicate: plain, split, bank-backed (new manual feed row + mirror), reconciliation adjustment refused; copy unreconciled.
- Capabilities equal the guards: for each fixture shape, `capabilities_for` false ⇔ the writer refuses.
- Isolation tables updated.

**E2E** (`e2e/tests/test_transactions.py`, POM `e2e/pages/transactions.py`), written against Phase 1 before the UI lands where possible:

- Select rows → bar shows count; header checkbox indeterminate; shift-click range; filter change clears selection.
- Bulk category on 3 rows → rows patched in place.
- Mixed selection with a Plaid row → Date field explains and "Deselect them" works.
- Delete mixed → confirm shows both counts; feed row appears in the Inbox uncategorized.
- Void → Undo restores.
- Selecting reconciled rows shows no Reconcile / Unreconcile button.
- Export → downloaded CSV has one line per split leg.
- Existing `test_bank_feed.py` batch-bar tests pass untouched after the `SelectionBar` extraction.
