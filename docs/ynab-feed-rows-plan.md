# YNAB import → bank feed rows

**Goal:** every YNAB register row on a bank-type account arrives as a `BankTransaction`
in that account's Inbox feed, linked to the journal entry the import already writes.
Categorized rows arrive categorized (and locked where YNAB reconciled them); rows YNAB
never categorized arrive uncategorized, waiting in the Inbox.

**Supersedes D12** in `docs/ynab-import-plan.md` ("straight to the journal, no
`BankTransaction` rows"). D12's objection was presenting 7,572 already-answered
questions. Feed rows linked to their entries answer that: they are not in the
review queue, they are history in the place the user looks at an account.

All figures below are measured against `docs/reference/… Register.csv` (7,572 rows,
36 accounts: 22 on-budget, 14 tracking).

---

## 1. What changes for the user

| Today | After |
|---|---|
| Inbox is empty after import; every account card shows no rows | Each feed account shows its full YNAB history, categorized, reconciled rows locked |
| Categorize-mode suggestions (`similar_transactions.py`, history = categorized feed rows) have nothing to learn from | Suggestions work on day one: the last 2,000 categorized rows are YNAB's |
| First Plaid/CSV sync re-imports the overlap as uncategorized rows; categorizing them double-counts | Overlap can be matched against the imported rows (§4 B2) |
| YNAB-uncategorized rows post to `Uncategorized Expense/Income` | They sit in the Inbox as uncategorized feed rows |

---

## 2. Row → feed row rules

A feed row is written only on an account with `has_feed=True`. The journal side is
unchanged except for the uncategorized case.

| Register row | Sample count | Feed rows written |
|---|---|---|
| Categorized row / income inflow on a feed account | 4,474 + 1,115 | 1, `journal_entry` = its entry |
| Transfer, feed ↔ feed | 1,044 rows (522 pairs) | 2 on one entry: primary + `is_transfer_mirror=True` leg (§4 B3) |
| Transfer, feed ↔ non-feed (tracking) | 315 | 1, on the feed side only |
| Split | 169 legs in 83 groups | 1 per group, for the total, on the split's account |
| Split leg that is a transfer merged into the split (D8) | 3 | 0 on the *other* account (§4 B4) |
| Reconciliation adjustment (`RECONCILIATION_PAYEES`) | 15 | 1 (matches `reconciliation/services/adjustment.py`, which writes a feed row on `has_feed` accounts) |
| Uncategorized, non-transfer, on a feed account | 3 | 1, `journal_entry=None`; **no journal entry written** (§4 B5) |
| `Starting Balance` | 21 | 0 — opening balances are not bank transactions |
| Any row on a non-feed account | 433 | 0 |

Expected on the sample with today's `has_feed` rule: **~7,040 feed rows** across 22
accounts, ~6,985 of them locked as reconciled.

### Field mapping

| `BankTransaction` field | Value |
|---|---|
| `amount` | `-row.net` (feed convention: positive = outflow) |
| `posted_date` | `row.entry_date` |
| `description` | `_description(row)` truncated to 255 |
| `merchant_name` | `_payee(row)` (None for transfers, as today) |
| `source` | new `SOURCE_YNAB = "ynab"` (choices-only migration; `journal_source` → `SOURCE_IMPORT`) |
| `raw` | `{"ynab": {"index", "account", "payee", "category", "memo", "cleared"}}` — provenance, and the key the overlap matcher (§4 B2) reads |
| `is_transfer_mirror` | per §2 table |
| `journal_entry` | the entry built from the row; None for §2's uncategorized case |

`FEED_SOURCES` in `apps/portability/services/schema.py` is derived from
`SOURCE_CHOICES`, so the new value exports/imports with no format bump.

---

## 3. Implementation

### Phase 1 — Build (pure)

- `build.py`: `PlannedFeedRow(account, amount, posted_date, description, merchant, is_mirror, raw)`;
  `PlannedEntry.feed: tuple[PlannedFeedRow, ...]`; `ImportPlan.inbox_rows: list[PlannedFeedRow]`
  for uncategorized rows with no entry. Rules from §2 live in `_simple_entry`,
  `_transfer_entry`, `_split_entry`, and a new branch in `_build_entries` for the
  uncategorized case.
- `AccountChoice.has_feed` (wizard payload `accounts[name].has_feed`, validated in
  `parse_choices`). Default = today's rule (`on_budget or liability`).
- `reconcile.py::check_balances`: expected closing balance minus the sum of
  `inbox_rows` per account; `_net_worth(plan)` likewise. Gate stays exact.
- `_stats`/`_notes`: `feed_rows`, `inbox_rows`, `inbox_amount`, split-transfer legs
  not shown in a feed (B4).
- `assert_sound`: every consumed row reaches an entry **or** `inbox_rows`.

### Phase 2 — Apply + wizard

- `apply.py::_create_entries`: after each batch's entries exist, `bulk_create`
  their feed rows; then `inbox_rows` in one batch. `ApplyResult.feed_rows`.
  `ANALYZED_MODELS` already analyzes `BankTransaction`.
- `can_import`: also refuse a book with any `BankTransaction` — an uploaded-but-
  uncategorized CSV passes today and would be duplicated.
- `AuditEvent.YNAB_IMPORT` metadata gains `feed_rows`/`inbox_rows`.
- Wizard, accounts screen: "Show in Inbox" toggle per account. Summary screen:
  "N transactions in your Inbox feeds, M waiting to be categorized ($X — these
  accounts' balances reach YNAB's once they are)".
