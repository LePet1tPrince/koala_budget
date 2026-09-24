# Goals as envelopes

Status: built (M1–M5), see §9 for what the build decided or changed. Implements Phase 2 §4
of `docs/unassigned-plan.md` and the "goal spending tracking" that `docs/goals_design.md`
left out of scope.

## 1. The idea

A goal is a budget envelope that never resets. Saving is an **allocation** of
unassigned money; spending is a **real transaction categorized to the goal**.

```
Budget category:  available = Σ budgeted  − Σ spent      (rolls over monthly)
Goal:             left      = Σ allocated − Σ spent      (same maths, plus a target)
```

Spending from a goal lowers net worth and the goal's claim by the same amount, so
**Unassigned doesn't move when you spend money you saved for** — a $20,000 car
behaves exactly like $84 of budgeted groceries.

On the income statement, goal spending is its own section below the operating net,
like capital spending: a real outflow, but not an everyday expense, so the month
you buy the car doesn't read as a −293% savings rate.

### Decisions already made (unassigned-plan §2, §4)

- Goals **stay equity accounts**; no account-type migration.
- **Overspending is carried**: a goal can go negative (red) and stays that way until
  the user chooses to cover it. Nothing is forced.
- **Spend it** (categorize the purchase to the goal) is the v1 flow. **Own it**
  (buying an asset and keeping a claim on it) is later.
- **Loans**: the whole purchase is spent from the goal; paying the loan back is the
  user's to model — keep allocating to the (now negative) goal, or set up a new goal
  for the payoff, splitting interest from principal themselves. No special machinery.
- Operating expenses and goal spending are reported separately everywhere.
- **Not every equity account is a goal**: opening-balance and other equity accounts
  stay plain equity. But **every goal has an equity account**.
- **Pay yourself first**: Budget vs Actual leads with a Goals section, above income.
- **Balance sheet**: plain equity (opening balances) stays; spending from a goal does
  not appear there. Money moved from a goal into an asset or liability shows up on
  that account as usual.
- **Not building yet**: moving a negative goal balance into a new goal.

## 2. What exists today

- `Goal` (`apps/budget/models.py`) is backed by a one-to-one equity `Account`
  ("Goal: <name>"). **The equity account type is stored as the string `"goal"`**
  (`ACCOUNT_TYPE_EQUITY = "goal"`, shown as "Goals"), so every account picker already
  presents every equity account as a goal.
- Goal progress is `Σ GoalAllocation.amount` only (`GoalQuerySet.with_progress`). Journal
  lines posted to the goal's account are ignored.
- Goal accounts **can already be picked as categories** almost everywhere: categorize
  mode, the edit / bulk-edit / split modals, reconcile's "add missing transaction", CSV
  mapping, the budget page's "Move to…" picker. No server endpoint restricts a
  category's type. So spending "from" a goal is possible today — and currently wrong:
  net worth drops while the goal still claims the full amount, so **Unassigned falls
  by the whole purchase**, and the spending appears on no report except the balance
  sheet's equity section.
