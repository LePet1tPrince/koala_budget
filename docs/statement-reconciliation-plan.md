# Statement Reconciliation — Requirements & Implementation Plan

**Status:** implemented (2026-09-23). Decisions D1–D9 accepted as recommended, except
D6, changed on review to allow undoing **any** statement (see §5). What the build did
differently from this plan is listed in §16; the rest of the document is kept as the
record of why the design is what it is.
**Priority:** P1.3 in `docs/feature-priority-report.md`.
**Estimate:** 9–10 dev-days (report said 6–9; §12 explains the difference).
**Prerequisite reading:** this document only.

---

## 1. What this feature is

A **reconciliation** checks the ledger against one bank or card statement. The user
enters the statement's closing date and closing balance, ticks each ledger line that
appears on the statement, and the app shows the difference live:

- **Difference = $0.00:** "Your statement says $4,182.19 as of Aug 31. Koala says
  $4,182.19. You're clear." The ticked lines are locked as reconciled, and the statement
  is kept as a permanent record.
- **Difference ≠ $0.00:** "Koala says $4,169.44. The $12.75 difference is probably one of
  these:" followed by specific candidates (§7.5). The user can fix it, save and come back
  later, or finish with an explicit adjustment entry.

The feature adds three things that do not exist today:

1. **A statement record** (date, balance, the lines it covered, and who finished it).
2. **A session that survives the browser.** Ticks are saved on the server, so a
   reconciliation can be resumed later.
3. **An integrity check.** Each finished statement can later be tested for whether it
   still holds. This is how the refund guarantee becomes something we can check.

---

## 2. What exists today (verified against the code)

| Piece | Where | Reuse? |
|---|---|---|
| `JournalLine.is_reconciled` | `apps/journal/models.py` | **Yes.** It stays the only input to every reconciled balance. |
| `JournalLine.is_cleared` | same | Not used. YNAB import sets it and nothing reads it. Out of scope; leave it alone. |
| `AccountQuerySet.with_reconciled_balance()` | `apps/accounts/querysets.py:38` | **Yes.** It sums `dr − cr` over reconciled, non-void lines. |
| `batch_reconcile` / `batch_unreconcile` | `apps/bank_feed/views.py:1617`, `:1787` | These operate on feed rows only. §5 D1 changes the reconcile half. |
| `_create_reconciliation_adjustment()` | `apps/bank_feed/views.py:1683` | **Move it to a service** and reuse it. It posts to the system equity account "Reconciliation Adjustments". |
| Reconcile dialog with a "True Balance" field | `BatchActionBar.jsx:315-380` | To be replaced (§5 D1). |
| "Reconciled balance … as of {date}" header | `LineApp.jsx:643-650` | Keep. Feed the date from the last statement (§10). |
| `latest_reconciled_date` | `_annotate_feed_account_activity`, `views.py:96` | Keep as the fallback when no statement exists. |
| Monthly-review health flags `UNRECONCILED`, `BALANCE_GAP` | `apps/monthly_review/services/health.py` | Add a `STATEMENT_DUE` flag (§10). |
| Guards on reconciled lines: amount change, de-categorize, archive, batch move, transfer resolve | `bank_feed/views.py` | Keep. Three gaps are listed in §3. |

**Two facts shape the design:**

- **Not every ledger line has a feed row.** The YNAB importer writes thousands of entries
  with no `BankTransaction` (`apps/ynab_import/services/apply.py`). Opening balances
  (`apps/onboarding/services/opening.py`) and future manual entries (P1.2) have none
  either. **The reconciliation therefore works on `JournalLine`s for an account, not on
  feed rows.** A flow built on feed rows could not reconcile a YNAB migrant's accounts,
  and YNAB migrants are our acquisition channel.
- **Balances are stored in ledger sign (`dr − cr`) and shown that way.** A credit card
  that owes $1,234.56 appears as **−$1,234.56** on the feed card, in the header and in the
  dialog. A paper statement says **$1,234.56**. §6 fixes this in one place.

---

## 3. Defects to fix first (Phase 0)

The guarantee claims that a reconciled line stays reconciled. Today it does not. The
three 🔴 items were **confirmed by running tests** against the current code (a temporary
test in `apps/bank_feed/tests/`, since deleted). Each one returned HTTP 200 and changed
reconciled state:

### 3.1 🔴 Editing one side of a transfer unreconciles the other side
Steps: categorize checking → credit card (a transfer, which creates a mirror leg).
Reconcile the **credit card** side. Then edit only the **checking** side's description.
**Result:** the credit card line's `is_reconciled` becomes `False`.

