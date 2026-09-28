# Goal-linked accounts

Status: plan. Builds on `docs/goals-envelopes-plan.md` (allocated / spent / left) and the
v3 Unassigned formula (`docs/unassigned-plan.md` §1).

## 1. The idea

A goal may be **linked to one asset account** (e.g. "Emergency fund" ← "RBC HISA").
From the link's start date, money moving into that account raises the goal's
**allocated**; money moving out lowers it, by the same amount, in the month of the
transaction. It is one-way: manual assigns, withdrawals, closes and covers on the goal
never touch the account.

```
allocated = Σ manual GoalAllocation.amount  +  Σ linked contributions
left      = allocated − spent                        (unchanged)
```

## 2. Decisions to confirm

| # | Question | Recommendation |
|---|---|---|
| D1 | What counts as "money in/out"? | Every counted journal line on the account **except** where the other side is a spending category (an expense account or a goal account). So transfers, income deposits (interest, a paycheque landing there), and balance adjustments (opening balance, reconciliation adjustment) count; purchases and refunds don't. See §3. |
| D2 | Accounts per goal | One open link per goal and one per account in v1. The model stores date ranges, and the maths sums over links, so allowing several accounts per goal later is a constraint change only. |
| D3 | Which accounts can be linked | Non-system **asset** accounts only. A liability (paying a loan) would read as money set aside when it is money gone. |
| D4 | Past start dates | Allowed, with a preview of what the past activity adds to the goal and does to Unassigned. |
| D5 | Materialized or derived | **Derived** (computed from journal lines at read time), never written into `GoalAllocation`. See §4. |

## 3. Why spending categories are excluded (D1)

Unassigned = net worth + income due − envelopes − goals. Each case, with the account
`L` linked to goal `G`:

| Transaction | Net worth | Envelopes | G allocated | Unassigned | OK? |
|---|---|---|---|---|---|
| Transfer checking → L, $500 | 0 | 0 | +500 | −500 | ✓ money set aside |
| Transfer L → checking, $200 | 0 | 0 | −200 | +200 | ✓ money released |
| Transfer L → L2 (linked to G2), $300 | 0 | 0 | G −300, G2 +300 | 0 | ✓ |
| Credit card paid from L, $400 | 0 | 0 | −400 | +400 | ✓ money left the goal |
| Interest income into L, $10 | +10 | 0 | +10 | 0 | ✓ lands in the goal |
| Opening balance / reconciliation adjustment on L, ±X | ±X | 0 | ±X | 0 | ✓ |
| Car paid from L, categorized to goal G | −X | 0 | 0 (spent +X) | 0 | ✓ goal spending path |
| **Groceries paid from L, $100 — if it counted** | −100 | −100 | −100 | **+100** | ✗ money appears |
| Groceries paid from L, $100 — excluded | −100 | −100 | 0 | 0 | ✓ |

An expense already reduces its envelope's claim; reducing the goal's claim too
double-counts, and Unassigned rises by money that no longer exists. A line on a goal
account is goal spending (`spent`), which already reduces `left`.

Consequence: spending categorized to an expense from `L` makes the account balance and
the goal's `left` drift apart. That is shown, not corrected (§6.3).

If D1 is changed to "transfers only", the rule becomes "other side is an asset or a
liability"; nothing else in this plan changes.

## 4. Why derived (D5)

A linked contribution changes whenever a line on `L` is created, edited, re-dated,
re-categorized, split, voided, archived (via its `BankTransaction`), deleted or
bulk-imported. Several of those paths skip signals (`bulk_create` in the YNAB and
portability imports, `_raw_delete` in `wipe_book`, `QuerySet.update()` in
reconciliation, archive toggling a `BankTransaction` only). Keeping a stored column in
step means hooking every one of them and every future one; a missed hook is silent
drift in Unassigned. Computing from `JournalLine` + `counted_entries()` at read time is
correct by construction, matching how `spent` already works.

Cost: `GoalAllocation` rows no longer hold the whole allocation, so every read site that
sums them directly must go through one helper (§5.3).

## 5. Backend

### 5.1 Model — `apps/budget/models.py`

```python
class GoalAccountLink(BaseBookModel):
    goal = FK(Goal, CASCADE, related_name="account_links")
    account = FK(Account, PROTECT, related_name="goal_links")
    start_date = DateField()              # first day counted (inclusive)
    end_date = DateField(null=True)       # last day counted (inclusive); null = open
    # constraints:
    #   UniqueConstraint(book, goal) where end_date is null     (D2)
    #   UniqueConstraint(book, account) where end_date is null  (one goal per account)
    #   CheckConstraint end_date >= start_date
```

