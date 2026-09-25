# YNAB import → bank feed rows

**Goal:** every YNAB register row on a bank-type account arrives as a `BankTransaction`
in that account's Inbox feed, linked to the journal entry the import already writes.
Categorized rows arrive categorized; rows YNAB never categorized arrive uncategorized,
waiting in the Inbox. **Nothing imported is reconciled** — the user reconciles every
account by hand.

**Supersedes** in `docs/ynab-import-plan.md`: **D12** ("straight to the journal, no
`BankTransaction` rows") and **D9** (carry YNAB's reconciled flag onto the bank line).

All figures are measured against `docs/reference/… Register.csv` (7,572 rows,
36 accounts: 22 on-budget, 14 tracking).

---

## 1. Decisions

| # | Question | Decision |
|---|---|---|
| F1 | Transfers between two feed accounts | The feed row is written **once**, on one leg. The other side appears through the app's own transfer-mirror rule, exactly as if the user had categorized it in the Inbox (§3.2). |
| F2 | Split containing a transfer | One feed row, on the account that holds the split. The transfer leg's counterpart appears through the same mirror rule — which skipped splits, so the rule is extended for every book, not just imports (§3.3). |
| F3 | Reconciliation state | **Never reconcile imported lines.** `is_reconciled=False` on every line, feed row and opening balance. No `Reconciliation` records. |
| F4 | Default "Show in Inbox" per account | On-budget or liability, **off** when the closing balance is 0 and there is no row in the 12 months before the export. Toggle per account on the wizard's accounts screen. |
| F5 | Future-dated rows | Feed rows like any other. |
| F6 | Deduplication | Every real transfer is already one entry, so anything the transfer detector would pair across the imported rows is a coincidence. After the rows are written, every such pair is recorded as a `TransferMatchDismissal` ("not a transfer"), repeating until the detector finds nothing (§4 B1). No per-account cut-off or Plaid/CSV matcher (§4 B2). |
| F7 | Statement records for "reconciled through" | Not built (follows from F3). |

---

## 2. What changes for the user

| Today | After |
|---|---|
| Inbox empty after import | Each feed account shows its full YNAB history, categorized |
| YNAB-reconciled lines arrive locked | Every imported line is unreconciled, ready for manual statement reconciliation |
| Categorize-mode suggestions (history = categorized feed rows) have nothing to learn from | Suggestions work on day one from the last 2,000 imported rows |
| YNAB-uncategorized rows post to `Uncategorized Expense/Income` | They sit in the Inbox, uncategorized |

---

## 3. Design

### 3.1 Row → feed row rules

A feed row is written only on an account with `has_feed=True` (after the F4 default
and the user's toggle).

| Register row | Sample (feed accounts, F4 defaults) | Feed rows |
|---|---|---|
| Categorized row / income inflow | 5,472 | 1 |
| Transfer, feed ↔ feed | 472 pairs | 1 primary + 1 mirror from the mirror rule (§3.2) |
| Transfer, feed ↔ non-feed | 350 | 1, on the feed side; no mirror (the rule only mirrors into feed accounts) |
| Split | ~83 groups | 1, for the total, on the split's account |
| Split with a transfer leg to a feed account | 3 | the split's row + 1 mirror per such leg (§3.3) |
| YNAB reconciliation adjustment (`RECONCILIATION_PAYEES`) | 5 | 1 (posts to equity, as today) |
| Uncategorized, non-transfer | 3 | 1, `journal_entry=None`; **no journal entry written** |
| Future-dated (after export date) | 4 | as its row type (F5) |
| `Starting Balance` | — | 0 — opening balances are not bank transactions |
| Any row on a non-feed account | — | 0 |

Sample total: **~6,850 feed rows on 13 accounts**, 3 in the Inbox queue.
F4 turns off 9 on-budget accounts by default: `BBC A/R`, `Bender Books (TG)`,
`Glebeholme Expenses`, `Short-Term Savings (EQ)`, `Tax Payments (EQ)`,
`Timmy's Invest (WS)`, `Timmy's Trade (WS)`, `Viv's Invest (WS)`, `WS Cash`.
`Cash` and `Reconcile account` stay on (active, non-zero history); the user can
toggle them off.

### Field mapping

| `BankTransaction` field | Value |
|---|---|
| `amount` | `-row.net` (feed convention: positive = outflow) |
| `posted_date` | `row.entry_date` |
| `description` | `_description(row)` truncated to 255 |
| `merchant_name` | `_payee(row)` (None for transfers, as today) |
| `source` | new `SOURCE_YNAB = "ynab"` (choices-only migration; `journal_source` → `SOURCE_IMPORT`) |
| `raw` | `{"ynab": {"index", "account", "payee", "category", "memo", "cleared"}}` — provenance |
| `is_transfer_mirror` | False on every row the import writes itself; True only on rows the mirror rule produces |
| `journal_entry` | the entry built from the row; None for uncategorized rows |

`JournalLine.is_reconciled=False` everywhere (F3). `JournalLine.is_cleared` keeps
YNAB's `Cleared` value: nothing reads it for balances or reconciliation.

`FEED_SOURCES` in `apps/portability/services/schema.py` derives from
`SOURCE_CHOICES`, so the new value exports and imports with no format bump.

### 3.2 F1 — one feed row per transfer, the mirror from the app's rule

`transfer_mirror.sync_transfer()` is what makes a transfer show up in the
counterpart's feed. The import must produce exactly its output, but through
`bulk_create` rather than ~470 individual `save()`s. So:

- Factor the row-building half of `sync_transfer` into a pure
  `mirror_rows_for(tx, entry_lines) -> list[BankTransaction]` (unsaved).
  `sync_transfer` keeps its create/move/delete logic on top of it; the import calls
  `mirror_rows_for` on each primary and bulk-inserts the result.
- **Primary** = the leg on a feed account; when both are, the first in file order.
  The mirror copies the primary's `description`/`merchant_name`/`posted_date` (that
  is the rule), so the other leg's own YNAB memo survives only in the entry's
  description when the primary had none.
- Test: after import, `sync_transfer(primary)` on every imported transfer is a
  no-op (no row created, moved, changed or deleted). That is the definition of
  "created correctly".

### 3.3 F2 — splits with a transfer leg

Sample case, `Viv's Paycheck (TD)` 28-05-2026: one $500 outflow split into Car $420
+ Transfer to `Cash` $80; `Cash` has the matching +$80.

End state: `Viv's Paycheck (TD)` shows one $500 split row; `Cash` shows +$80
categorized to `Viv's Paycheck (TD)`, appearing automatically.

Today `sync_transfer` returns early for any entry with more than two lines, so the
`Cash` row would never appear — in the import *or* when a user builds the same
split in the Inbox. Extending the rule (benefits both):

- `mirror_rows_for`: for a split, one mirror per leg whose account
  `is_transfer_target`, amount = that leg's line.
- `sync_transfer`: for a split, create/update/delete those mirrors to match the
  current legs; called from `apply_splits` after every split edit (leg removed →
  mirror deleted; leg re-amounted → mirror follows).
- `bank_transaction_to_feed_row`: a mirror whose entry is a split renders as a
  plain row — category = the primary's account, amount = its own line — not as the
  split's legs.
- `would_orphan_primary`: currently returns False for any split. A split's mirror
  must refuse re-categorization and split-editing ("edit the original
  transaction instead"), or `apply_splits` would treat the mirror's account as
  the bank line.
- `linked_legs` already finds rows by entry, so archive/delete of the split takes
  its mirrors with it; `find_transfer_candidates` already excludes mirrors.

### 3.4 Phases

**Phase 1 — Mirror rule** (`apps/bank_feed/services/transfer_mirror.py`,
`splits.py`, `serializers.py`): `mirror_rows_for`, split mirrors, rendering,
orphan guard. Tests on in-app categorization and split edits, independent of YNAB.

**Phase 2 — Build (pure)** (`apps/ynab_import/services/build.py`, `reconcile.py`):
- `PlannedFeedRow`; `PlannedEntry.feed` (primary rows only — mirrors are derived at
  apply time); `ImportPlan.inbox_rows` for uncategorized rows with no entry.
- `AccountChoice.has_feed` (payload `accounts[name].has_feed`, validated in
  `parse_choices`), default per F4.
- `is_reconciled=False` on every `PlannedLine`; drop D9's carry.
- Gate: `check_balances` and `_net_worth(plan)` subtract `inbox_rows` per account,
  so the reconciliation stays exact. `assert_sound`: every consumed row reaches an
  entry or `inbox_rows`.
- `_stats`: `feed_rows`, `inbox_rows`, `inbox_amount`.

**Phase 3 — Apply + wizard** (`apply.py`, `assets/javascript/ynab_import/`):
- Per batch: entries → lines → primary feed rows → `mirror_rows_for` → bulk insert.
  Then `inbox_rows`. `ApplyResult.feed_rows`; `YNAB_IMPORT` audit metadata.
- `can_import`: also refuse a book with any `BankTransaction` (an uploaded,
  uncategorized CSV passes today and would be duplicated).
- Accounts screen: "Show in Inbox" toggle. Summary: "N transactions in your Inbox
  feeds, M waiting to be categorized ($X — these accounts' balances reach YNAB's
  once they are). Nothing is reconciled; reconcile each account from its statement."
- Onboarding: unchanged — see §5.

**Phase 4 — Dismiss look-alike transfers** (F6): `transfer_detection.dismiss_all_candidates(book)` at the end of the apply.

**Tests:** every §3.1 rule; the gate with inbox rows; F4 defaults on the sample
(the 9 accounts above); no imported line reconciled; `sync_transfer` no-op
invariant; F2 end state on the three sample splits; isolation (nothing in a sibling
book); E2E: import → account card shows rows → transfer appears in both feeds.

---

## 4. Blockers and risks

### B1 — Transfer review flags historical coincidences · resolved (F6)

`find_transfer_candidates()` pairs any two non-mirror feed rows on different
accounts with equal magnitude, opposite direction, within 5 days, that don't share
an entry — categorized rows included. F1 stops a real transfer being flagged (its
two rows share an entry). It does not stop unrelated rows pairing. **Simulated on the
sample with F1 + F4: ~53 suggestions**, each offering "Resolve", which **voids** one
side's journal entry. The function also loads every feed row into memory per call
(~6,400 on the sample).

Resolved by F6: the apply dismisses every pair the detector finds, pass after pass
(the matching is greedy one-to-one, so dismissing one pair can free a row for its
next-closest match). Measured on the sample: 57 pairs, ~1.5 s.

### B2 — Linking a bank or uploading a CSV after import · not built (F6)

Separate from F1: this is the same *bank transaction* arriving from two sources.

- Plaid (`plaid/tasks.py::process_added_transaction`) dedupes only on
  `plaid_transaction_id`. The first sync returns Plaid's history window (90 days by
  default; the app sets no `days_requested`), all already imported from YNAB → the
  same transactions again, uncategorized. Categorizing them double-counts.
- CSV (`csv_upload.py`) flags a duplicate only on account + date + amount +
  description `iexact`; YNAB's cleaned payee never equals the bank's raw text.

Minimum fix (what D12 proposed and was never built): record each account's last
imported date; Plaid rows on or before it are skipped, CSV rows on or before it are
pre-flagged as duplicates. Fuller fix: match on account + amount + date ±3 days
against unmatched `source=ynab` rows.

### B3 — Reconciling five years by hand

Every imported line is unreconciled (F3):
- The reconcile workspace lists every candidate line up to statement date + 7 days,
  **unpaginated** (`candidates.visible_lines`). The first statement on
  `Credit Card (TG)` lists ~2,700 lines; `diagnose()` runs over all of them. Needs a
  measure, and likely pagination or virtualization.
- `tick_through(date)` makes a catch-up statement one click; month-by-month
  reconciliation of the history is ~58 statements per account.
- Opening balances are unreconciled too and must be ticked in each account's first
  statement.
- Every imported row shows under the feed's "To Review" filter, and the monthly
  review's step 1 reports every historical month as unreconciled.

### B4 — Split mirrors are a change to live feed behaviour

§3.3 changes `sync_transfer`, `apply_splits`, `would_orphan_primary` and the feed
row renderer for all books, not just imports. Phase 1 ships and is tested on its own.

### Non-blocking

- **Volume:** ~6,850 inserts beside ~13,300 lines, same batch loop.
  `ANALYZED_MODELS` already analyzes `BankTransaction`.
- **Portability:** new `source` value flows via `FEED_SOURCES`; `wipe_book` cascades
  `BankTransaction` through `Account`. Add a round-trip test on the sample.
- **Audit:** `bulk_create` skips signals by design; the one `YNAB_IMPORT` event is
  the record.
- **Future-dated rows (F5):** an account card's latest-transaction date can read
  later than today.

---

## 5. What was built

Measured on the sample export: **6,860 feed rows** (8 uncategorized, in the Inbox),
6,615 journal entries, 13,319 lines, 104 accounts (no `Uncategorized Expense/Income`:
the rows that needed them wait in the Inbox), 57 look-alike pairs dismissed, no line
reconciled. The whole apply takes ~3.7 s.

- **Mirror rule** (`apps/bank_feed/services/transfer_mirror.py`): `mirror_rows_for(primary, lines)`
  is the pure half — one mirror per line on another feed account, for that line's
  amount. `sync_transfer` uses it for splits (`_sync_split_mirrors`: create, resize,
  drop to match the legs) and cleans up stray mirrors in the two-line case (a split
  collapsed to a transfer used to keep all of them). `is_split_mirror()` refuses
  every edit of a split's mirror in `update` and `batch_edit`
  (`SPLIT_MIRROR_ERROR`); `bank_transaction_to_feed_row` renders it as a plain row
  whose category is the split's account (the feed list prefetches
  `journal_entry__bank_feed_transactions__account` for it).
