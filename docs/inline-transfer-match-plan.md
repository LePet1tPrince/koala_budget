# Inline transfer matching in the bank feed — plan

**Status: built.** §10 lists where the build differs from the plan below.

Replace the "Review transfers" button + modal (`TransferSuggestions.jsx`) with a
per-row chip in the bank feed table. The chip opens an inline panel showing the
counterpart transaction; one **Match** click keeps one leg, archives the other,
and leaves a single journal entry that moves money between the two accounts. The
server decides which leg is archived.

## 1. Current state

| Piece | Location | Behaviour |
|---|---|---|
| Detection | `apps/bank_feed/services/transfer_detection.py::find_transfer_candidates(book)` | Book-wide, greedy one-to-one. Pairs: different account, equal magnitude, opposite sign, ≤ `BANK_FEED_TRANSFER_WINDOW_DAYS` (5) apart, not archived, counted entry, not a mirror, not the same entry, not dismissed. |
| List | `GET bankfeed/api/feed/transfers/` | `[{outflow, inflow, amount, date_gap_days}]`; each leg is a `BankFeedRowSerializer` row. |
| Resolve | `POST transfers/resolve` `{archive_id, keep_id}` | Client picks the leg. Voids the archived leg's entry, archives it and any leg sharing that entry. Refuses if any line of the archived leg's entry is reconciled. **Does not touch the kept leg.** |
| Dismiss | `POST transfers/dismiss` `{transaction_a, transaction_b}` | Records `TransferMatchDismissal`. |
| UI | `TransferSuggestions.jsx`, mounted in `LineApp.jsx` toolbar | Count button → modal of pairs; "Duplicate — archive {account}" ×2, "Not a duplicate". |

Gap in resolve: after archiving, the kept leg is still uncategorized (or
categorized to an expense), so the counterpart account loses the movement until
the user categorizes the kept leg as a transfer by hand. **Match must finish
that job** — otherwise "match" leaves balances wrong.

## 2. Target behaviour

1. A row in the selected account's feed that belongs to a candidate pair shows a
   chip **⇄ Possible transfer** in its Description cell.
2. Clicking the chip expands an inline panel (a `<tr>` under the row, `colSpan`
   all columns). No modal. One panel open at a time.
3. Panel shows the counterpart: account, date (+ day gap), payee, memo, signed
   amount, Categorized/Uncategorized, Reconciled lock. Plus one sentence stating
   the outcome before the click: *"Match keeps this transaction and archives the
   one in Visa — the one in Visa is not reconciled."*
4. Buttons: **Match** (primary), **Not a match** (ghost), **Go to other side**
   (switches account and flashes the counterpart row).
5. **Match** result, in one atomic request:
   - archive leg: entry voided (if any), row archived, any leg sharing that entry
     archived (existing resolve behaviour);
   - kept leg: categorized to the archived leg's account → one entry with a line
     on each account; `sync_transfer` creates the mirror row in the other feed.
   - Net effect: one entry, both feeds show the transfer, counted once.
6. **Not a match** = existing dismiss. Chip disappears from both feeds.
7. A blocked pair still shows the chip; Match is disabled and the reason is
   printed in the panel (not only a tooltip).

## 3. Decision rule — which leg is archived

Implemented once on the server (`propose(pair)`), sent to the client in the
suggestion payload, re-run at match time. Archiving voids the leg's **whole
entry**, so "locked" is a property of the entry, not the row's own flag.

```
locked(leg)  = leg.journal_entry exists AND any line of it is_reconciled
splitted(leg)= leg.journal_entry has > 2 lines
```

Ordered; first rule that decides wins:

