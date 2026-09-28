# Every dollar a job: the Unassigned metric

Status: design agreed; Phase 1 (make it visible) built. The concept sketch that preceded this
document lives at <https://claude.ai/artifact/Co2cRn5w8K8y4wXxmvwZ1g>.

## 1. The metric

One number for the money that has no job yet: what is left of net worth once every
goal, every budget envelope and (optionally) budgeted income still to come has been
accounted for.

```
  Net worth                                   $20,000
+ Budgeted income not yet received             +5,000   (only with future-income budgeting on)
− Budget envelopes, unspent                     −7,500   (3,500 rolled over + 4,000 this month)
− Left in goals                                −16,000
= Unassigned                                    $1,500
```

In code, as of the end of the month being viewed (T):

```
unassigned = net_worth(T)
           + Σ max(0, −available_T) over income categories     # budgeted, not yet received
           − Σ max(0,  available_T) over expense categories    # unspent budget: the envelopes
           − Σ max(0,  left_T)      over goals                 # allocated − spent
```

`available_T` is the budget page's own running balance per category
(`BudgetService.get_available_with_previous`): expense `budget − actual + rollover`,
income `actual − budget + rollover`. A goal's `left_T` counts allocations dated in or
before T and spending through the end of T. Nothing dated after T counts.

**The rule behind every term: a claim is the larger of what was planned and what
actually happened.** The effect of each action on Unassigned:

| Flow | Action | Previous month | Current month | Future month |
|---|---|---|---|---|
| Income | Increase budget | Up | Up | – |
| Income | Increase actual, still ≤ budget | – | – | – |
| Income | Actual > budget | Up | Up | – |
| Expense | Increase budget | Down | Down | – |
| Expense | Increase actual, still ≤ available | – | – | – |
| Expense | Actual > available | Down | Down | – |
| Goal | Increase allocation | Down | Down | – |
| Goal | Increase spending, still ≤ left | – | – | – |
| Goal | Spending > left | Down | Down | – |

Anything else that moves net worth moves Unassigned: opening balances, reconciliation
adjustments, any other equity entry.

- **Income rolls.** A shortfall stays "still due" into the next month; a surplus
  offsets income still expected. A September paycheque that lands in October fills
  September's gap rather than arriving twice. If budgeted income isn't coming, lower
  the current month's budget; there is no need to edit history. ("Up" for last month's
  surplus is net of what it fills: it offsets this month's income still due first.)
- **Overspending comes out of Unassigned.** An overspent envelope or goal claims
  nothing, so the money spent past it leaves net worth with nothing offsetting it.
  The negative balance is **carried**, never reset, so budgeting into the hole does not
  move Unassigned a second time: the first dollars of a budget fill the hole, and only
  what goes past it is a new claim. A consequence: last month's overspending that this
  month's budget already absorbs shows up as a smaller envelope, not a lower
  Unassigned — the money is gone either way, and the invariant
  `envelopes + goals + unassigned = net worth + income due` always holds.