Cause: `apply_splits()` (`apps/bank_feed/services/splits.py:165-179`) deletes and
recreates every non-bank line on the premise that "they carry no state the user set".
That premise is wrong for a transfer. The counterpart line is the **other feed's bank
line**, and it carries that feed's `is_reconciled`. The update guard at
`views.py:668-676` only checks the edited side's own line. The same thing happens in the
other direction (editing the mirror recreates the checking line), and on every path that
calls `apply_splits` (`update`, `batch_edit`, `_update_journal_category`, CSV
auto-categorize).

**Fix:** in `apply_splits`, when a leg's account already has a line on the entry and the
leg keeps that account, update the line in place instead of deleting and recreating it.
If a reconciled counterpart line would be **deleted or change amount** (the transfer is
re-pointed, or its total changes), refuse with "The other side of this transfer is
reconciled. Unreconcile it first." That is the wording the archive guard already uses.

### 3.2 🔴 A reconciled transaction can be moved to another account and re-dated
`PUT feed/{id}/` with a different `account` and a later `date` returns 200. The
reconciled bank line moves into the other account and keeps `is_reconciled=True`. Both
accounts' reconciled balances change. `batch_edit` already refuses this move
(`views.py:1296`), but the single-row `update` does not.

**Fix:** in `update`, refuse an account change on a reconciled row. Refuse a date change
when the new date falls after the `statement_date` of the statement that reconciled the
line (§8.3). Before any statement exists, date changes stay allowed; they cannot break a
statement that does not exist yet.

### 3.3 🔴 A reconciled entry can be voided
`POST journal/api/journal-entries/{id}/void_entry/` voids an entry that has reconciled
lines (`apps/journal/views.py:87`). `NOT_VOID` then removes those lines from the
reconciled balance without any warning. **Fix:** refuse to void an entry that has a
reconciled line.

### 3.4 🟠 `JournalEntrySerializer.update()` recreates all lines
`apps/journal/serializers.py:146-152` runs `instance.lines.all().delete()` and then
recreates the lines, which drops `is_reconciled`. This was found by reading the code, not
by a test. The feed does not reach it today. P1.2 (manual edit) will, unless it is
guarded now. **Fix:** refuse `lines` in the payload when any existing line is reconciled.

### 3.5 🟠 The "True Balance" field in the current dialog has a sign trap
`computedAdjustment = trueBalance − (reconciledBalance + reconcilingAmount)`
(`BatchActionBar.jsx:96`). All the values are ledger-signed. On a card, a user who types
the statement's **1,234.56** gets an adjustment of about **+$2,469.12** instead of $0.
This was found by reading the code. It is removed by D1.

**All guard logic goes in one module,** `apps/reconciliation/services/guards.py`
(`assert_line_mutable(line, *, new_account=None, new_date=None, new_amount=None)`,
`assert_entry_voidable(entry)`), so that the feed, the journal API and P1.2 all call the
same checks.

---

## 4. Terms

| Term | Meaning |
|---|---|
| **Statement** | One `Reconciliation` row: account, `statement_date`, `statement_balance`. |
| **Draft** | A statement that is still being worked on. At most one per account. |
| **Candidate line** | A `JournalLine` on the account that can be ticked (§7.2). |
| **Ticked** | A candidate that belongs to the draft (`line.reconciliation = draft`, `is_reconciled` still `False`). |
| **Opening** | The account's current reconciled balance when the draft is evaluated. |
| **Difference** | `statement_balance − (opening + Σ ticked)`. The draft can be finished when this is 0. |
| **Intact** | A completed statement whose own lines still sum to the total recorded when it was finished (§8.2). |
| **Statement sign** | Assets: `dr − cr`. Liabilities: `cr − dr`. This is the sign printed on a statement. |

---

## 5. Decisions (accepted; D6 changed on review)

**D1. Replace the feed's quick reconcile with the statement flow.**
*Recommended: yes.* The feed's **Reconcile** button now opens `/reconcile/<account>/`
with the selected rows already ticked in a draft. **Unreconcile** stays in the feed. The
"True Balance" and adjustment fields are removed; adjustments exist only in the statement
flow, where the sign is handled correctly.
*Why:* if both paths exist, lines can be reconciled with no statement, and the drift
check (§8.2) then reports false changes. One path keeps the check honest.
*Cost:* ticking a few rows as reconciled without a statement is no longer possible.
*Alternative:* keep the quick path and accept that the drift check only covers lines
reconciled through statements.

**D2. Which accounts can be reconciled.**
*Recommended:* every non-system asset or liability account, with or without a feed. This
includes YNAB tracking accounts, a mortgage, and cash. Income, expense and equity
accounts cannot be reconciled.