- **The system "Reconciliation Adjustments" equity account is offered as a category**
  in every picker except "Move to…" (the only place that filters `is_system`;
  `SimpleAccountSerializer` doesn't expose the flag).
- **Goal accounts often land in the system group.** `Goal.save()` looks for a group
  named "Goals" and otherwise falls back to the *lowest-id equity group* — on template
  and generated charts that is the system "Equity Adjustments" group. Onboarding guards
  against it; `goal_create_view` and the YNAB import don't.
- `create_account` (bank feed) can create an equity account with no `Goal` row — which
  is fine: plain equity (e.g. opening balances) is legitimate and stays that way.
- `is_complete` means "marked done": it hides the goal from `active()` (dashboard only),
  blocks quick-assign, but its allocations still count toward Unassigned.
- YNAB import: spending from a savings category posts to a **same-named expense
  account**, never to the goal; a savings category that was spent out entirely is
  skipped rather than imported.

## 3. Three numbers per goal

| Name | Definition | Used for |
|---|---|---|
| **allocated** | `Σ GoalAllocation.amount` (withdrawals are negative allocations) | funding progress: `funded % = allocated / target`, `to fund = target − allocated` |
| **spent** | `Σ (dr − cr)` of counted journal lines on the goal's account, through the end of the month being viewed (`counted_entries()`: not void, not archived) | the spending history; refunds (credits) reduce it |
| **left** | `allocated − spent` | the goal's claim in Unassigned, the "left in goal" figure, what can be withdrawn |

Progress bars and quick-assign use **allocated**, not left: once the car is bought the
koala should not slide back down to 3% and the quick-assign button should not ask you
to refill a goal you've finished with. `to fund` stays `target − allocated`.

"Through the end of the month" keeps `spent` consistent with net worth, which
`compute_unassigned` measures as of month end. (Allocations stay all-time, as today.)

**What is a goal account:** exactly the account a `Goal` row points at
(`Account.objects.filter(goal__isnull=False)`) — never "any equity account". Plain
equity accounts (opening balances, the system reconciliation account, anything else a
user creates in the equity group without a goal) are not goals: they don't show under
Goals, they aren't goal spending on the income statement, and they stay on the balance
sheet. Because the stored equity type is `"goal"`, nothing may infer goal-ness from the
account type; every check goes through the `Goal` relation.

## 4. Changes

### 4.1 Account integrity (prerequisite)

- `Goal.save()` always uses a **non-system** "Goals" group, creating it if missing;
  it never falls back to another equity group. A data migration moves existing goal
  accounts out of the system group into "Goals" (a group change only; no type change).
- **The system account leaves every category picker.** Server-side account lists for
  categorize mode, the bank feed, reconcile and CSV mapping exclude `is_system`
  accounts, and `SimpleAccountSerializer` exposes `is_system` so the client can't
  reintroduce it. The category-accepting endpoints (`categorize`, feed
  create/update/batch edit, `parse_legs`, `recategorize`, the journal line
  serializer) refuse a system account as a category.
- **Every goal has an equity account.** `Goal.save()` already creates one; the bulk
  paths that skip `save()` (portability import `bulk_create`, and anything added later)
  must supply it, and a test asserts no `Goal` lacks an account after each import path.
  The reverse is *not* enforced: plain equity accounts without a goal stay allowed.
- **Goals and plain equity are told apart in the UI.** The equity type's label
  ("Goals") currently covers opening-balance accounts too. Pickers and the accounts
  board group accounts with a `Goal` under **Goals** and the rest under **Equity**
  (display only; the stored type stays `"goal"`).

### 4.2 Goal maths and Unassigned

- `GoalQuerySet.with_progress(month)` adds `spent` (a scalar subquery over counted
  `JournalLine`s on `OuterRef("account")`, through month end) and `left`; keeps
  `total_saved` as an alias of `allocated` for one release so templates can move over.
- `compute_unassigned`: the goals term becomes Σ **left**. The `Unassigned` dataclass
  gains `goals_spent`; `goals = goals_before + goals_this_month − goals_spent`; the
  waterfall gains a "Spent from goals" step (it is already out of net worth, so it adds
  back); `detail["goals"]` carries allocated/spent/left per goal. The Dollar Map and
  `allocation_bar` already treat a negative goal as carried overspending.
- `goal_withdraw` caps at **left** (you can't withdraw money already spent);
  `goal_assign_available` keeps `min(available, target − allocated)`. Both responses
  add `spent` and `left`.
- Dashboard "To reach all goals" = `Σ max(target − allocated, 0)` over open goals.

### 4.3 States

Derived, except one stored fact:

| State | Rule |
|---|---|
| **Saving** | open, allocated < target, nothing spent |
| **Funded** | open, allocated ≥ target (or `is_complete` set by the user), nothing spent — stops asking for money, still holds its claim |
| **Spending** | open, spent > 0 |
| **Closed** | `closed_at` is set |

- New field `Goal.closed_at` (nullable). **`is_complete` keeps its data and is
  reinterpreted as "funded — stop asking for money"**, which is what users meant by
  marking a goal complete; their money stays claimed, so deploy changes nobody's
  Unassigned through this field.
- **Close** (`POST goals/<pk>/close/`, audit event `GOAL_CLOSED`):
  - left > 0 → release it (a negative allocation this month, like withdraw), then close;
  - left < 0 → the user picks: **cover** it from Unassigned (a positive allocation) or
    **leave it open** (carried, e.g. paying back a loan). A goal can't close negative.
  - Closed goals move to a "Closed" filter on the Goals page, with their history.
- Archive stays "hide"; archiving an open goal with money in it closes it first.

### 4.4 Spending from a goal

- Pickers group goals under "Goals" with their balance: "Car · $600 left". A
  non-blocking hint when an amount exceeds what the goal holds: "Car will go to
  −$1,500 — that's fine, it's carried".
- **Cover from goal** on an overspent budget row: pick a goal and an amount; one
  endpoint, one transaction, writes a negative allocation on the goal and raises the
  category's budget for the month by the same amount (so Unassigned is unchanged).
  This is how buffer goals (emergency fund) get used.
- A goal's card and detail page list its spending (the goal account's lines), linking
  to the Transactions page filtered to that account.

### 4.5 Reports

- **Income statement** — `get_income_statement_data` also returns `goal_spending`
  (items, per-period columns, total) from goal accounts only:
  ```
  Income                                   6,000
  Expenses                                 4,200
  Net before goal spending                 1,800   ← savings rate uses this
  Goal spending — planned, paid from goals 19,400
    Car                                   19,400
  Net after goal spending                −17,600
  ```
  Collapsible like the other sections, in the By Month/Quarter/Year views and the CSV
  export. Rows drill down to the account activity page, which treats a goal account like
  an expense (period totals) and adds an allocated-vs-spent chart.
- **Sankey**: a "From goals" source node feeding the hub and a "Goal spending" node on
  the outflow side, so a month where goal spending exceeds income still conserves flow
  and net profit stays the operating figure.
- **Cash flow**: goal spending is money out — its own series; "Net" after it.
- **Spending Trends**: operating only by default, with an **"Include goal spending"**
  toggle that adds a Goal spending series to the stacked bars (URL-driven, e.g.
  `?goals=1`, so the choice survives the period dropdown and can be linked).
- **Budget vs Actual** gains a **Goals section at the very top, above Income** — pay
  yourself first. One row per open goal:
  - **Needed this month** (the row's "budget"): the pace to hit the target date,
    `(target − allocated before this month) / months left including this one`, measured
    from the start of the month so assigning doesn't shrink the bar you're filling.
    Goals without a target date, or already funded, show no pace ("No target date" /
    "Funded").
  - **Assigned this month** (the row's "actual"): this month's net allocation; the
    meter fills toward Needed.
  - **Spent from goal this month**, as a secondary figure, so a month you bought the
    car reads as planned spending rather than a gap.
  - Section totals, and a first "Set aside" stat in the summary strip. Goal spending
    stays out of the expense section.
- **Balance sheet**: goal accounts leave the equity section — spending from a goal is
  reported on the income statement, not the balance sheet. Plain equity (opening
  balances, the system reconciliation account) stays. If money leaves a goal for an
  asset or liability (the later "own it" flow), it shows up on that account like any
  other balance.
- **Goal Progress report**: allocated line plus a spent series; table columns
  Allocated / Spent / Left.
- **Monthly review**: `spend` is already operating-only (income-statement based), so no
  change there; add a **goal spending card** ("$19,400 from Car — funded over 10
  months"), never flagged as overspending. "Saved" stays allocations. Goal accounts stop
  appearing in the net-worth-by-account list (they aren't assets).
- **Accounts board**: goal accounts show **left**, not their raw ledger balance.

### 4.6 Goals page

- Cards show **Allocated · Spent · Left** and the state pill; the bar fills by funded %,
  with the spent part hatched; a negative goal reads "−$1,500 · carried" in red with
  "Cover" and "Keep paying back" actions.
- Close button (per §4.3); "Closed" filter.
- The Summit style gets the full treatment; Koala and Arcade adapt minimally (the climb
  follows funded %). Deleting the two unused styles is a separate cleanup.

### 4.7 YNAB import

- Spending from a savings category posts to the **goal's account**, not a same-named
  expense account.
- A savings category spent out entirely (the house) is imported as a **closed goal**
  with its allocations and spending history instead of being skipped.
- Goal accounts are created in a non-system "Goals" group (§4.1).
- Verify from a real export whether goal categories also produce `Budget` rows
  (`_build_budgets` has no goal filter; unconfirmed) and remove them if so.

### 4.8 Portability and tenancy

- `Goal.closed_at` joins the portability schema (the `test_schema` field walk will
  demand it). Goal spending lines are ordinary journal lines and already travel.
- Written against today's team scoping. If the books work (`docs/books-plan.md`) has
  swept the budget app first, new code takes a `book` instead; every new query here
  goes through the same service layer, so it is a one-place change either way.

## 5. What changes for existing users at deploy

Lines already posted to goal accounts start counting as spending. For each affected
goal, **left** drops by that amount and **Unassigned rises by the same amount** —
correcting the double count described in §2. Some of those lines may be transfers to
savings that were miscategorized to a goal. A management command
`goal_activity_report` lists, per team, every line on a goal account (date, amount,
payee, counter account) so they can be reviewed before and after the release, and the
goal's spending list (§4.4) makes each one visible and re-categorizable in the app.

## 6. Milestones

1. **M1 Integrity** (§4.1) — Goals group fix + migration, system account out of
   pickers and refused server-side, every goal guaranteed an account, Goals vs Equity
   grouping in pickers and the accounts board. Small, safe, independently shippable;
   fixes real bugs on its own.
2. **M2 Maths** (§4.2, §3) — spent/left, Unassigned, assign/withdraw, dashboard, cards
   show Allocated · Spent · Left, `goal_activity_report`.
3. **M3 Reports** (§4.5) — income statement section, Sankey, cash flow, balance sheet,
   Budget vs Actual goals section, activity page, goal progress report, monthly review
   card, accounts board.
4. **M4 Lifecycle** (§4.3, §4.4, §4.6) — states, close, cover from goal, negative-goal
   display, picker balances and the overspend hint.
5. **M5 YNAB import** (§4.7).

## 7. Testing

- **Maths**: allocated/spent/left with spending, refunds, withdrawals, voided and
  archived-feed entries; spending after month end excluded from that month; a goal
  overspent goes negative and Unassigned is unchanged by the purchase.
- **Unassigned invariant**: for any categorization to a goal account, Unassigned before
  == after (property test over random amounts/months).
- **Integrity**: goals always land in a non-system group; the system account is refused
  as a category by every endpoint (parameterized); every `Goal` has an account after
  goal creation, YNAB import and portability import; a plain equity account is never
  treated as a goal (not under Goals, not goal spending, still on the balance sheet).
- **States**: close releases a positive balance, refuses a negative one unless covered;
  `is_complete` goals keep their claim.
- **Cover from goal**: goal −X, budget +X, Unassigned unchanged, audited, atomic.
- **Reports**: the Spending Trends toggle adds and removes the goal spending series;
  income statement totals tie out (operating net − goal spending = net
  after); Sankey conserves flow; balance sheet no longer lists goal accounts but keeps
  opening-balance equity; Budget vs Actual renders Goals first, with needed measured from
  the start of the month; CSV export.
- **YNAB**: spent-out savings category arrives closed with its history; savings spending
  lands on the goal account; reconciliation gate still passes.
- **E2E**: categorize a purchase to a goal in categorize mode → the card shows it spent,
  the pill doesn't move, the income statement shows it under Goal spending.

## 8. Resolved questions

- Plain equity accounts (opening balances, etc.) stay plain; every goal has an equity
  account (§1, §3).
- Budget vs Actual gets a Goals section first, above income (§4.5).
- No "move negative balance to a new goal" action for now (§1).
- Goal spending stays off the balance sheet; opening-balance equity stays on (§4.5).
- Spending Trends gets an "Include goal spending" toggle, off by default (§4.5).

## 9. As built

What the implementation decided where the plan was silent, and where it differs.

- **Where the maths lives.** `GoalQuerySet.with_progress(month)` annotates `allocated`,
  `spent`, `left`, `spent_this_month` (all scalar subqueries, so no GROUP BY fan-out) plus
  the old `saved_previous`/`saved_this_month`/`total_saved`/`remaining`. `Goal` gains
  `allocated_amount`/`spent_amount`/`left_amount`/`to_fund`/`is_funded`/`state` properties
  that read the annotations (or query when absent). `compute_unassigned` gets
  `goals_spent` from one aggregate over goal-account lines through month end.
- **Archived goals** stay out of Unassigned, as before (both allocations and spending).
  Archiving an open goal now closes it first, so nothing is hidden while still claimed; a
  negative goal can't be archived until covered.
- **`is_complete`** is labelled "Funded" everywhere. A funded goal refuses *quick*-assign
  only; an explicit amount still goes in, because that is how a negative funded goal is
  covered or paid back from its card.
- **System accounts** are refused as a category by `apps/accounts/guards.py::
  assert_category_allowed`, called from every category-accepting path. An account the
  transaction *already* uses is allowed (`keep_ids`), so re-saving an existing adjustment
  row works. The edit modal keeps a transaction's current category in its options for the
  same reason.
- **Pickers** read one helper, `apps.budget.services.picker_accounts_data(team)`
  (`PickerAccountSerializer`: `is_goal`, `goal_left`). `SimpleAccountSerializer` exposes
  `is_system` (and `api-client/models/SimpleAccount.ts` carries `isSystem`). The client-side
  kind (`goal` vs `equity`) is `assets/javascript/common/accountKind.js::accountKind`.
- **Accounts board**: equity-type groups holding a goal (or the non-system "Goals" group)
  render under **Goals**, the rest under **Equity**. The Goals section offers "New goal"
  (the Goals page makes the account) instead of an inline "Add account", which would have
  created plain equity.
- **Spending list / link**: a goal's card and detail page link to Transactions with
  `?f_debit_account=a:<id>`; the Transactions page now honours account filters passed in
  the URL (`journal.views._initial_account_filters`).
- **Cover from goal** is `POST budget/cover-from-goal/`, returning the same `cells` payload
  as `save-amount`, driven by a dialog in `budget_table.html` + `budget-autosave.js`.
  Expense rows only.
- **Cash flow** draws goal spending as its own bar beside Money Out (not stacked on it).
- **Portability** format is version 3 (`goal_closed_at` on `accounts.csv`;
  `upgrade.upgrade_2_to_3`).
- **YNAB §4.7 verification**: the sample export's two goal categories that were also spent
  from produced **56** `Budget` rows (of 1,872) under the old import. Goal categories now
  get the goal's equity account (in a non-system "Goals" group) instead of an expense
  account, and `_build_budgets` skips them: 1,816 rows. `House` arrives closed with its
  allocations; the reconciliation gate still passes.
- **Not built**: the overspend hint appears in the edit modal only (categorize mode
  categorizes on click, so it shows the goal's balance in the picker instead); the user
  data export (`apps/users/services.py`) does not carry `closed_at` -- that file is being
  reworked by `docs/books-plan.md`.
- **Books plan**: new code is team-scoped and every new query sits in a service function
  (`GoalService`, `goal_left_by_account`, `picker_accounts_data`,
  `ReportService.goal_account_ids`, `compute_unassigned`). New migrations are
  `budget/0004_goal_closed_at_goals_group` and `audit/0010`; the books work adds
  migrations to the same apps, so whichever lands second needs a merge migration.