| # | Condition | Result |
|---|---|---|
| 1 | either leg is a split | **blocked** — "Open the split to edit its categories." (a split cannot carry the transfer as one category; rewriting it is the editor's job) |
| 2 | both locked | **blocked** — "Both sides are reconciled. Unreconcile one to match them." |
| 3 | exactly one locked | keep the locked leg (user's rule: "if one is already reconciled, pick the other one" to archive) |
| 4 | one leg is already categorized to the other leg's account | keep it (already a transfer; no rewrite) |
| 5 | one leg categorized, other not | keep the categorized one (keeps its entry, edits, audit history) |
| 6 | source rank `plaid` > `csv` = `ynab` > `manual` | keep higher rank (live feed is authoritative) |
| 7 | tie | keep the outflow leg (transfer origin; mirror copies its description) |

Post-check on the chosen kept leg: if its category line must be re-pointed and
that line is reconciled (a transfer to a *third* feed account, reconciled there —
`assert_line_mutable` would refuse), **blocked** (`category_reconciled`). A swap
is never possible here: a reconciled category line makes the leg locked, and a
locked leg cannot be archived.

Output: `{status: "ready", keep_id, archive_id, reason_code, reason}` or
`{status: "blocked", code, message}`. `reason` is the user-facing clause shown in
the panel ("the one in Visa is reconciled", "this one is already categorized as a
transfer", …).

## 4. Backend

### 4.1 New service `apps/bank_feed/services/transfer_match.py`

- `propose(outflow, inflow) -> Proposal` — §3. Needs reconciled-line and
  line-count facts per entry; `find_transfer_candidates` adds one
  `prefetch_related("journal_entry__lines")` (or annotations
  `has_reconciled_line`, `line_count` via `Exists`/scalar subquery) so `GET
  transfers/` stays O(1) queries per page.
- `validate_pair(a, b, book)` — same predicates the detector applies (different
  accounts, equal magnitude, opposite sign, within window, neither archived,
  neither `is_transfer_mirror`, not same entry, not dismissed). Raises
  `MatchError` (user-facing message). Re-running the full greedy detector is not
  required: a pair valid on its own is safe to match even if the detector would
  have paired one leg differently.
- `archive_duplicate(tx)` — body of today's `transfer_resolve` atomic block,
  extracted (void entry, archive row, archive legs sharing the entry).
- `match(a, b, *, expected_archive_id, book) -> MatchResult` —
  `transaction.atomic`, `select_for_update` on both rows, `validate_pair`,
  `propose`; if `blocked` → `MatchError`; if `archive_id != expected_archive_id`
  → `ProposalChanged(proposal)` (state moved since the panel rendered); then
  `archive_duplicate(archive)` and `categorize_single(keep, archive.account)`.
  Returns `{kept_id, archived_id, kept_journal_entry_id, previous_category_id,
  voided_entry_id}`.

### 4.2 Extract single-category categorize into a service

`BankFeedViewSet._create_journal_from_bank_transaction` and
`_update_journal_category` are view methods. Move both into
`apps/bank_feed/services/categorize.py::categorize_single(bank_tx,
category_account)` (create entry if none, else re-point the category line with
the existing `would_orphan_primary` / `is_split` / `assert_line_mutable` guards,
then `sync_transfer`). The viewset methods become one-line wrappers. Behaviour
unchanged; existing `test_categorize.py` / `test_batch_edit.py` /
`test_transfer_mirror.py` must pass untouched.

### 4.3 Endpoints (`BankFeedViewSet`)

| Method | Path | Change |
|---|---|---|
| GET | `transfers/` | Each pair gains `proposal` (§3 output). New optional `?account=<id>`: filter **after** the book-wide greedy pass (filtering before would change pairings). |
| POST | `transfers/match` | **New.** Body `{transaction_a, transaction_b, expected_archive_id}`. 200 → `MatchResult`. 400 `MatchError`. 404 if either id is outside the book. 409 `{error, proposal}` on `ProposalChanged`. |
| POST | `transfers/dismiss` | Unchanged. |
| POST | `transfers/resolve` | **Removed** with the modal (only consumer). Two write paths with different guarantees (resolve leaves the kept leg uncategorized) is a hazard. |

Serializers: `TransferProposalSerializer`, `TransferMatchRequestSerializer`,
`TransferMatchResponseSerializer`; `@extend_schema` on all; regenerate
`api-client/` (frontend keeps calling through `getBatchOperationsApi`, as today).

Audit: reuse `AuditEvent.TRANSFER_DUP_RESOLVED` with metadata
`{mode: "match", kept_id, archived_id, reason_code, previous_category_id,
voided_entry_id}` — no audit migration. No model migration.

Isolation (`apps/books/tests/test_isolation.py`): add
`bank_feed:bank-feed-transfer-match` to `WRITES` (lambda building a pair from
each book); delete the `transfer-resolve` entry.

## 5. Frontend

### 5.1 Data — `LineApp.jsx`

- State `matches` + `loadMatches()` → `batchApi.transferSuggestions()` (whole
  book, one request; a pair lives in two accounts and account cards need counts
  for all accounts).
- `reloadFeed = () => Promise.all([loadLines(), loadAccounts(), loadMatches()])`
  replaces every post-mutation `Promise.all([loadLines(), loadAccounts()])`
  (categorize, edit, bulk edit, archive, unarchive, delete, duplicate,
  unreconcile, upload, Plaid refresh) — any of these can create or break a pair.
- `matchByTxId = useMemo(Map<importedTransactionId, {pair, self, other}>)`.
- Remove `<TransferSuggestions>` from the toolbar; delete
  `TransferSuggestions.jsx`.
- Handlers passed to the table: `onMatch(entry)`, `onDismissMatch(entry)`,
  `onOpenMatchCounterpart(entry)`.
- `focusRequest` gains an `importedTransactionId` form (today it locates by
  `journalEntryId`, which an uncategorized counterpart lacks). `LineTable`'s
  focus effect matches either key.
- After Match: `reloadFeed()`, then `focusRequest` on the kept entry
  (`kept_journal_entry_id`) — in this account that is either the kept row or its
  new mirror, so the row the user acted on is flashed either way. Toast:
  "Matched — kept the one in {account}, archived the one in {account}."
- 409: replace the pair's `proposal` with the returned one, keep the panel
  open, show "Something changed — check the new outcome and match again."

### 5.2 Table — `LineTable.jsx` + new `TransferMatchPanel.jsx`

- Chip: in the Description cell, before the text (widest column; Category is
  9rem and already holds the split badge and transfer link). `<button
  class="badge badge-warning badge-sm gap-1">` + `arrow-right-left` icon,
  label "Possible transfer", `aria-expanded`, `aria-controls`,
  `stopPropagation` (row click opens the edit modal), testid
  `transfer-match-chip-{row.id}`. Not rendered in the archived view.
- Panel row: `<tr data-testid="transfer-match-panel-{row.id}"><td
  colSpan={COLUMNS.length}>`. Two columns ≥ `md`, stacked below: "This
  transaction" | "Other side in {account}". Outcome sentence. Buttons
  `transfer-match-btn`, `transfer-dismiss-btn`, `transfer-goto-btn`. Blocked →
  Match `disabled` + reason in `text-warning` text. Busy state disables all three.
- `openMatchId` state in the table; Escape closes the panel; opening another
  chip closes the previous one; panel closes when its row leaves `pageRows`.
- Pagination: the panel row is not counted toward page size (inserted while
  rendering `pageRows`).

### 5.3 Discovery replacing the toolbar count

- Quick Filters dropdown: new independent item **Possible transfers** with a
  `Chip` count (rows in this account with a match), testid
  `quick-filter-transfers`. Combines with the existing filters like
  Uncategorized does.
- `AccountCard.jsx`: small `badge-warning` "N to match" when the account has
  pairs (counts derived from `matches`, no extra request).

### 5.4 API helpers — `assets/javascript/bank_feed/bank_feed.js`

`transferMatch(a, b, expectedArchiveId)`; `transferSuggestions(accountId?)`;
remove `transferResolve`.

## 6. Tests

### Backend — `apps/bank_feed/tests/test_transfer_match.py` (+ edit `test_transfers.py`)

`propose()` decision table, one test per row of §3:
- split on either side → blocked
- both locked → blocked
- one reconciled → archive the other (both directions)
- archive-candidate's entry has a reconciled **mirror** line in the other
  account → that leg is locked, kept
- kept leg's category line reconciled in a third account → swap to the other leg; blocked when the other is locked
- already categorized to counterpart → kept
- categorized vs uncategorized → categorized kept
- plaid vs csv → plaid kept; full tie → outflow kept

`match` endpoint:
- uncategorized + uncategorized → one posted entry, lines on both accounts,
  mirror row in counterpart feed, duplicate archived, each account balance and
  net worth move by the amount once
- kept categorized to an expense → re-pointed to the counterpart account
- both cross-categorized (each with its own mirror) → one entry voided, its
  mirror archived, one entry left
- reconciled kept leg → its bank line keeps `is_reconciled` and its `pk`
- 409 when `expected_archive_id` is stale, body carries the new proposal
- 400: same account, unequal amounts, same sign, archived leg, mirror leg,
  dismissed pair, outside window
- 404: id from another book
- audit event metadata
- second identical request → 400 (pair no longer valid)
- `GET transfers/` carries `proposal`; `?account=` filters after pairing

Isolation suite: `transfer-match` classified; `test_every_book_url_is_covered`
passes.

### E2E — `e2e/tests/test_bank_feed.py`, POM `e2e/pages/bank_feed.py`

Rewrite the four transfer-review tests (lines ~340–420) against the inline UI
(contract-first: write the new ones, delete the modal ones in the same change):
- chip shows on the leg in **both** account feeds
- panel shows counterpart account/payee/memo and the outcome sentence
- reconciled leg is kept; the unreconciled one is archived; Match then leaves
  one active row per account (kept row + mirror)
- both reconciled → Match disabled, reason visible
- Not a match → chip gone in both feeds, survives reload
- Go to other side → account switches, counterpart flashed
- Quick filter "Possible transfers" narrows to chip rows

POM: replace `transfer_review_button`/`open_transfer_review`/
`transfer_suggestion_*`/`transfer_archive_button`/`transfer_dismiss_button` with
`match_chip(row_text)`, `open_match(row_text)`, `match_panel()`,
`match_button()`, `not_a_match_button()`, `goto_counterpart_button()`.

## 7. Build order

1. `services/categorize.py` extraction (no behaviour change; existing tests green).
2. `services/transfer_match.py` (`propose`, `validate_pair`, `archive_duplicate`,
   `match`) + unit tests.
3. Endpoints + serializers + payload `proposal` + isolation entry + api-client
   regen. Remove `transfers/resolve`.
4. Frontend: `LineApp` data/reload, `LineTable` chip + `TransferMatchPanel`,
   Quick Filter, AccountCard badge, delete `TransferSuggestions.jsx`.
5. E2E rewrite.
6. `CLAUDE.md` Recent Changes entry; supersede the transfer-review paragraph.

## 8. Decided against

| Option | Why not |
|---|---|
| Hard-delete the duplicate | Next Plaid sync / CSV import of the same window re-creates it; loses the audit trail. Archive is what resolve already does. |
| Link both real rows to one entry (no archive) | `sync_transfer` keeps a mirror in lockstep with its primary, so it would overwrite the second bank row's own date/description; contradicts the requested "one is deleted" model. |
| Annotate `GET feed/` rows with match info | Detector is book-wide greedy; computing it per paginated page request repeats the whole pass per page. One `transfers/` request per reload is cheaper and already exists. |
| Client picks the leg (as resolve does) | Decision must survive state changing between render and click; server re-runs `propose` and 409s on drift. |

## 9. Open questions

1. **Undo.** Toast "Undo" → `POST transfers/unmatch` (unarchive, un-void,
   restore `previous_category_id` from the match response). Not requested;
   adds a write path. Recommend: ship without, add if users ask.
2. **Categorize mode.** Uncategorized legs of a pair also appear there.
   Recommend a follow-up: show the same chip on the card so a user doesn't
   categorize both legs as transfers (which today still leaves the pair flagged,
   so it is recoverable, not silent).
3. **Edit modal.** Show "Possible transfer with …" in `EditTransactionModal`?
   Recommend no — the row chip is visible behind it.

## 10. As built

- Services: `apps/bank_feed/services/categorize.py` (`categorize_single`,
  `create_entry`, `repoint_category`; the viewset's two methods are wrappers) and
  `apps/bank_feed/services/transfer_match.py` (`propose`, `propose_pairs`,
  `validate_pair`, `archive_duplicate`, `match_transfer`). `propose_pairs` loads
  the lines of every paired entry in one query rather than prefetching lines for
  the whole book.
- Endpoint name is `match_transfer` in the service; the route is
  `POST transfers/match` as planned. Proposal shape:
  `{status, code, message, keep_id, archive_id}` (`message` is the reason
  clause when ready, the full refusal when blocked).
- Chip label is **"Match found"** (shorter than "Possible transfer", which
  truncated the description column to a few characters); its tooltip and
  accessible name name the other account. The quick filter is **"Possible
  transfers"** (`filter-transfers`); the card badge is an icon + count on the
  institution line (`card-match-count`; not `account-card-…`, which would
  collide with the cards' own `account-card-<id>` prefix).
- The panel row is pinned to the left of the table's horizontal scroll area and
  sized to its visible width, so on a phone the buttons stay on screen.
- After Match the kept transfer (the kept row, or its new mirror in this
  account) is flashed without clearing the user's filters (`focusRequest`
  `keepFilters`); "Go to other side" locates an uncategorized counterpart by
  bank transaction id (`focusRequest.importedTransactionId`).
- `api-client/` regenerated (it was also missing the transaction-edit models).
- Undo, categorize mode and the edit modal (§9) were not built.
- Panel layout revised after review: a comparison table (one column per
  account, one row per attribute: Date, Amount, Category, Payee, Description,
  Reconciled) instead of two leg cards; a category pointing at the other leg's
  account reads "Transfer to/from {account}". The feed table has a 56rem
  minimum width so the chip keeps room at phone width.