**D3. What is ticked when a session starts.**
*Recommended:* nothing, except the rows the user selected in the feed. The screen offers
one-click **"Tick all through Aug 31"**, which the server applies by date (§9). The
statement means something only if a person actually compared the lines. Auto-ticking
would turn the guarantee into a rubber stamp.
*Alternative:* pre-tick every candidate dated on or before the statement date. That is
faster and weaker.

**D4. Unreconciling a line from a completed statement.**
*Recommended:* allow it, with a confirmation that names the statement: "This transaction
is part of your Aug 31 statement. Unreconciling it will mark that statement as changed."
The statement then shows **Changed** (§8.2), and the line becomes a candidate again.
*Alternative:* refuse, and require **Undo reconciliation** on the whole statement. That
is stricter, but more annoying when fixing one mistake.

**D5. Where adjustments post.**
*Recommended:* only to the existing system equity account **Reconciliation Adjustments**,
through the existing helper. Adjustments then never appear in income or expense reports.
A real missing fee should be entered as a transaction (§9.4), not as an adjustment.

**D6. Undo.** *Decided: any completed statement can be undone, not only the latest.*
Undo clears its lines' `is_reconciled`, voids its adjustment entry (archiving the
adjustment's feed row), and marks the statement `undone`; the row is kept for history.
The lines **keep** their link to the undone statement, so the next session's drift
banner can say which statement they came from. Undoing an older statement leaves later
statements intact (their own lines are untouched); the reconciled balance falls by what
the undone one locked, and those lines are candidates again.

**D7. Export/import.**
*Recommended:* statements travel with the data export: a new `reconciliations.csv`, a
`reconciliation_id` column in `journal.csv`, and a format version bump. Archives from
before the bump still import, with no statements. The schema test (`test_schema.py`)
forces this choice anyway: the new `JournalLine.reconciliation` field must be either
mapped or omitted with a stated reason.

**D8. Who can do what.**
*Recommended:* any team member can start, finish or undo a reconciliation. This matches
today's feed reconcile, and budgeting households share this work. Every action is
recorded as an `AuditEvent`.

**D9. Navigation.**
*Recommended:* no new top-level navigation item. Entry points are the bank-feed header,
the account detail page, a **Reconciliation status** row on Reports home (the hub,
§9.2), and monthly-review insights.

---

## 6. Sign convention — the only arithmetic in this feature

**The server calculates in ledger sign. The API and UI use statement sign.** One pair of
functions converts between the two, and nothing else flips signs:

```python
# apps/reconciliation/services/signs.py
def to_statement(account, ledger_amount):   # asset: x ; liability: -x
def to_ledger(account, statement_amount):   # inverse
```

For each candidate line, the API returns `amount = to_statement(account, dr − cr)`. This
is the line's effect on the statement balance. The client's calculation is then always:

```
difference = statement_balance − (opening + Σ ticked amounts)
```

Every value in that formula is in statement sign, for every account type. The client adds
**integer cents** (`toCents` added to `common/amount.js`), never floats.

### 6.1 Worked examples (use them as test fixtures)

**Chequing (asset).** The last statement was Jul 31 at $3,904.11, so opening = 3,904.11.
The Aug 31 statement says **$4,182.19**.

| Line | Ledger `dr−cr` | Statement amount |
|---|---|---|
| Paycheque | +2,450.00 | +2,450.00 |
| Rent | −1,800.00 | −1,800.00 |
| Costco | −359.17 | −359.17 |
| Coffee | −12.75 | −12.75 |
| Coffee (the same purchase, imported twice) | −12.75 | −12.75 |

- All five ticked: 3,904.11 + 2,450 − 1,800 − 359.17 − 12.75 − 12.75 = **4,169.44**.
  Difference = **+12.75**. The hint (§7.5) names the duplicate pair.
- Untick one coffee: the total is 4,182.19 and the difference is **0.00**. The statement
  can be finished.

**Credit card (liability).** The statement says the balance owed is **$1,234.56**. The
reconciled ledger balance is −1,000.00, which is 1,000.00 in statement sign. The ticked
lines are a charge of 284.56 (ledger `dr−cr` = −284.56, statement +284.56) and a payment
of 50.00 (ledger +50.00, statement −50.00). 1,000.00 + 284.56 − 50.00 = **1,234.56**, so
the difference is 0. The user types the number printed on the statement. The field label
says "Balance owed", and "(enter as a positive number)" appears under it.

**Adjustment.** If the chequing statement is finished with a difference of +12.75, then
`to_ledger(+12.75)` = +12.75, which is a debit to chequing and a credit to Reconciliation
Adjustments. If a card statement is finished with a difference of +12.75 (the card owes
12.75 more), `to_ledger` gives −12.75, which is a credit to the card. The existing
helper's `amount > 0 → debit bank` rule is correct when it receives the **ledger**
amount, and the server always passes it one.