- Onboarding: the YNAB path pre-ticks the categorize task; leave it unticked when
  `inbox_rows` is non-empty.

### Phase 3 — Transfer-review guard

`transfer_detection.py` changes per §4 B1. Must ship with Phase 2.

### Phase 4 — Overlap matcher for Plaid/CSV

Matcher + "matched" marker per §4 B2, called from `process_added_transaction` and
`preview_transactions`.

### Phase 5 (optional) — Statement records

One completed `Reconciliation` per account at its last reconciled row's date,
`statement_balance` = reconciled balance, `cleared_total` = sum of locked lines, so
the feed header and account cards show "reconciled through {date}" instead of
nothing. Lines get `reconciliation_id`. Requires `integrity.py` to treat it as intact.

### Tests

Pure: every §2 rule, the gate with inbox rows, `has_feed` toggle, sample totals
(`feed_rows`, `inbox_rows`). Apply: the sample lands N feed rows; each feed row's
account has a line on its entry; mirror/primary share an entry; `bank_transaction_to_feed_row`
reports the right category/split/reconciled for each §2 case. Isolation: nothing
in a sibling book. E2E: import → account card shows rows → a reconciled row is locked.

---

## 4. Blockers and risks

### B1 — Transfer review floods with historical false positives · **blocking**

`find_transfer_candidates()` scans every non-archived, non-mirror feed row,
categorized included, and pairs equal-magnitude opposite-direction rows on
different accounts within 5 days. Five years of history will produce coincidental
pairs (a $50 refund here, a $50 purchase there). "Resolve" **voids** the archived
leg's entry — one wrong click deletes a real expense from every balance. It also
loads every feed row into Python on each call.

Fix: skip a pair when both legs are `source=ynab` (YNAB already paired every real
transfer: 839 matched, 0 unmatched), and bound the scan (e.g. rows posted in the
last 90 days or unreconciled). Measure the candidate count on the sample before/after.

### B2 — Plaid/CSV overlap duplicates · **blocking for anyone who links a bank**

- Plaid (`plaid/tasks.py::process_added_transaction`) dedupes only on
  `plaid_transaction_id`. The first sync's history window duplicates every imported
  row in it.
- CSV (`csv_upload.py`) flags a duplicate only on account + date + amount +
  **description `iexact`**; YNAB's cleaned payee/memo never equals the bank's raw
  text, so nothing is flagged.

This exists today (D12's corollary — the per-account cut-off it called for was never
built), and is worse today: the duplicate arrives uncategorized against an entry that
already exists, and categorizing it double-counts. Feed rows make it fixable:
match an incoming row to an unmatched `source=ynab` row on the same account, same
amount, date within ±3 days (prefer uncleared YNAB rows, then closest date). Plaid:
attach the `PlaidTransaction` to the existing row instead of creating one. CSV:
mark `is_potential_duplicate`. Needs a "matched" marker on the YNAB row
(`raw["ynab"]["matched"]` or a nullable FK) so one YNAB row absorbs one bank row.

