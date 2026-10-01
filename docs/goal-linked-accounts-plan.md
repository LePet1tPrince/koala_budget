# Goal-linked accounts

Status: built (M1–M5), revision 2. D6 ("Leave the goal alone") was approved with the
plan and is built. Builds on `docs/goals-envelopes-plan.md` (allocated / spent /
left) and the v3 Unassigned formula (`docs/unassigned-plan.md` §1). Inspired by
Monarch's Save Up goal (Goals 3.0), trimmed to fewer options (§9).

## 1. The idea

A goal can be **linked to one or more asset accounts** ("the money for this goal lives
in these accounts"). From each link's start date:

- **Money arriving** in a linked account **adds to the goal's allocation**: transfers in,
  income landing there (interest, a paycheque), balance adjustments.
- **Money leaving** for another of your accounts does what the goal's **outflow setting**
  says (§3): take it out of the goal (default), or count it as spent from the goal.
- Optionally (default on), the **balance already in the account** at the start date
  counts as the goal's starting balance.

It is one-way: assigning, withdrawing, closing or covering a goal never touches its
accounts.

```
allocated = Σ manual GoalAllocation.amount + starting balances + linked inflows − linked withdrawals
spent     = Σ lines on the goal's equity account + linked spending
left      = allocated − spent
```

## 2. Decisions (confirmed)

| # | Decision |
|---|---|
| D1 | Default: any money arriving counts. Outflows to your other accounts: the user chooses per goal, between "take it out of the goal" and "count it as spent". |
| D2 | Several accounts per goal. An account feeds at most one goal at a time (its whole balance belongs to that goal). |
| D3 | Asset accounts only (non-system). |
| D4 | Start dates may be in the past. The form previews what the past activity adds. |
| D5 | Linked amounts are **derived** from journal lines at read time, never written into `GoalAllocation` (§6). |

### Needs your OK

**D6: a third outflow choice, "Leave the goal alone".** The app already lets you
categorize a purchase to a goal, including one made on a credit card. If you then pay
that card from the linked account, the payment is a transfer out, and both existing
choices reduce the goal a second time:

| Step | Take it out | Count as spent | Leave alone |
|---|---|---|---|
| $2,000 flight on the card, categorized to "Trip" | spent +2,000 | spent +2,000 | spent +2,000 |
| Card paid $2,000 from the linked account | allocated −2,000 | spent +2,000 | — |
| Trip's left | **−4,000 (wrong)** | **−4,000 (wrong)** | −2,000 ✓ |

Recommendation: add the third choice, worded for this case: *"Leave the goal alone —
I categorize what I buy to the goal."* If you'd rather keep two choices, the fallback is
a warning when a purchase is categorized to a linked goal from an account the goal
isn't linked to: "Paying this from {account} will reduce {goal} again."

## 3. What each transaction does

For a line on a linked account `L` (goal `G`), the transaction's **other side** decides:

| Other side | Money arriving in L | Money leaving L |
|---|---|---|
| Your account linked to **no goal** (checking, card, loan) | allocated + | **per outflow setting** |
| Your account linked to **another goal** `G2` | allocated + (G2: per its rule) | allocated − always (moving money between goals is a reallocation, not spending) |
| Your account linked to the **same goal** | nothing (internal move) | nothing |
| Income category | allocated + | allocated − (an income reversal) |
| Equity, not a goal (opening balance, reconciliation adjustment) | allocated + | allocated − |
| **Expense category** | nothing (a refund goes back to its own envelope) | nothing (the envelope already paid it) |
| **Goal account** | nothing (a refund of goal spending: spent goes down) | nothing (goal spending: spent goes up) |

Outflow setting, for transfers to an account linked to no goal:

| Setting | Effect | Progress bar | For |
|---|---|---|---|
| **Take it out of the goal** (default) | allocated − | goes down | goals you refill: emergency fund |
| **Count it as spent from the goal** | spent + | stays | goals you spend once: a trip, a car |
| *Leave the goal alone* (D6) | nothing | stays | you categorize purchases to the goal |

### Why expense lines never count

Unassigned = net worth + income due − envelopes − goals. Groceries paid from `L`,
$100: net worth −100 and the Groceries envelope's claim −100. If the goal also lost 100,
claims would fall by 200 against 100 of real money, and Unassigned would rise by money
that no longer exists. A refund into `L` is the same in reverse. To pay for something
*from the goal*, categorize it to the goal.

### Unassigned check (default settings)

| Transaction | Net worth | G | Unassigned |
|---|---|---|---|
| Checking → L, $500 | 0 | allocated +500 | −500 (set aside) |
| L → checking, $200 | 0 | allocated −200 (spend: spent +200) | +200 |
| Interest into L, $10 | +10 | allocated +10 | 0 |
| L → L2 linked to G2, $300 | 0 | G −300, G2 +300 | 0 |
| L1 → L2, both linked to G | 0 | nothing | 0 |
| Groceries from L, $100 | −100 | nothing (Groceries envelope −100) | 0 |
| Car from L, categorized to G | −X | spent +X | 0 |
| Reconciliation adjustment on L, −$5 | −5 | allocated −5 | 0 |

"Take it out" and "count as spent" both lower `left` by the same amount, so they never
differ in Unassigned, only in the progress bar and history. "Leave alone" keeps the
claim until the purchases are categorized to the goal.

### Drift

A goal's `left` and its accounts' total balance diverge when: an expense is paid from a
linked account, a refund lands there, the user assigns or withdraws manually, money is
spent from the goal through an unlinked account, or an account's transactions are
still uncategorized. The detail page shows the gap with its causes (§7.3).

## 4. Data model — `apps/budget/models.py`

```python
class Goal:
    outflow = CharField(choices=[("withdraw", …), ("spend", …), ("ignore", …)], default="withdraw")
    monthly_contribution = DecimalField(null=True, blank=True)    # §9, optional plan

class GoalAccountLink(BaseBookModel):
    goal = FK(Goal, CASCADE, related_name="account_links")
    account = FK(Account, PROTECT, related_name="goal_links")
    start_date = DateField()                   # first day counted, inclusive
    end_date = DateField(null=True)            # last day counted, inclusive; null = open
    include_starting_balance = BooleanField(default=True)
    # UniqueConstraint(book, account) where end_date is null    (D2: one goal per account)
    # CheckConstraint end_date >= start_date
```

- Unlinking sets `end_date`; the row stays, so past months keep what the account added.
- Ranges on one account never overlap (service check).
- `PROTECT`: an account with journal lines is already undeletable; this only blocks
  deleting an empty linked account until it is unlinked.
- The starting balance is **derived**, not snapshotted: the account's counted balance
  through `start_date − 1`, credited in `start_date`'s month. If an old transaction is
  later edited, the starting balance follows, as the account would.
- `outflow` applies to the goal's whole history (it is derived). Switching between
  "take out" and "spent" never changes Unassigned; switching to or from "leave alone"
  does, and the form previews it.
- Register `GoalAccountLink` in `BOOK_MODELS`; budget migration for both models.

## 5. Linked flows — one definition

`apps/budget/linked.py::linked_lines(book)` — a `JournalLine` queryset of counted lines
on linked accounts, each dated inside its link's range, annotated with:

```
goal_id, month
alloc_delta, spent_delta
```

Per line `l` (amount `in = l.dr`, `out = l.cr`), with `T` = the entry's total debits and
each class share = that class's amount on the **opposite** side ÷ `T`:

```
free    = asset/liability linked to no goal on that date
other   = asset/liability linked to another goal on that date
income  = income account
adjust  = equity account with no Goal
(same-goal accounts, expense accounts and goal accounts: share ignored)

alloc_delta = round(in  × (free + other + income + adjust)
                  − out × (other + income + adjust)
                  − out × free × [outflow = withdraw], 2)
spent_delta = round(out × free × [outflow = spend], 2)
```

The share form handles splits without special cases: a two-line entry is all one
class; a split where `L` is the bank line (L cr 150; groceries dr 100, checking dr 50)
gives −50; a split where `L` is a leg (paycheque into checking with $500 to L) gives
+500. Only an entry with several lines on both sides (a manual journal) splits pro rata
and can round; hence `round` per line. `T = 0` contributes 0.

Starting balances are added as a second source in the same module.

Two consumers, both built on it:

1. **Scalar subqueries** for annotations: `goal_allocated_subquery(start, end)` (manual
   + starting balances + `alloc_delta`; signature changes from month lookups to a date
   range, matching `goal_spent_subquery`) and `goal_spent_subquery(start, end)` (goal
   account lines + `spent_delta`). Callers: `GoalQuerySet.with_progress`,
   `compute_unassigned`. Everything built on them — `left`, `remaining`, `to_fund`,
   progress, state, the Dollar Map, dashboard, quick-assign clamp, withdraw cap,
   close/cover — follows unchanged.
2. **`goal_monthly(book, goals, start, end)`** → `{goal_id: {month: {assigned, linked,
   spent}}}`, replacing every direct `GoalAllocation` read:

| Site | Use |
|---|---|
| `budget/views.py` `goals_list_view` (streaks) | `assigned + linked > 0` |
| `budget/views.py` `goal_detail_view` | activity (§7.2) |
| `budget/services.py` `get_total_saved` | via `with_progress`, or delete if unused |
| `monthly_review/services/review.py` (window; `months_funded`) | `assigned + linked` |
| `reports/services.py` goal-account allocated-vs-spent chart | all three |
| `reports/views.py` Goal Progress | all three |

A test fails on any `GoalAllocation.objects` read outside writers and these helpers.

The income statement's goal-spending section keeps reading goal-account lines only:
linked "spending" is a transfer between your own accounts, not an expense. The goal
page's `spent` includes it.

## 6. Why derived

A linked flow changes whenever a line on a linked account is created, edited,
re-dated, re-categorized, split, voided, archived (through its `BankTransaction`),
deleted or bulk-imported. Several of those paths skip signals (`bulk_create` in the
YNAB and portability imports, `_raw_delete` in `wipe_book`, `QuerySet.update()` in
reconciliation, archive changing only the `BankTransaction`). A stored figure would
need a hook on each, and a missed one is silent drift in Unassigned. Derived from
`JournalLine` + `counted_entries()` it is correct by construction, as `spent` already is.

Performance: only lines on linked accounts are read. Benchmark `with_progress` and
`compute_unassigned` on the YNAB sample book with its savings accounts linked; index
`GoalAccountLink(account, start_date)` if needed.

## 7. Frontend

### 7.1 Goal form (create and edit, `templates/budget/goal_form.html`)

Three sections, nothing else added:

1. **Goal**: name, target amount, description.
2. **Plan** (§9): target date *or* monthly contribution; the other is computed and
   shown ("$400/month reaches $10,000 by Mar 2028").
3. **Where the money lives** (optional):
   - Account checklist: eligible asset accounts by group, each with its balance;
     accounts feeding another goal are disabled with "Feeds {goal}".
   - Per ticked account: **Count from** (shared `date-field`, default today) and
     **Include the $X already there** (default on).
   - **When money moves out of these accounts to your other accounts:** radio, the
     options in §3, default "Take it out of the goal". Shown once any account is ticked.
   - Preview, refreshed from `goal-link-preview` (debounced, newest response wins):
     "Adds $A to this goal. Unassigned goes from $B to $C." Red when $C < 0; still
     allowed.

No-JS: fields post normally; no preview.

### 7.2 Goal detail page

- **Activity** (Monarch's event list): one row per event, newest first — *Assigned* /
  *Withdrawn* (manual allocations, by month), *Starting balance from {account}*, *From
  {account}* and *Moved out of {account}* (each linked line, linking to the
  transaction), *Spent* (goal-account lines and linked spending), *Adjustment*
  (equity counter lines).
- **Accounts**: each link with dates and an Unlink button; the outflow setting.
- **Drift line**: "Your linked accounts hold $X; this goal has $Y left", with the
  causes from §3 that apply.

### 7.3 Goal cards (all three styles)

A status pill (§9) and a "Linked · {account}, {account}" line under the name.

### 7.4 Account detail

"Feeds goal: {goal} since {date}", linking to the goal.

### 7.5 Feedback

Categorizing a transfer into a linked account already triggers the Unassigned pill's
delta chip (`unassigned-pill.js` re-reads after any non-GET).

## 8. Backend services and endpoints

`apps/budget/services/goal_links.py` (or `GoalService`):

- `set_links(goal, rows)`: rows of `{account, start_date, include_starting_balance}`;
  diffs against the open links — removed accounts end today, new accounts link, a
  changed start date or starting-balance flag updates the open row. Refusals (a
  user-facing `ValueError`, nothing written): account not in this book, not an asset,
  system, archived, open-linked to another goal, start date after today or overlapping
  the account's previous link; goal closed or archived.
- `preview(goal, rows, outflow)`: `{adds, unassigned_before, unassigned_after}`.
- `unlink(link, end_date=today)`.
- Closing or archiving a goal ends its links at the close date **before** computing
  what to release, so the release uses the final `left`.
- Audit events `GOAL_ACCOUNT_LINKED`, `GOAL_ACCOUNT_UNLINKED`,
  `GOAL_OUTFLOW_CHANGED` (audit migration).

| Route | View | Isolation table |
|---|---|---|
| `goals/new/`, `goals/<pk>/edit/` | existing, `GoalForm` extended | existing |
| `GET goals/link-preview/` | `goal_link_preview` | READS (other book's account id refused) |
| `POST goals/<pk>/links/<link_pk>/unlink/` | `goal_unlink` | OBJECTS |

## 9. From Monarch's Save Up goal

Source: Monarch help center "Introducing Goals 3.0", "Using Save Up Goals", "Moving
Funds In and Out of Goals" (via search excerpts; the pages themselves were not
reachable from this environment).

| Monarch | Here |
|---|---|
| "Use the entire balance and future activity" of an account for one goal | **Adopted** as the link with starting balance on (default) |
| Several accounts per goal | **Adopted** (D2) |
| "Spending reduces goal progress" toggle (on for refill goals, off for one-time) | **Adopted** as the outflow setting, same wording intent |
| Spend from a goal, including on a credit card | Exists (categorize to the goal) |
| Event list: Contribution, Withdrawal, Adjustment | **Adopted** as the activity list (§7.2) |
| Target amount, target date, planned monthly contribution | **Adopted**: date *or* monthly, the other computed. New optional `Goal.monthly_contribution`; Budget vs Actual's "needed this month" uses it when set, else the existing pace |
| Status: on track / ahead / at risk | **Adopted** as a pill: *Ahead* (allocated ≥ the plan's straight line to date), *On track* (this month's assigned + linked ≥ needed), *Behind* otherwise; none without a plan |
| "Available for goals" (unallocated account balances) | Skipped: Unassigned already is this, across all money |
| Link individual income/transfer transactions to a goal, rules | Skipped: account links cover it |
| Pay Down goals, growth rates, goal images, global account toggles | Skipped |

## 10. Reports, review, portability

- Budget vs Actual Goals section: assigned = assigned + linked (tooltip splits them).
- Goal Progress, goal-account chart, monthly review: via `goal_monthly`.
- Dollar Map `detail["goals"]` gains `linked`.
- **Portability format v4**: `goal_links.csv` (`goal_id, account_id, start_date,
  end_date, include_starting_balance`), `goal_outflow` and `goal_monthly_contribution`
  columns on `accounts.csv`, `FieldMap`s in `schema.py`, `upgrade_3_to_4` (no links,
  outflow `withdraw`, no monthly contribution). `_verify()` unchanged (links don't move
  balances). `wipe_book` counts links.
- User data export (`apps/users/services.py`): add `goal_links.csv`.
- YNAB import, onboarding: no change.

## 11. Tests

`apps/budget/test_goal_links.py`:

- Every cell of §3's two tables, each asserting allocated, spent, left and Unassigned,
  under each outflow setting.
- The D6 card-payment sequence under each setting.
- Splits: bank line, leg, both-sides-multiple.
- Starting balance: on/off, follows an edit to a pre-start transaction, retroactive
  start date.
- Not counted: before start, after end, after the viewed month, void, behind an
  archived `BankTransaction`, uncategorized feed row; deleting the entry removes it.
- Transfer mirror: a transfer categorized from checking counts once.
- Unlink keeps past months; close ends links, then releases the final `left`.
- Manual assign/withdraw leaves account balances unchanged.
- Outflow switch: take-out ↔ spent leaves Unassigned unchanged; to leave-alone changes it.
- Refusals (each from §8).
- Streak, Goal Progress, monthly review read linked months.
- Plan: date ↔ monthly computation; status pill thresholds.
- Portability round trip with links; v3 archive imports.
- Isolation table entries; `BOOK_MODELS`.

E2E (`e2e/tests/test_goals.py`): create a goal linked to two accounts with the preview;
categorize a transfer into one in the Inbox and see the goal and the Unassigned pill
move; switch the outflow setting; unlink.

## 12. Milestones

1. **M1 model + service**: `GoalAccountLink`, `Goal.outflow`, `Goal.monthly_contribution`,
   migrations, `set_links`/`unlink`/`preview`, refusals, audit events.
2. **M2 maths**: `linked.py`, subquery signatures, `goal_monthly`, every §5 read site
   moved, §3 test tables.
3. **M3 UI**: goal form (three sections, preview endpoint), detail page (activity,
   accounts, drift), cards (status, linked line), account detail, unlink endpoint,
   isolation entries.
4. **M4 reports + portability**: §10, format v4.
5. **M5 E2E** and `CLAUDE.md` Recent Changes entry.

## 13. Out of scope

- Liability links (D3), "Available for goals", per-transaction goal links and rules.
- A "match goal to account balance" action.
- Goal actions moving money between accounts.
- Suggesting links during onboarding or the YNAB import.

## 14. What the build changed

- **Format version 5, not 4**: version 4 was taken by `hidden_from_budget` while this
  was being planned.
- **Unlink URL** is `POST goals/links/<link_pk>/unlink/` (the link names its goal), so
  the isolation suite's one-id `OBJECTS` table covers it.
- **Unlinking an account linked the same day drops the link** instead of ending it,
  so a mistake fixed straight away leaves nothing behind.
- **Plan status** measures from the goal's creation month, or the viewed month when
  that is earlier.
- Not built: splitting assigned vs linked in Budget vs Actual's tooltip, and a separate
  `linked` figure in the Dollar Map (both already include linked money in their totals).
- `BOOK_MODELS` is now the frozen `BACKFILLED_BOOK_MODELS` (what `books.0003`
  backfills) plus models created with a `book` column from the start.