---

## 7. Backend — services (`apps/reconciliation/services/`)

A new app, `apps.reconciliation`. This follows the house pattern of one app per feature,
and keeps the logic out of `bank_feed`, because the flow is not limited to feed accounts.

### 7.1 `balances.py`
- `reconciled_balance(account)` uses `with_reconciled_balance()` and needs no change.
- `summary(draft)` returns `{opening, ticked_total, difference, ticked_count}` in
  statement sign. It is **always recomputed from the database**, never taken from the
  client.

### 7.2 `candidates.py`
A line is a candidate when all of these hold:

```
line.account == account
and not line.is_reconciled
and line.journal_entry.status != void
and (line.reconciliation is null or line.reconciliation.status != draft or line.reconciliation == this draft)
and line's entry is not linked to an ARCHIVED BankTransaction in this account
```

The last condition matches `with_categorized_balance()`: an archived feed row is a
dismissed duplicate. Lines are ordered by `entry_date` and then `pk`. The list is limited
to `entry_date ≤ statement_date + 7 days`, with `?include_later=1` to show everything.
Banks and the ledger often disagree on dates by a day or two, so lines dated after the
statement date can still be ticked; a hint mentions them (§7.5).

Each candidate carries `id, date, payee, description, category (or "Split (N)"),
amount (statement sign), ticked, has_feed_row, source`.

**Uncategorized feed rows** have no journal line, so they cannot be ticked. The session
reports them separately as `{count, total, earliest, latest}` for rows dated on or before
the statement date, with a link to categorize mode (`/bankfeed/categorize/?account=`).
A statement almost always includes them, so the hint in §7.5 checks whether they account
for the difference.

### 7.3 `session.py`
- `start(account, statement_date, statement_balance_stmt, user, preselect_line_ids=())`
  refuses a system account or an account type other than asset/liability. It refuses a
  `statement_date` on or before the latest completed statement's date. If a draft already
  exists, it returns that draft (one draft per account, enforced by a DB constraint).
  Preselected lines must be candidates.
- `tick(draft, line_ids, ticked: bool)` is idempotent and team-scoped. It refuses ids
  that are not candidates. It writes with `QuerySet.update(reconciliation=…)`, **with no
  audit rows**: a draft tick is not history.
- `tick_through(draft, date)` ticks every candidate dated on or before `date` in one
  `UPDATE`. On a first reconciliation this is what makes 2,000 historical lines
  practical.
