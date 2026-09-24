# Every dollar a job: the Unassigned metric

Status: design agreed; Phase 1 (make it visible) built. The concept sketch that preceded this
document lives at <https://claude.ai/artifact/Co2cRn5w8K8y4wXxmvwZ1g>.

## 1. The metric

One number for the money that has no job yet: what is left of net worth once every
goal, every budget envelope and (optionally) this month's expected income has been
accounted for.

```
  Net worth                                   $20,000
+ Budgeted income not yet received             +5,000   (only with future-income budgeting on)
− Expense envelopes rolled over from last month −3,500
− This month's expense budget, unspent          −4,000
− Goals, allocated before this month           −15,000
− Goals, allocated this month                   −1,000
= Unassigned                                    $1,500
```

In code:

```
unassigned = net_worth
           + Σ max(0, budget − actual) over income categories, this month only, while the month is running
           − Σ available(expense categories)          # budget − actual + rollover: the envelopes
           − Σ goal allocations (non-archived goals)
```

**Change from the previous figure.** The budget/goals card used to compute this as
`net_worth − goals − Σ available(income + expense categories)`, i.e. it summed income
through the per-category income "available" (`actual − budget + rollover`). Carried
forward, that turned every past month's income shortfall into money still "due"
forever (budget $5,000, earn $4,800, and $200 of phantom money joined the figure every
month), and it held back income earned over budget instead of letting it arrive
unassigned. Only this month's not-yet-received income counts now, and only while the
month is running. The per-category "Available" column on the budget page is
unchanged — that is the category's own view; this is the whole-budget figure.

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
| Budget with income that hasn't arrived? | **A setting: "Let me budget with future income".** On: income is budgeted and counted before it lands (current behaviour). Off: income budgeting disappears entirely (income rows hidden from the budget page, grid and Budget vs Actual; income categories excluded from the envelope sum) and money becomes unassigned only once it lands. Open: team-level or profile-level (see §6). |
| Negative Unassigned | **An alarm on every screen.** The label changes to "Over-assigned", it renders in the error colour, and it stays that way until resolved. |
| Overspent envelopes | **Carry the negative.** An overspent category (or goal) keeps its red negative balance into the next month. The user is never forced to cover it; covering is an offered action, not a requirement. (Deliberately unlike YNAB, which pulls overspending out of Ready to Assign.) Mathematically this means overspending does not move Unassigned — the shortfall stays visible on the envelope that caused it. |
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
- **Dollar Map report** (`/a/{slug}/reports/dollar-map/`, `?month=YYYY-MM`):
  - a stats strip (net worth, in envelopes, in goals, unassigned);
  - the *allocation bar* — every claim on your money side by side (goals, budget
    envelopes, unassigned), with a marker at net worth and, when income is budgeted
    but not yet received, a marker for "with income due"; anything that extends past
    what you have (over-assignment, or overspending carried as negative envelopes) is
    hatched and explained;
  - a per-bucket breakdown (each goal; each envelope, noting what rolled over);
  - the *waterfall* — net worth stepping down to Unassigned, one bar per term above.

### Which month?

The pill and dashboard always show the **current calendar month**. The budget and
goals pages show the month being viewed, and the Dollar Map report takes `?month=`.
Known limitation: a budget amount entered for a *future* month does not reduce this
month's Unassigned (it counts from that month on). Worth revisiting if users expect
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

- **Future-income setting: team or profile?** Budgets are team-scoped. A per-profile
  setting would show two partners different numbers for the same budget, and hiding
  income rows for one would hide shared data. Recommendation: a workspace setting in
  the Settings hub; if it must be per-profile, it should only change which figure that
  person sees.
- **Default for new teams** — probably off (only budget money you have), possibly asked
  during onboarding.
- **Final name.**