### B3 — Transfers: both legs are real, the model has a primary and a mirror

KB's feed transfer = one real leg + one synthetic mirror. Imported, both are real.
Making the inflow leg the mirror reuses every invariant (archive/delete together,
detection exclusion, orphan guard) at two costs: `sync_transfer` overwrites the
mirror's description/merchant/date from the primary on the first edit, and
`would_orphan_primary` refuses re-categorizing the mirror leg to a non-feed account
("edit the original transaction instead"). Alternative — two non-mirror legs on
one entry — needs `sync_transfer`, `linked_legs`, `would_orphan_primary` and
`batch_delete` audited for a non-mirror counterpart. **Recommend mirror.**

### B4 — Split with a merged transfer leg (3 rows on the sample)

The split's entry has one bank line plus legs; one leg is another feed account.
A feed row on that other account would render as a split of the *wrong* account
(`bank_transaction_to_feed_row` treats every non-own line as a leg) and
`apply_splits` would edit the wrong bank line. Its journal line still counts, so the
balance is right; the row is missing from that feed. Named in the import summary.
Alternative: restructure into a split + a separate transfer entry — changes the
statement-line shape on the split's account. **Recommend leave out.**

### B5 — Uncategorized rows in the Inbox (3 on the sample)

No journal entry → the account balance is short by their amount until categorized,
and a YNAB-reconciled row cannot carry `is_reconciled` (it lives on `JournalLine`).
The gate change in Phase 1 keeps the reconciliation exact; the summary says why the
balance differs. On the sample all 3 are Cleared/Uncleared, none Reconciled.
Decision needed for other exports: a *reconciled* uncategorized row → Inbox (loses
lock) or `Uncategorized Expense/Income` + categorized feed row (keeps lock).
**Recommend the latter**: a reconciled statement must not change after import.

### B6 — Accounts that are not banks get Inbox cards

Default `has_feed = on_budget or liability` puts `Cash` (79 rows),
`Reconcile account` (516 rows — a pension pass-through clearing account) and
`BBC A/R` in the Inbox, plus 13 dormant zero-balance accounts. The per-account
toggle (Phase 1) is the fix; defaults need a rule. `feed_accounts` does **not**
filter `is_archived`, so archiving dormant accounts would not hide their cards
without that change too.

### B7 — Uncleared and future-dated rows

60 uncleared + 80 cleared-not-reconciled rows on feed accounts; 6 dated after the
export date (scheduled). Uncleared rows are the likeliest to be duplicated by the
first bank sync — B2's matcher prefers them. Future-dated rows are already posted
as journal entries today; as feed rows they would show future dates in the Inbox.
Decision: skip feed rows for `entry_date > export date`, or import as-is.

### Non-blocking

- **Volume:** +~7,000 inserts beside ~13,300 lines; same batch loop. Feed list is
  paginated (200) and prefetches lines.
- **Portability:** new `source` value flows via `FEED_SOURCES`; `wipe_book` cascades
  `BankTransaction` through `Account`. Round-trip test with the sample.
- **Guards:** reconciled imported rows are protected by the existing
  `ReconciledLineError` guards on every edit path; no change.
- **Audit:** `bulk_create` skips signals by design; the one `YNAB_IMPORT` event is the record.

---

## 5. Decisions

| # | Question | Recommendation |
|---|---|---|
| F1 | Transfer feed ↔ feed: primary + mirror, or two real legs | Primary (outflow leg) + mirror (B3) |
| F2 | Split-merged transfer legs | Leave out of the other feed; name in summary (B4) |
| F3 | YNAB-uncategorized rows | Inbox if unreconciled; `Uncategorized` account + categorized feed row if reconciled (B5) |
| F4 | Default "Show in Inbox" per account | On-budget or liability, **off** when closing balance is 0 and no row in the last 12 months (B6) |
| F5 | Future-dated rows | No feed row (B7) |
| F6 | Ship B2 with this, or after | With it: without the matcher, linking a bank after import duplicates the overlap |
| F7 | Phase 5 statement records | After; not needed for the goal |