- `finish(draft, *, adjust: bool, expected_difference)`:
  1. `select_for_update()` on the draft.
  2. Recompute the summary. If the difference is 0, continue. If it is not 0 and
     `adjust` is false, return **400**. If `adjust` is true and the difference does not
     equal `expected_difference`, return **409** ("the numbers changed while you were
     looking; review again"). This protects against stale clients and two household
     members working on the same draft.
  3. If adjusting: `create_adjustment(account, to_ledger(diff), statement_date)`. That is
     the moved helper, and it creates a feed row **only when `account.has_feed`**. The
     adjustment's bank line gets `reconciliation=draft, is_reconciled=True`.
  4. Set `is_reconciled=True` on each ticked line **with a save per line**, so that
     `AuditLog` records each flip. This is the same choice as `batch_archive`: history is
     the point of the feature. About 3 queries per line; 300 lines take under a second.
  5. Snapshot `opening_balance`, `cleared_total` (Σ own lines, ledger sign, including the
     adjustment) and `adjustment_amount`. Set `status=completed`, `completed_at` and
     `completed_by`.
  6. `log_event(RECONCILIATION_COMPLETED, …)`.
- `discard(draft)` deletes the draft row. `SET_NULL` releases its ticks.
- `undo(rec)`: see D6. Any completed statement can be undone.

### 7.4 `integrity.py`
- `is_intact(rec)`: Σ(`dr − cr` of lines where `reconciliation=rec`, `is_reconciled`,
  entry not void) `== rec.cleared_total`.
- `drift(account)`: the current reconciled balance minus the latest completed
  `statement_balance`, plus the list of lines responsible. That list is the lines linked
  to any completed statement that are now unreconciled or void. It can be produced
  because D4 **keeps** the `reconciliation` link when a line is unreconciled (§8.3).

After the Phase 0 guards, the only ways a completed statement can drift are an explicit
unreconcile (with a warning) or a whole-team wipe on import. Both are visible, so the
drift banner can always explain itself.

### 7.5 `diagnose.py` — difference hints (pure, fully unit-tested)
Input: candidates (id, date, amount, ticked), the difference, `statement_date`, and the
uncategorized-row summary. Output: up to 5 hints, ranked. Each hint gives a sentence and
the line ids to highlight.

| Rule | Condition | Message |
|---|---|---|
| Missing tick | an unticked line equals `diff` | "Tick *Coffee, Aug 30, −$12.75*?" |
| Extra tick | a ticked line equals `−diff` | "*Coffee* may not be on this statement. Untick it?" |
| Duplicate | two ticked lines with the same amount within 3 days, and the amount equals `diff` in size | "These two look like the same purchase." |
| Wrong sign | a ticked line equals `diff / 2` | "*X* may be entered as money in instead of money out." |
| Transposed digits | changing one ticked line by swapping two adjacent digits gives `diff` (checked concretely, not just `diff % 9`) | "Did the bank show *$54.10* where Koala has *$45.10*?" |
| After statement date | Σ ticked lines dated after `statement_date` equals `−diff` | "These are dated after Aug 31." |
| Uncategorized | an uncategorized row, or all of them together, equals `diff` | "Categorize these N transactions first." |
| Drift | `drift(account) ≠ 0` | a banner, not a hint (§9.3) |

A subset-sum search is **out of scope**: it is exponential, and it produces confident
wrong answers.

---

## 8. Data model

### 8.1 New model `apps/reconciliation/models.py`

```python
class Reconciliation(BaseTeamModel):
    STATUS_DRAFT, STATUS_COMPLETED, STATUS_UNDONE = "draft", "completed", "undone"

    account = FK("accounts.Account", CASCADE, related_name="reconciliations")
    statement_date = DateField()
    statement_balance = Decimal(15, 2)      # LEDGER sign (dr−cr); API converts (§6)
    status = CharField(choices, default=draft)
    opening_balance = Decimal(15, 2, null)  # snapshot at finish
    cleared_total = Decimal(15, 2, null)    # Σ own lines at finish, ledger sign, incl. adjustment
    adjustment_amount = Decimal(15, 2, default=0)  # ledger sign
    started_by / completed_by = FK(User, SET_NULL, null)
    completed_at / undone_at = DateTimeField(null)

    class Meta:
        ordering = ["-statement_date"]
        constraints = [UniqueConstraint(fields=["account"], condition=Q(status="draft"),
                                        name="one_draft_reconciliation_per_account")]
```

There is **deliberately no FK to the adjustment `JournalEntry`.** The adjustment's bank
line points at the statement through `JournalLine.reconciliation`, so it can be found
from there. This also keeps `portability/services/wipe.py` safe: that module raw-deletes
entries, and an FK from a reconciliation to an entry would make that `DELETE` fail.

### 8.2 `JournalLine.reconciliation`
`FK(Reconciliation, SET_NULL, null, blank, related_name="lines")` in journal migration
`0002`. Meaning of each state:

| `reconciliation` | `is_reconciled` | Meaning |
|---|---|---|
| null | False | Never reconciled |
| null | True | Reconciled before statements existed (feed quick path, YNAB import). Counts toward the opening balance. |
| draft | False | Ticked in an open session |
| completed | True | Reconciled by that statement |
| completed | False | Unreconciled after the fact, so that statement is now **Changed** |

### 8.3 How the guards use the link
`assert_line_mutable` refuses a date change past `line.reconciliation.statement_date`
when the line is reconciled. It refuses an account change and an amount change on any
reconciled line, whether or not it has a statement.

### 8.4 Audit
Add `RECONCILIATION_STARTED`, `RECONCILIATION_COMPLETED`
(`{account, statement_date, statement_balance, lines, adjustment}`) and
`RECONCILIATION_UNDONE` in audit migration `0009`. Started versus completed gives the
funnel.

---

## 9. API and pages

### 9.1 JSON API (`/a/{slug}/reconcile/api/`)
This is a DRF ViewSet with `TeamModelAccessPermissions` and `extend_schema` on every
action. **Regenerate `api-client/`** afterwards; per the house rule, no fetch calls are
written by hand.

| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | `accounts/` | — | Asset/liability accounts, each with its reconciled balance (statement sign), last statement `{date, balance, intact}`, draft id, uncategorized count |
| GET | `reconciliations/?account=` | — | History, newest first, with `intact` |
| POST | `reconciliations/` | `account, statement_date, statement_balance, line_ids?` | The draft (or the existing draft) |
| GET | `reconciliations/{id}/` | `include_later?` | Header, summary, candidates, uncategorized summary, hints, drift |
| PATCH | `reconciliations/{id}/` | `statement_date?, statement_balance?` (draft only) | Summary and hints |
| POST | `reconciliations/{id}/tick/` | `line_ids, ticked` | Summary and hints |
| POST | `reconciliations/{id}/tick_through/` | `date` | Summary, hints, and the ids that were ticked |
| POST | `reconciliations/{id}/finish/` | `adjust, expected_difference` | The completed statement (200), or 400/409 |
| POST | `reconciliations/{id}/undo/` | — | The undone statement (any completed statement) |
| DELETE | `reconciliations/{id}/` | — | 204 (draft only) |

### 9.2 Page views
- `/a/{slug}/reconcile/` is the **hub**: every reconcilable account with its last
  statement, status, and a Start/Continue button. It doubles as the evidence page for
  the guarantee ("every account reconciled to the penny as of …").
- `/a/{slug}/reconcile/<account_id>/` opens the draft if one exists, otherwise the start
  form. `?lines=1,2,3` passes the feed selection through (D1).
- `/a/{slug}/reconcile/statement/<id>/` is a read-only statement: its lines, totals,
  who finished it and when, and whether it is intact. It can be printed.

All three use `@login_and_team_required`, and one Vite entry, `reconcile-app`, with
props passed through `json_script`.

### 9.3 Frontend (`assets/javascript/reconcile/`)
- **`StartForm.jsx`:** account; statement date (defaults to the last day of the month
  after the previous statement, or of last month if there is none); statement balance
  ("Balance owed" for liabilities, with the sign explained). Shows "Starting from $X —
  your Jul 31 statement" as a read-only line.
- **`Workspace.jsx`:**
  - **A sticky summary strip:** Statement · Starting · Ticked (in / out) · **Difference**.
    The difference is large, green at 0 and neutral otherwise. On a phone the strip
    stacks at 390px.
  - **The line table:** checkbox, Date, Payee / Description, Category, In, Out. Liability
    columns are labelled "Payments" and "Charges". Filters: All / In / Out / Unticked.
    An **amount search** narrows the table as the user types ("12.75"), which is how
    people match against a paper statement. Keyboard: ↑/↓ moves, Space ticks. The
    checkboxes use `rounded-sm`, because the theme otherwise makes checkboxes look like
    radio buttons (`--radius-selector`).
  - **"Tick all through {date}"** and **"Untick all"**.
  - **An uncategorized callout** ("7 transactions from this account aren't categorized
    yet — they can't be reconciled until they are") with a link to categorize mode.
  - **`DifferenceHints.jsx`**, shown only when the difference is not 0. Each hint
    highlights its rows and has a one-click action (tick or untick).
  - **A drift banner** (`alert-warning`) when `drift ≠ 0`: "Since your Jul 31
    reconciliation, 1 reconciled transaction was unreconciled: *Coffee −$12.75*. It's
    back in the list below."
  - **Ticks save optimistically**, batched every 250ms into one `tick` POST. The summary
    is computed on the client from the local tick set, so it responds immediately. Each
    POST takes a **monotonic ticket**, and only the newest response may overwrite the
    summary. This is the same rule as `budget-autosave.js`.
- **`FinishDialog.jsx`** (`common/Modal`):
  - Difference 0: "Reconciled. Your statement and Koala both say $4,182.19." Confetti
    (`common/confetti.js`, `'cannons'`).
  - Difference not 0: "Keep working" (the draft is already saved), or "Finish with a
    $12.75 adjustment", with a plain-language explanation of what the adjustment posts.
    The adjustment button is secondary, never the default.
- **`History.jsx`:** the per-account statement list, with **Intact** / **Changed**
  badges and **Undo** on every completed statement.

### 9.4 Adding a missing transaction (feed accounts only)
A missing bank fee is the most common real difference. For `has_feed` accounts,
"+ Add missing transaction" opens the existing `EditTransactionModal` in create mode (it
posts to the existing `feed/` create endpoint), and the new line appears already ticked.
For accounts without a feed this waits for **P1.2** (manual entry); until then the user
can finish with an adjustment.

---

## 10. Changes to existing code

| File | Change |
|---|---|
| `apps/bank_feed/services/splits.py` | §3.1: update counterpart lines in place; refuse to delete or re-amount a reconciled counterpart |
| `apps/bank_feed/views.py` | §3.2 guards in `update`. `batch_reconcile` either creates or extends a draft (D1) or is removed; the frontend then navigates instead of posting. `batch_unreconcile` keeps the `reconciliation` link and returns `affected_statements` for the D4 confirmation. `_create_reconciliation_adjustment` moves to `apps/reconciliation/services/adjustment.py`. |
| `apps/journal/views.py` | §3.3: `void_entry` calls `assert_entry_voidable` |
| `apps/journal/serializers.py` | §3.4: `update()` refuses `lines` when any existing line is reconciled |
| `BatchActionBar.jsx` | Remove the True Balance / adjustment dialog. **Reconcile** navigates to `/reconcile/<account>/?lines=…`. The Unreconcile confirmation names the affected statements. |
| `LineApp.jsx` | A "Reconcile" button in the "Lines for …" header. "Reconciled through Aug 31 ✓/⚠" uses the last statement and falls back to `latest_reconciled_date`. |
| `AccountCard.jsx`, `FeedAccountSerializer` | Add `last_statement_date` and `last_statement_intact`, computed in `_annotate_feed_account_activity` as a separate query (same reason as the existing ones: to avoid join fan-out) |
| `templates/accounts/account_detail.html` | A "Reconcile" button plus a statement history card |
| `apps/monthly_review/services/health.py` + `insights.py` | A new `STATEMENT_DUE` flag: an account with activity whose last statement is more than 45 days old (or that has none after 30 days of activity). The insight links to `/reconcile/<id>/`. |
| `apps/reports` home | A "Reconciliation status" link to the hub |
| `apps/portability/services/schema.py`, `export.py`, `apply.py`, `wipe.py` | D7: `RECONCILIATION` FieldMap, `reconciliations.csv`, a `reconciliation_id` column, a version bump, and a wipe-order test |
| `apps/audit/models.py` | Three event types plus migration `0009` |
| `common/amount.js` | `toCents()` |
| `docs/security-log.md`, `docs/testing-guide.md`, `CLAUDE.md` | Update as per house practice |

---

## 11. Test plan

**Backend unit tests.** New files `apps/reconciliation/tests/test_*.py`, using
`TestCase` with `setUpTestData`:
- `test_signs`: the §6.1 examples for an asset and a liability, and the adjustment
  direction for both.
- `test_candidates`: exclusion of void entries, archived feed rows, other accounts,
  already-reconciled lines, and another account's draft. The `include_later` window.
  Opening-balance lines are included.
- `test_session`: start refuses a non-balance account, a system account, and a date not
  after the last statement. A second start returns the same draft. `tick` and
  `tick_through` are idempotent and team-scoped. Finish at 0; finish with a difference
  and no adjust → 400; stale `expected_difference` → 409. A feed account's adjustment
  creates a feed row; a non-feed account's does not. `AuditLog` has a row per flipped
  line. Discard releases the ticks. Undo works on any completed statement, and it
  voids the adjustment.
- `test_integrity`: a statement stays intact after finishing, becomes Changed after one
  line is unreconciled, and drift names that line.
- `test_diagnose`: one test per rule in §7.5, plus the ranking and the 5-hint cap.
- `test_guards`: **the three confirmed defects written as failing tests before they are
  fixed** (§3.1–3.3), plus §3.4.
- `test_views`: happy path plus **permission tests**: anonymous is refused, another
  team's account or statement returns 404, and a member of a different team cannot tick
  a line from this team.
- Portability: the schema test passes; a round trip keeps statements and intact status;
  an archive from before the version bump imports with no statements.

**E2E.** `e2e/pages/reconcile.py` (POM) and `e2e/tests/test_reconcile.py`:
1. Chequing statement with a difference of 0 → finish → the hub shows Intact.
2. The duplicate-coffee example → a hint appears → untick → 0 → finish.
3. A credit card with the positive "balance owed" → 0 (the sign regression test).
4. Finish with an adjustment → the adjustment row appears in the feed, already
   reconciled.
5. Tick, reload, and the draft resumes with its ticks.
6. Select rows in the feed → Reconcile → they arrive ticked.
7. Unreconcile a statement's line in the feed → the confirmation names the statement →
   the hub shows Changed → a new session shows the drift banner.

As with the other E2E suites, write tests 6 and 7 **against the current feed first** to
pin down the Unreconcile behaviour, then change the feed.

---

## 12. Phases

| Phase | Scope | Days | Gate |
|---|---|---|---|
| 0 | Guards §3.1–3.4 plus their failing-first tests. `guards.py`. | 1–1.5 | The three reproduced defects now fail with a 400 |
| 1 | App, model, migrations, `signs`, `candidates`, `session`, `integrity`, adjustment move, audit events | 2 | Unit tests for all of them pass |
| 2 | API, pages, API-client regeneration | 1 | View and permission tests pass |
| 3 | Frontend: start form, workspace, finish, history; feed rewiring (D1) | 2.5 | Manual run-through with `/verify` |
| 4 | `diagnose.py` plus the hints UI | 1 | Rule tests pass |
| 5 | Entry points (feed, account detail, monthly review, reports hub), portability, E2E, docs | 1.5–2 | All 7 E2E tests pass; the full E2E suite stays green |
| | **Total** | **9–10** | |

**Why this is more than the report's 6–9 days:** the report assumed "every ingredient
exists". The guard gaps (Phase 0) and the portability requirement enforced by the schema
test (Phase 5) were not in its estimate. Without them the feature would promise that
reconciled lines are locked when they are not.

Phase 0 can ship as its own PR. It fixes live integrity bugs whether or not the rest is
built.

---

## 13. Out of scope

- Reading statements from PDF or OFX, or importing the closing balance automatically.
- Continuous reconciliation against Plaid's live balance. `PlaidAccount` stores no
  balance today; this is a natural P2 item.
- Reconciliation reminders by email or in-app. These belong to P0.4 and P1.5; this plan
  provides the `STATEMENT_DUE` signal they need.
- Any use of `is_cleared`.
- Posting adjustments to a category the user chooses (D5).
- Subset-sum matching of the difference.
- Adding a missing transaction on an account without a feed; this waits for P1.2.

---

## 14. Acceptance criteria

1. For any asset or liability account, a user can enter a statement date and balance,
   tick lines, and see the difference update on every tick. The difference is always
   shown in statement sign.
2. Finishing at $0.00 marks every ticked line reconciled, records the statement, and
   shows the "you're clear" confirmation.
3. Finishing with a difference requires an explicit adjustment. The adjustment posts to
   Reconciliation Adjustments with the correct sign for both assets and liabilities.
4. A draft survives a reload and a second household member opening it. Only one draft
   can exist per account.
5. With a non-zero difference, at least the §7.5 rules that apply are shown as hints.
6. The three confirmed defects in §3 are refused with a clear message.
7. Every completed statement reports Intact or Changed. Changed names the lines
   responsible.
8. The feed, the account detail page, the monthly review and the reports hub all lead to
   the flow. Feed account cards show "Reconciled through {date}".
9. Statements survive a data export followed by an import.
10. No `@mui` import, no hardcoded grays, `{% translate %}` on every string, and
    `text-base-content/70` for muted text.

---

## 15. Files — quick reference

**New:** `apps/reconciliation/{__init__,apps,models,urls,views,serializers}.py` ·
`apps/reconciliation/services/{signs,balances,candidates,session,integrity,diagnose,guards,adjustment}.py` ·
`apps/reconciliation/migrations/0001_initial.py` · `apps/reconciliation/tests/` ·
`apps/journal/migrations/0002_journalline_reconciliation.py` ·
`apps/audit/migrations/0009_…` · `templates/reconciliation/{hub,session,statement}.html` ·
`assets/javascript/reconcile/{reconcile-app,StartForm,Workspace,DifferenceHints,FinishDialog,History}.jsx` ·
`e2e/pages/reconcile.py` · `e2e/tests/test_reconcile.py`

**Changed:** see §10.

---

## 16. As built — where the code differs from this plan

- **D6** as above: any statement is undoable, and undo keeps each line's link.
- **More unguarded write paths than §3 listed**, all fixed through `guards.py`: bulk
  re-categorize (`_update_journal_category`) re-pointed a reconciled transfer
  counterpart; de-categorizing deleted it; `batch_edit` re-dated reconciled rows past
  their statement; `SimpleLineSerializer.update()` could move or re-amount a reconciled
  line. `batch_edit` now runs in one atomic helper so a refusal rolls back the batch.
- **`JournalEntry.SOURCE_RECONCILIATION`** (new choice, migration `journal.0002`) marks
  adjustment entries, so undo finds them without guessing and they travel in exports
  through the existing `source` column. The Transactions page badges them "Adjustment".
- **Feed handoff** passes journal entry ids (`?entries=`), not line ids: a feed row
  knows its entry, and the page maps each to the account's own line.
- **Hints**: a duplicate pair is one hint whose one-click fix unticks the later copy
  (`action_ids`), rather than an "untick it?" per copy plus a duplicate note.
- **API client**: the viewset is annotated for drf-spectacular (0 schema errors) and
  `api-client/` was regenerated with openapi-generator 7.9.0, which reproduced the
  committed client byte-for-byte apart from this feature's changes. The page itself
  uses a small hand-written `assets/javascript/reconcile/api.js`, the same pattern as
  the portability and YNAB wizards.
- **Portability**: `export.build_archive()` still returns three lists (a dozen call
  sites unpack it); statements come from `export.build_reconciliation_rows()` and are
  passed to `write.build_archive_bytes(reconciliations=...)`. Format version 2; a
  version-1 archive is read without the new file and column and upgraded by
  `upgrade.upgrade_1_to_2`. The integrity gate gains a `statements` check, compared
  only when the archive carries one.
- **Phone layout**: below `sm` the table shows one signed Amount column and puts the
  date under the payee.