- **Covering overspending is free.** Raising the budget of an overspent row (the Cover
  dialog's "from Unassigned") only clears the red; covering from a goal releases the
  goal's money back into Unassigned; closing a negative goal tops it back to zero at
  no cost.
- **Future months don't count.** Budgets, income and goal allocations dated after T
  claim nothing yet; they start counting on the 1st of their month.

**History of the figure.** v1 summed income through per-category income available
without a floor and carried overspending in the envelope sum, so overspending never
moved Unassigned and income over budget was held back. v2 counted only the current
month's unreceived income (while the month ran) and still carried overspending. v3
(this) floors every claim at zero and lets income roll, per the table above.

**Single source of truth:** `apps/budget/unassigned.py::compute_unassigned()`. The
sidebar pill, the dashboard, the budget/goals card, the goal quick-assign clamp and
the Dollar Map report all read it, so they cannot disagree.

**Name.** "Unassigned" (verb: *Assign*), with the negative state labelled
"Over-assigned". The name is still open; both strings are defined once
(`UNASSIGNED_LABEL` / `OVER_ASSIGNED_LABEL` in `apps/budget/unassigned.py`) and every
template and script reads them from there. Alternatives considered: Free funds, Ready
to assign (YNAB's term), Jobless dollars, Unclaimed.

## 2. Decisions

| Question | Decision |
|---|---|
| Do illiquid assets (house, RRSP, car) count? | **Yes, for now.** Unassigned is based on full net worth. A "Holdings" bucket that absorbs illiquid accounts is parked; revisit if it bites (see §4.4). |
| Budget with income that hasn't arrived? | **A setting: "Let me budget with future income".** On: income is budgeted and counted before it lands (current behaviour). Off: income budgeting disappears entirely (income rows hidden from the budget page, grid and Budget vs Actual; income categories excluded from the envelope sum) and money becomes unassigned only once it lands. **Decided: a setting on each set of books** — see `docs/books-plan.md`. |
| Negative Unassigned | **An alarm on every screen.** The label changes to "Over-assigned", it renders in the error colour, and it stays that way until resolved. |
| Overspent envelopes | **Out of Unassigned at once, negative carried** (revised; was "carry the negative, Unassigned unchanged"). Money spent without a budget isn't free, so overspending lowers Unassigned as soon as it is categorized. The envelope (or goal) keeps its red negative balance into the next month — never reset — and budgeting into that hole doesn't move Unassigned again. Covering is an offered action, not a requirement. See §1. |
| Goals: equity accounts or something else? | **Stay equity accounts. No migration.** Almost every equity account is a goal; the one exception is the system reconciliation/opening-balance account (`is_system=True`), which is excluded wherever goals are enumerated. |

## 3. The number everywhere (Phase 1)

- **Sidebar pill** on every app page (and the mobile top bar), in three states:
  - positive — "waiting for a job" (the figure links to the Dollar Map, with a Budget link beside the hint);
  - zero — "Every dollar has a job";
  - negative — red, "Over-assigned", "promised more than you have".
- **Every action shows its ripple.** After any successful write the pill refreshes
  itself and shows a delta chip (`+$300`, `−$150`) with a polite live-region
  announcement. This is done once, in `assets/javascript/unassigned/unassigned-pill.js`,
  by observing same-origin non-GET `fetch` responses — so the Inbox, categorize mode,
  budget autosave, goals quick-assign and anything added later all ripple without each
  having to remember to.
- **Dashboard headline.** The lead metric card is Unassigned (with the allocation bar),
  replacing "Total budget available" — which showed the sum of category balances, not
  this metric.
- **Budget and Goals pages.** The net-worth card now shows every term of the sum (net
  worth, income still due, in budget envelopes, in goals) and its bottom line carries
  the metric's name and state; the Goals page summary and its toasts use the name too.
- **Dollar Map report** (`/a/{slug}/reports/dollar-map/`, `?month=YYYY-MM-DD`, picked with the shared `BudgetMonthPicker`):
  - a stats strip (net worth, in envelopes, in goals, unassigned);
  - the *allocation bar* — every claim on your money side by side (goals, budget
    envelopes, unassigned), with a marker at net worth and, when income is budgeted
    but not yet received, a marker for "with income due"; over-assignment, the only
    way the claims can extend past what you have, is hatched and explained;
  - a per-bucket breakdown (each goal; each envelope, noting what rolled over);
  - the *waterfall* — net worth stepping down to Unassigned, one bar per term above.

### Which month?

The pill and dashboard always show the **current calendar month**. The budget and
goals pages show the month being viewed, and the Dollar Map report takes `?month=`.
Budgets, income and goal allocations entered for a *future* month do not affect this
month's Unassigned (they count from that month on). Worth revisiting if users expect
YNAB-style "assign ahead".

## 4. Goal lifecycle (Phase 2)

### 4.1 A goal is an envelope that doesn't reset

```
Budget category:  available = Σ budgeted − Σ spent     (rolls over month to month)
Goal:             saved     = Σ allocated − Σ spent    (same maths, plus a target)
```

Saving is an allocation of unassigned net worth. Moving $1,000 into a savings account
is a transfer between two asset accounts and is categorized as a transfer — never to
the goal. Spending is a real transaction categorized to the goal's (equity) account.

Today goal progress is `Σ GoalAllocation` only; journal lines on the goal's account
never touch it. So categorizing the car purchase to "Goal: Car" lowers net worth by
$20,000 while the goal still claims $20,000, and Unassigned falls by $20,000 — the
money is counted as both spent and still saved. Phase 2 fixes that by making goal
progress `Σ allocated − Σ (dr − cr) on the goal account`. Buying the car then moves
net worth and the goal by the same amount, and Unassigned doesn't flinch.

### 4.2 States

Saving → Funded → Spending → Closed.

- **Funded**: target reached; stops asking for money but still holds its claim.
- **Spending**: transactions categorized to the goal draw it down (may start before
  it is fully funded).
- **Closed**: leftover released to Unassigned (the existing withdraw endpoint), or an
  overspend covered or carried; archived with its history.

`is_complete` today means "done" and drops the goal out of `active()`; it must split
into Funded (still holding money, still counted) and Closed.

### 4.3 Three kinds of goal (behaviour, not a model field)

- **Purchase** (car, trip, wedding): ends in one or a few transactions categorized to
  the goal.
- **Buffer** (emergency fund): never spent directly — "Cover from goal" moves money
  from the goal into an overspent category for that month, and the expense shows in
  its normal category.
- **Horizon** (retirement): never spent within the app. Contributions to the RRSP are
  transfers. Optional "Held in" link to the account the money lives in, warning when
  goals claim more than it holds.

### 4.4 Spend it vs own it

- **Spend it (v1):** the purchase is categorized to the goal. Net worth −$19,400,
  goal −$19,400, Unassigned unchanged. Matches YNAB, so imported savings categories map
  onto it with no special case.
- **Own it (later):** the purchase goes to an asset account (Vehicle, Home). Net worth
  is unchanged — but because illiquid assets count (§2), closing the goal would make
  Unassigned jump by $19,400. An owned goal would have to keep a claim equal to the
  asset's balance. That is Holdings in all but name, so it waits.

### 4.5 Reports

The income statement gets a **Goal spending** section below the operating net:

```
Income                                    6,000
Expenses                                  4,200
Net before goal spending                  1,800   (savings rate uses this)
Goal spending — planned, paid from goals 19,400
  Car                                    19,400
Net after goal spending                 −17,600
```

Operating expenses and goal (capex-like) spending are treated separately throughout:
Spending Trends and Budget vs Actual exclude goal spending by default, the Sankey draws
it as its own flow from savings, and the monthly review gives it its own card instead
of flagging it as overspending.

### 4.6 Other cases

- Car costs $21,500, goal holds $20,000 → goal carries −$1,500 (red); covering is the
  user's choice.
- Refund on a goal purchase → credit to the goal account; the goal goes back up.
- **Financed purchase** ($15k loan + $5k from the goal): the whole $20,000 is spent from
  the goal, and the user sets up a new $15,000 goal to pay the loan down. Splitting
  payments into interest and principal is the user's to do; no special machinery.
- Goal abandoned → release the balance (withdraw), history intact.
- Longer term: `GoalAllocation` and `Budget` have the same shape and formula and could
  merge; the portability format already distinguishes them by a `kind` column.
- YNAB import: spent savings categories (the house) could come in as closed goals with
  their spending history rather than being skipped.

## 5. Roadmap

1. **Make it visible** — metric service, sidebar pill with ripple chips, dashboard
   headline, relabelled budget/goals card, Dollar Map report. *(done)* Deferred to
   Phase 2 pending the open question in §6: the future-income setting.
2. **Make it actionable** — future-income setting; goals as envelopes (spending on the
   goal account draws it down) with the Funded/Closed split; Goal spending section on
   the income statement; "Cover from goal"; income-landed "give it a job" toast in the
   Inbox; budget-page warning before an edit pushes Unassigned below zero.
3. **Make it a habit** — month-end sweep step in the monthly review with suggested
   splits; auto-assign strategies; Unassigned-at-month-end trend; zero-month streak;
   Ask Koala answers "can I afford it?" against Unassigned; "Own it" goals.

## 6. Open questions

- ~~Future-income setting: team or profile?~~ Decided: per set of books, which
  introduces multiple books per team (`docs/books-plan.md`).
- **Default for new teams** — probably off (only budget money you have), possibly asked
  during onboarding.
- **Final name.**