- Unlink sets `end_date`; the row stays, so past months keep their contributions.
- Ranges on one account must not overlap (service check: new `start_date` > the
  account's latest `end_date`).
- `PROTECT` on account: an account with journal lines is already undeletable; an
  account with none contributes nothing, so this only blocks deleting a linked empty
  account until it is unlinked.
- Register in `BOOK_MODELS` (`apps/books/tests/test_structure.py`).

### 5.2 Linked contributions — one definition

`goal_linked_subquery(start=None, end=None)` in `models.py`, beside
`goal_spent_subquery`. For each counted line `l` on a linked account, dated inside both
the link's range and `[start, end)`:

```
contribution(l) = round( (l.dr × C_cr − l.cr × C_dr) / T , 2 )

C_dr, C_cr = Σ dr / Σ cr of lines in l's entry on countable accounts
T          = Σ dr of l's entry
countable  = account type ∈ {asset, liability, income, equity} AND account has no Goal
```

This is the other side's countable share, applied to `l`:

- Two-line entry: `l`'s full amount if the other account is countable, else 0.
- Split where `L` is the bank line (e.g. L cr 150; groceries dr 100, checking dr 50):
  −150 × 50/150 = **−50**.
- Split where `L` is a leg (paycheque: checking dr 2,000, L dr 500, tax dr 500,
  income cr 3,000): +500 × 3,000/3,000 = **+500**.
- Only an entry with several lines on *both* sides (rare, manual journal) splits pro
  rata and can round; hence the per-line `round`.

A line with `T = 0` contributes 0.

`services.linked_contributions(book, goals, start, end)` → `{goal_id: {month: amount}}`,
the same expression grouped by `TruncMonth(entry_date)`, for per-month read sites.

### 5.3 Allocated everywhere goes through two helpers

1. `goal_allocated_subquery(start=None, end=None)` (signature changed from month
   lookups to a date range, matching `goal_spent_subquery`) = manual + linked. Callers:
   `GoalQuerySet.with_progress` (`saved_previous`, `saved_this_month`, `allocated`) and
   `compute_unassigned` (`allocated_to_date`). Everything built on those — `left`,
   `remaining`, `to_fund`, `progress_percentage`, `state`, the Dollar Map, the dashboard,
   quick-assign clamp, withdraw cap, close/cover — follows with no further change.
2. `goal_monthly_allocations(book, goals, start=None, end=None)` →
   `{goal_id: {month: {"assigned", "linked", "total"}}}`. Replaces the direct
   `GoalAllocation` reads:

| Site | Use |
|---|---|
| `budget/views.py` `goals_list_view` (streaks) | `total > 0` months |
| `budget/views.py` `goal_detail_view` (last 12 months) | show assigned and linked columns |
| `budget/services.py` `get_total_saved` | via `with_progress` (or delete if unused) |
| `monthly_review/services/review.py` (window allocations; `months_funded`) | `total` |
| `reports/services.py` goal account allocated-vs-spent chart | `total` |
| `reports/views.py` Goal Progress cumulative line | `total` |

A test greps `apps/` for `GoalAllocation.objects` outside writers and these helpers, so
a new direct read fails.

Writers are unchanged: `add_to_allocation`, assign-available, withdraw, close, cover all
write manual rows.

### 5.4 Link service — `apps/budget/services/goal_links.py` (or `GoalService`)

- `link(goal, account, start_date, assign_existing=False)`: all refusals raise a
  user-facing `ValueError` before writing:
  - account not in this book, not an asset, `is_system`, archived;
  - account already in an open link; goal already linked (D2); goal closed/archived;
  - `start_date` after today, or overlapping the account's previous link.
  - `assign_existing=True` adds a manual allocation, in `start_date`'s month, equal to
    the account's balance through `start_date − 1` (only if positive).
  - Audit `GOAL_ACCOUNT_LINKED` `{goal, account, start_date, assigned_existing}`.
- `unlink(goal, end_date=today)`: sets `end_date`; audit `GOAL_ACCOUNT_UNLINKED`.
- `preview(goal, account, start_date)`: `{balance_before_start, past_activity,
  unassigned_before, unassigned_after, unassigned_after_with_existing}` — the
  Unassigned figures via `compute_unassigned` on an unsaved link (pass the proposed link
  into the subquery helper, or compute the delta = linked total + optional existing).
- Changing the linked account on edit = `unlink` today + `link` from today.
- `GoalService.close_goal` and archive (which closes first) call `unlink(goal,
  end_date=close date)` **before** computing what to release, so the release uses the
  final `left`.
- Audit migration for the two event types.

### 5.5 Endpoints

| Route | View | Notes |
|---|---|---|
| `goals/new/`, `goals/<pk>/edit/` | existing | `GoalForm` gains `linked_account`, `link_start_date`, `assign_existing` |
| `GET goals/link-preview/?goal=&account=&start=` | `goal_link_preview` | JSON for the form |
| `POST goals/<pk>/unlink/` | `goal_unlink` | JSON + no-JS redirect |

All `login_and_book_required`; account lookups `for_book`. Add all three to
`apps/books/tests/test_isolation.py` (`goal_link_preview` → READS with an account id
from the other book refused; `goal_unlink` → OBJECTS).

## 6. Frontend

### 6.1 Goal form (`templates/budget/goal_form.html`)

- **Linked account** select, optional: eligible asset accounts grouped by account group,
  each showing its balance; accounts linked to another goal listed disabled with "Feeds
  {goal}".
- **Count activity from** (shared `date-field`, default today; hidden until an account
  is picked).
- **Also assign the $X already in {account}** checkbox.
- A preview line refreshed from `goal-link-preview` (debounced, newest-response-wins):
  "Past activity adds $A. Unassigned goes from $B to $C." Shown red when $C < 0 (the
  link is still allowed: over-assigned is a state the app already handles).
- No-JS: fields post normally; the preview is omitted.

### 6.2 Goal cards and detail

- Card (all three styles): a small "Linked · {account}" chip under the name.
- Detail page: link history (account, from, to, Unlink button), and the monthly table
  splits **Assigned** / **From {account}** / **Spent**.

### 6.3 Drift line (detail page only)

"{Account} holds $X; this goal has $Y left." when they differ, with the reasons that
apply, computed from the same data: spending from the account categorized elsewhere,
manual assigns/withdrawals, activity before the start date, uncategorized feed rows
(not in the ledger yet). No "match" action in v1.

### 6.4 Account detail

"Feeds goal: {goal} since {date}" with a link to the goal. The accounts board gets no
change.

### 6.5 Feedback when it happens

Categorizing a transfer into `L` already triggers the Unassigned pill's delta chip
(`unassigned-pill.js` re-reads after any non-GET), so the effect is visible with no
per-feature wiring.

## 7. Reports, review, portability

- Budget vs Actual Goals section: "assigned" = total (tooltip splits linked).
- Goal Progress, goal-account activity chart, monthly review: via
  `goal_monthly_allocations` (§5.3).
- Dollar Map: `detail["goals"]` gains `linked`.
- **Portability format v4**: new `goal_links.csv` (`goal_id, account_id, start_date,
  end_date`), a `FieldMap` for `GoalAccountLink` in `schema.py`, `FILES_ADDED_IN[4]`,
  `upgrade_3_to_4` (no file = no links). `_verify()` needs no change (links don't move
  balances). `wipe_book` reports the count.
- User data export (`apps/users/services.py`): add `goal_links.csv`.
- YNAB import, onboarding: no change.

## 8. Tests

`apps/budget/test_goal_links.py`:

- Every row of the §3 table, asserting goal allocated/left and Unassigned.
- Split cases from §5.2 (bank-line and leg), and a both-sides-multiple entry.
- Not counted: dated before `start_date`, after `end_date`, after the viewed month;
  void; behind an archived `BankTransaction`; uncategorized feed row.
- Deleting/voiding the transfer removes the contribution.
- Unlink keeps past months; activity after unlink doesn't count.
- Close ends the link, then releases the final `left` (linked included).
- Manual assign/withdraw on a linked goal leaves the account balance unchanged.
- `assign_existing` writes one manual allocation equal to the prior balance.
- Refusals: other book's account, liability, system, already linked, closed goal,
  future start, overlapping range.
- Streak, Goal Progress series and monthly review read linked months.
- Transfer mirror: categorizing a checking row as a transfer to `L` counts once.
- Portability round-trip with a link; v3 archive imports with no links.
- Isolation table entries; `BOOK_MODELS` entry.

E2E (`e2e/tests/test_goals.py`): link an account on the goal form with the preview,
categorize a transfer into it in the Inbox, see the goal and the Unassigned pill move;
unlink from the detail page.

Performance: benchmark `with_progress` and `compute_unassigned` on the YNAB sample book
with its savings account linked; add an index on `GoalAccountLink(account, end_date)` if
needed (lines on `L` already use the `JournalLine.account` FK index).

## 9. Milestones

1. **M1 model + service**: `GoalAccountLink`, migration, link/unlink/preview, audit
   events, refusals, tests.
2. **M2 maths**: `goal_linked_subquery`, `goal_allocated_subquery` range signature,
   `goal_monthly_allocations`, every read site in §5.3 moved, §3 matrix tests.
3. **M3 UI**: goal form + preview endpoint, cards chip, detail page (history, split
   table, drift line), account detail, unlink endpoint, isolation entries.
4. **M4 reports + portability**: §7, format v4.
5. **M5 E2E** and `CLAUDE.md` Recent Changes entry.

## 10. Out of scope

- Several accounts per goal (D2) and liability links (D3).
- A "match goal to account balance" action.
- The reverse direction (goal actions moving money between accounts).
- Suggesting a link during onboarding or YNAB import.