- **Build** (`apps/ynab_import/services/build.py`): `PlannedFeedRow`, `PlannedEntry.feed`,
  `ImportPlan.inbox_rows`, `_Resolver.goes_to_inbox()` (no category, not a transfer,
  not a correcting entry, not a tracking account, on a feed account). `PlannedLine`
  lost `is_reconciled`. `AccountChoice.has_feed`, defaulted by
  `analyse.suggested_feed()` (`DORMANT_DAYS = 365`, measured back from the export's
  last row). `check_balances` counts the Inbox rows; `_net_worth` (the preview) does
  not — it is what the ledger will say.
- **Apply** (`apply.py`): feed rows are bulk-inserted per batch, primaries then
  `mirror_rows_for`; `source=ynab` (new `BankTransaction.SOURCE_YNAB`, migration
  `bank_feed.0007`), `raw={"ynab": {"row": n}}`; `can_import` also refuses a book
  with any `BankTransaction`; `ApplyResult` gains `feed_rows`, `inbox_rows`,
  `dismissed_transfer_matches`.
- **Wizard**: "In Inbox" checkbox per account (`ynab-account-feed`; the Import
  checkbox became `ynab-account-import`), an "In your Inbox" stat on the preview
  and the result.
- **Not changed, deliberately**: the onboarding "categorize" task stays ticked — it
  is auto-detected from "has a journal entry", which an import has.
- **Tests**: `apps/ynab_import/tests/test_feed.py` (build rules, defaults, apply on a
  hand-written export and on the sample, the `sync_transfer` no-op invariant,
  portability round trip), `SplitTransferMirrorTest` in
  `apps/bank_feed/tests/test_splits.py`, two E2E tests in `e2e/tests/test_ynab_import.py`.
