# Goal plans: budgeting a goal's monthly contribution

Plan for a **Goals section on the budget page**. Each open goal gets a row whose
*Planned* amount comes from `Goal.monthly_contribution` and can be changed for any
single month. A goal with linked accounts gets money when the money **arrives** in a
linked account. Until then, its plan holds that money back from Unassigned. A goal
without linked accounts gets money as soon as it is **planned**.

Builds on `docs/unassigned-plan.md` (v3 rule: *a claim is the larger of what was
planned and what actually happened*), `docs/goals-envelopes-plan.md` and
`docs/goal-linked-accounts-plan.md`.

---

## 0. Decisions already taken

| # | Question | Decision |
|---|---|---|
| D1 | What happens to an unmet plan at month end | **A per-goal setting**, `Goal.unmet_plan`: `release` (default) or `carry`. Only linked goals use it (§2.3). |
| D2 | Where per-month plans are stored | **A new model, `GoalPlan(goal, month, amount, source)`** (§3). |
| D3 | Which month a transfer counts in | **The month of its `entry_date`.** No reassigning a transfer to another month (§9.1). |
| D4 | Where the default comes from | **`Goal.monthly_contribution` only.** The target-date pace from `goal_plan()` is shown as a hint, never used as the default (§6.3). |
| D5 | Where the section sits | **Between Income and Expenses**, so goals are paid first, matching the Goals-first order of the Budget vs Actual report. |

---

## 1. Problem

Goal money currently comes from two places (`goal_allocated_subquery`):

- `GoalAllocation`: manual assigns and withdrawals.
- Linked flows: money arriving in a linked account (`apps/budget/linked.py`).

With a linked goal (a pension fed from checking):

- **Before the transfer**, the $1,000 is still in checking. Unassigned still counts
  it, so it can be budgeted to something else.
- **Assigning it manually** doesn't fix that: the transfer adds another $1,000, so
  the goal ends up with $2,000.

There is no place to say "this money is spoken for, and the transfer will deliver it."

---

## 2. Rules

### 2.1 Terms per goal and month

`m` is a first-of-month date.

| Term | Definition |
|---|---|
| `planned(m)` | The goal's `GoalPlan` row for `m` if there is one. Otherwise the **default**: `monthly_contribution` when the default is active and `m ≥ plan_from` (§4), else 0. Never negative. |
| `mode(m)` | **linked** if one of the goal's `GoalAccountLink`s covers any day of `m`; otherwise **direct**. Always derived from link history, never stored. |
| `assigned(m)` | Σ `GoalAllocation.amount` in `m`. Unchanged: manual assigns, withdrawals, close/cover releases. |
| `flows(m)` | Σ `alloc_delta` of linked lines dated in `m` (`linked_lines`). **Starting balances are not flows**: they are a one-off in the link's first month and never count toward a plan. |
| `put_in(m)` | `assigned(m) + flows(m)` |

### 2.2 Direct months: the plan is the allocation

A direct goal has nothing to wait for, so `planned(m)` is added to `allocated` in `m`,
alongside `assigned(m)`. Assign and withdraw on the goals page still work and add to
or take from it.

**Target cap.** A plan never takes a goal past its target. For goals with
`target_amount > 0`, the plans counted through any date `x` are:

    plans_through(x) = min( Σ direct planned(m) for m < x,
                            max(0, target − other_allocated(x)) )

`other_allocated(x)` is everything else dated before `x`: assigns, flows and
starting balances. A window `[a, b)` counts `plans_through(b) − plans_through(a)`.
The cap applies to typed plans as well as the default. Open-ended goals (no
target) are not capped.

### 2.3 Linked months: the plan holds money until it arrives

`held(M)` is the amount held back from Unassigned for goal G as of month `M`.

`held(M) = 0` in any of these cases:

- `mode(M)` is direct;
- the goal is archived;
- the goal is closed and `M` is on or after the month it closed.

Otherwise:

- **`unmet_plan = release`**:
  `held(M) = max(0, planned(M) − put_in(M))`.
  The shortfall goes back to Unassigned on the 1st of the next month.
- **`unmet_plan = carry`**:
  `held(M) = max(0, Σ (planned(m) − put_in(m)))` over linked months `m` from `s` to `M`,
  where `s` is the first linked month with `planned > 0`.
  Like income, the difference rolls in both directions: an over-transfer reduces
  what later months hold.

Then, for target goals:
`held(M) = min(held(M), max(0, target − allocated(M)))`.

A plan in a linked month **never changes `allocated`**. Only arrivals (and manual
assigns) do, so the progress bar moves when the money lands.

Changing `unmet_plan` recomputes every month, the same way the book's
future-income setting does. No stored figure is rewritten.

### 2.4 Unassigned

```
unassigned = net worth
           + Σ max(0, −available) over income categories
           − Σ max(0,  available) over expense categories
           − Σ max(0,  left)      over goals
           − Σ held               over goals        ← new
```

`left = allocated − spent` is unchanged, except that `allocated` now includes direct
plans (§2.2). Plans dated after the viewed month count for nothing, the same rule as
every other term.

### 2.5 Worked examples

The examples start with checking at $5,000 and the pension at $20,000. The pension
goal plans $1,000/month. "Unassigned Δ" is the change from before the plan.

**Linked goal, `release`:**

| Event | allocated | held | Unassigned Δ |
|---|---|---|---|
| Oct 1: default plan of $1,000 applies | 0 | 1,000 | −1,000 |
| Oct 15: transfer $1,000 | +1,000 | 0 | −1,000 (no change from the transfer) |
| Alternative: transfer only $600 | +600 | 400 | −1,000 |
| → Nov 1, nothing more arrived | +600 | 0 (Oct lapsed) + Nov's 1,000 | −600 − 1,000 |
| Alternative: transfer $1,200 | +1,200 | 0 | −1,200 (the extra $200 really moved) |

**Linked goal, `carry`:** the same as `release` through October. On Nov 1 after the
$600 transfer, held = 400 + 1,000 = 1,400, and the next $1,400 that arrives clears it.

**Direct goal ($500/month, target $1,200):**

| Month | planned | counted | allocated | Unassigned Δ that month |
|---|---|---|---|---|
| Oct | 500 | 500 | 500 | −500 |
| Nov | 500 | 500 | 1,000 | −500 |
| Dec | 500 | 200 (cap) | 1,200 | −200 |
| Jan | 500 | 0 | 1,200 | 0 |

---

## 3. Data model

### 3.1 `GoalPlan` (new, `apps/budget/models.py`)

```python
class GoalPlan(BaseBookModel):
    SOURCE_DEFAULT = "default"   # written by plans.freeze(): what the default was that month
    SOURCE_TYPED = "typed"       # the user changed this month on the budget page
    goal = models.ForeignKey(Goal, on_delete=models.CASCADE, related_name="plans")
    month = models.DateField()                      # first of month (save() normalizes)
    amount = models.DecimalField(max_digits=15, decimal_places=2)   # ≥ 0
    source = models.CharField(max_length=10, choices=..., default=SOURCE_TYPED)

    class Meta:
        unique_together = ["book", "goal", "month"]
        default_related_name = "budget_goal_plans"
        constraints = [CheckConstraint(amount__gte=0)]
```

- Add it to `BOOK_MODELS` in `apps/books/migration_utils.py`. It is not added to
  `BACKFILLED_BOOK_MODELS`, because it did not exist at `books.0003`.
- `wipe_book`: removed by the CASCADE from `Goal`. Check that the order in
  `wipe.py` still deletes it before accounts.

### 3.2 New fields on `Goal`

| Field | Type | Meaning |
|---|---|---|
| `plan_from` | `DateField(null=True)` | First month the **current** default settings apply to. Months before it have `GoalPlan` rows wherever a plan applied (§4). Null means the default has never applied. |
| `unmet_plan` | `CharField` with choices `release` and `carry`, default `release` | D1. |

`monthly_contribution` stays the source of the default and keeps its current role
in `goal_plan()`.

### 3.3 Migration `budget.0009_goal_plans`

1. Create `GoalPlan` and add the two `Goal` fields.
2. Data step `adopt_existing_goals`. For every open goal with
   `monthly_contribution > 0`, call `plans.adopt(goal, deploy_month)`:
   - set `plan_from = deploy_month`, so **no earlier month changes**;
   - for a goal that is direct in `deploy_month` and already has a positive
     `GoalAllocation` that month, write
     `GoalPlan(month=deploy_month, amount=0, source=typed)`, so a contribution the
     user already assigned by hand isn't added again by the new default.
   Goals without a contribution keep `plan_from = None`.
3. Reversible: the reverse step deletes all `GoalPlan` rows. The fields are dropped
   by the schema reverse.

`plans.adopt()` is also used by the portability upgrade (§8), so the migration and
an imported archive behave the same way.

---

## 4. The default and history

Months without a row use the **current** settings, so a settings change would
silently rewrite every such month. Plans therefore follow one invariant:

> A month without a `GoalPlan` row plans the goal's current default. Every write
> that changes the default first records what the affected months planned.

**What the default depends on:**

- `monthly_contribution`
- whether the default is active (open, not archived, not `is_complete`)
- `plan_from`
- the goal's links, which decide `mode`

**`plans.freeze(goal, today)`**, called inside the writer's transaction with the
goal row locked (`select_for_update`):

1. For each month from `plan_from` through the current month that has no row, write
   `GoalPlan(amount=default, source=default)` (skipped while the default is
   inactive).
2. Set `plan_from` to the first of next month.

After a freeze, months without a row are all in the future, and they keep that
status while nothing changes. Dynamic months (≥ `plan_from`) therefore all share
the goal's current link state, which is why their `mode` can be read as "has an open
link" (§5.1). Rows read their mode from link history.

**Writers that must freeze**, each through one function in `apps/budget/plans.py`:

| Writer | Call |
|---|---|
| Goal form save, contribution changed (`_goal_form_view`) | `plans.set_contribution(goal, amount, today)` |
| `goal_links.set_links`, `unlink`, `end_all` | `plans.freeze(goal, today)` before changing links |
| `GoalService.close`, the archive path (`goal_delete_view`) | `plans.freeze`, then the change |
| `goal_complete_view` (Funded), and any un-fund or reopen | `plans.freeze`, then the change |
| Goal creation (form, onboarding `api/complete/`, YNAB import, portability apply) | `plans.start(goal, created_month)`, which sets `plan_from` |

**`set_contribution(goal, amount, today)`** applies a contribution change **from the
current month**:

1. freeze;
2. set `monthly_contribution`;
3. if the current month's row is `source=default`, set it to the new amount
   (delete it when the new amount is 0 or empty);
4. a `typed` row keeps what the user typed.

A new contribution applies to the current month at once, and past months keep the
old amount.

**Enforcement:** add `PlanInputsWriteTest` (AST scan, modelled on
`NoBypassingWritesTest` in `apps/journal/test_voiding.py`). It fails on assignments
to `monthly_contribution`, `is_complete`, `closed_at` or `is_archived` on a `Goal`,
and on `GoalAccountLink` create/save/delete, outside the listed writers, migrations
and tests.

---

## 5. Calculations: `apps/budget/plans.py`

### 5.1 SQL: direct plans go into `allocated`

`direct_planned_subquery(end)` is a scalar subquery on `Goal`, Σ direct `planned(m)`
for `m < end`:

- **Rows:** Σ `GoalPlan.amount` with `month < end`, where no `GoalAccountLink`
  covers the row's month (an `Exists` per row).
- **Dynamic months:** applies only when the goal has no open link and its default is
  active.
  `monthly_contribution × (months in [plan_from, end) − count of rows in [plan_from, end))`.
  The month count is `(year(end) − year(plan_from)) × 12 + month(end) − month(plan_from)`
  (`ExtractYear`/`ExtractMonth`), floored at 0 with `Greatest`.

`goal_allocated_subquery(start, end)` becomes `cumulative(end) − cumulative(start)`,
where:

    cumulative(x) = other(x) + Case(target > 0 → Least(P(x), Greatest(0, target − other(x))), else P(x))
    other(x)      = goal_assigned_subquery(end=x) + linked_allocated_subquery(end=x)
    P(x)          = direct_planned_subquery(x)

`with_progress(month)` currently uses an unbounded `allocated`. It passes
`plans_end = month_after(month)`, so plans after the viewed month never count. Every
existing caller (`with_progress`, `compute_unassigned`, `goal_left_by_account`,
`goal_links.preview`) is otherwise unchanged.

### 5.2 Python: per-month figures and `held`

`plan_months(book, goals, start, end)` returns
`{goal_id: {month: {"planned", "mode", "source"}}}`, built from rows, the dynamic
default and link history. It is the Python twin of §5.1. `PlanTwinTest` checks that
the two agree on a randomized history.

`goal_monthly()` gains three keys per month:

- `planned`
- `plan_in`: what direct plans counted that month, after the cap
- `mode`

`saved` becomes `assigned + linked + plan_in`. Every per-month reader (streaks,
monthly review, Goal Progress, the goal-account chart) follows without further
changes. `AllocationReadsTest` gets `GoalPlan` added.

`held_by_goal(book, goals, month)` returns `{goal_id: held}` per §2.3, computed from
`goal_monthly()` data. `held` is only needed in Python: Unassigned, the budget page,
goal cards and the Dollar Map. It never goes into `with_progress`.

### 5.3 `compute_unassigned`

- `Unassigned` gains a `goals_held: Decimal` field.
- `amount` becomes `net_worth + income_due − envelopes − goals − goals_held`.
- `detail["goals"]` rows gain `held` and `planned`.
- `NetWorthService.card_data` gains a `held` key.

Every screen that reads `compute_unassigned` (pill, dashboard, net-worth card,
quick-assign clamp, Dollar Map) follows from there.

### 5.4 `goal_plan()`

`rate` and `needed` read **this month's `planned(m)`** when the goal has a plan for
`m`. Otherwise they keep today's logic (contribution, or the target-date pace). For
the status pill:

- a linked goal is *on track* once `put_in(m) ≥ planned(m)`;
- a direct goal is on track by construction (its plan is its allocation).

---

## 6. Budget page

### 6.1 The section

`_budget_figures()` adds `sections[1] = {"key": "goal", "label": _("Goals"), …}`
(D5). It has one group with a row per open goal (`GoalService.get_goals_with_progress`
order). Closed and archived goals are excluded. Funded goals (`is_complete`) are shown
with a *Funded* badge, and their default is 0.

The column mapping reuses the table's existing columns, so no new header is needed:

| Column | Goal row |
|---|---|
| Category | Goal name, linking to `goal_detail`. A muted sub-line shows `Linked · {accounts}` when linked this month. A tag reads *Monthly* when the value is the default, or *Changed* with a ↺ reset button (`goal-plan-reset`) when typed. |
| Progress | Meter of `put_in(m) / planned(m)`. Its label is `{pct}%`, or "Funded". |
| Budgeted | **Planned**, an `AmountInput`-style text field (`goal-plan-input`, `data-goal-id`, `data-month`, `data-amount-input`), value `planned(m)`. |
| Actual | What went in this month: `saved` from `goal_monthly` (direct plans + assigns + flows). |
| Available | The goal's `left`. When `held > 0`, a sub-line reads "$400 still to move to {account}" (`goal-held`). |
| Action | None. Cover and withdraw stay on the goals page. |

The section totals are Planned, Actual and Left, plus a "Still to move" total when
any row holds money. The sidebar summary gains "Planned for goals". The net-worth
card gains a line "Waiting to move to goals" (`networth:held`) under "In goals".

### 6.2 Saving

New endpoint `POST budget/save-goal-plan/` (`budget:budget_save_goal_plan`):

- **Body:** `{goal_id, month, amount}`, or `{goal_id, month, reset: true}`.
- **Lookup:** the goal comes from `Goal.objects.filter(book=request.book).active()`
  (404 otherwise).
- **Amount:** parsed by `parse_budget_amount` (formulas allowed, blank = 0).
  `0 ≤ amount ≤ GRID_MAX_AMOUNT` is required, otherwise 400 ("A plan can't be
  negative. To take money out, withdraw it on the Goals page.").
- **Write:** upserts `GoalPlan(source=typed)` under `select_for_update`. Typing the
  value the default would give still writes a typed row; it stays until reset.
- **Reset:** deletes the typed row, but only for `month ≥ plan_from`. Frozen months
  have no default to go back to, so they are not offered a reset.
- **Response:** `{saved, goal_id, amount, cells}` with the same `_budget_cells()`
  payload, extended with these keys:
  - `goal:<pk>:actual`, `goal:<pk>:available`, `goal:<pk>:held`, `goal:<pk>:meter`,
    `goal:<pk>:source`
  - `section:goal:budgeted`, `section:goal:available`, `section:goal:held`
  - `sidebar:goals_planned`, `networth:held`
- **Form posts:** a plain form post (the `<noscript>` row form) gets a redirect back
  to the month. The JSON/redirect choice keys off the `Accept` header, as other
  endpoints do.
- Register it in `apps/books/tests/test_isolation.py` beside
  `budget:budget_save_amount` (WRITES, with a payload naming the fixture's goal).

`budget-autosave.js` treats a field with `data-goal-id` as a goal row:

- it posts to `data-goal-plan-save-url` with `goal_id`;
- the reset button posts `reset: true`;
- everything else (tickets, queueing, Enter/↑/↓, flash, error toast) is shared.

Because the save is a non-GET same-origin request, the Unassigned pill re-reads
itself.

### 6.3 The target-date hint

For a goal with a target date but no contribution, the row's sub-line shows the
pace from `goal_plan()`: "$312/mo reaches the target by Jun 2027". A **Use** button
(`goal-plan-use-pace`) types that amount as this month's plan. It is never used as
the default (D4).

---

## 7. Other surfaces

- **Goal form (`templates/budget/goal_form.html`).** Add `unmet_plan` radios to the
  *Where the money lives* section, shown only while an account is ticked:
  - "Release it at the end of the month: anything not moved goes back to Unassigned"
  - "Keep holding it until the money arrives"

  Under *Monthly contribution*, add: "Planned automatically every month on the
  Budget page. A change applies from this month; months you changed there keep what
  you typed."
- **Goal cards and detail.** Show "Planned this month $1,000 · $400 still to move"
  for linked goals (`goal_card_meta.html`). The detail page's Activity table gains a
  *Planned* row per month and shows `plan_in` for direct goals ("Planned
  contribution").
- **Quick-assign on a linked goal.** This is the original double-count, so for a goal
  that is linked this month, `goal_assign_available` **adds to this month's plan**
  (a typed `GoalPlan`) instead of writing a `GoalAllocation`. The response carries
  `planned: true`, and the toast reads "Planned. Move it to {account} to complete
  it." Direct goals are unchanged. Withdraw is unchanged.
- **Dollar Map.**
  - The waterfall gains the step "Waiting to move to goals".
  - The allocation bar shows held money as a hatched segment of the goals colour.
  - The per-bucket breakdown lists held money per goal.
- **Budget vs Actual (`GoalService.month_rows`) and Budget & Goals
  (`apps/reports/consolidated.py`).** `needed` becomes `planned(m)` when a plan
  exists, and rows gain `held`.
- **Monthly review.** The goals step reads `planned`, `plan_in` and `held` from
  `goal_monthly`. Add a `goal_plan_unmet` info card for each linked goal whose month
  ended with `held > 0` under `release`: "$400 of Pension's $1,000 plan wasn't moved
  and went back to Unassigned."
- **Not changed:** Auto-Assign (`budget_autofill_view`), since goals are already
  filled in by the default. The multi-month grid is a follow-up (§11, M7).

---

## 8. Portability: format v8

- `budget.csv` gains `kind = goal_plan` rows (`GoalPlan`: goal by backing account
  id, `month`, `amount`, `source`), via a new `GOAL_PLAN` `FieldMap` in the
  `budget.csv` composition.
- `accounts.csv` gains `goal_plan_from` and `goal_unmet_plan`.
- `schema.FORMAT_VERSION = 8`; `COLUMNS_ADDED_IN` and `FILES_ADDED_IN` are updated.
- `upgrade_7_to_8`: older archives had no plans. Each goal gets
  `goal_unmet_plan = release`, and the apply step calls `plans.adopt(goal,
  import_month)` (the same rule as the migration, §3.3), so importing an old archive
  changes no past month.
- `test_schema.py` covers the new fields automatically (`FieldMap` walk). The round
  trip test gains typed and default rows and both settings.
- The user data export adds `goal_plans.csv`.

---

## 9. Edge cases

1. **A transfer in a different month from its plan (D3).** A Sep plan whose
   transfer is dated Oct 2:
   - `release`: September's shortfall lapses on Oct 1. The Oct 2 arrival is put in
     for October, which covers October's plan.
   - `carry`: the Oct 2 arrival first fills September's carried shortfall.

   The goal form's help text says which setting suits an account funded late in the
   month.
2. **Money moved out of a linked account** (`outflow = withdraw`) lowers `put_in`,
   so `held` rises again within the month. The plan stands until it is edited.
3. **Linking mid-month.** The whole month becomes linked (mode is per month). A
   direct plan already counted this month moves from `allocated` to `held`, so
   Unassigned is unchanged and the goal's allocated falls until the money arrives.
   The link's starting balance is not put in (§2.1).
4. **Unlinking mid-month.** The freeze writes this month's row while the link still
   covers it, so the month stays linked. Next month is direct: its plan is allocated
   and the old account's later arrivals don't count.
5. **Target reached.** Direct plans are capped (§2.2) and `held` is capped (§2.3).
   The planned value stays as typed, and the row explains it: "Only $200 left to
   finish this goal."
6. **Funded (`is_complete`).** The freeze keeps the current month's plan, and the
   default is off from next month. Type 0 to stop it this month.
7. **Closed.** `held = 0` from the close month. Closing a direct goal releases
   `left`, including this month's plan, as it does today.
8. **A goal created mid-month** plans its full contribution in that month
   (`plan_from` = creation month).
9. **Past months** can be changed: typed rows are allowed for any month, exactly as
   budget amounts are. Reset is only offered from `plan_from` on.
10. **Future months.** Viewing November in October shows November's default and lets
    it be typed over. It counts only when viewing November or later.
11. **Concurrent writes.** Every plan writer locks the `Goal` row first, so a freeze
    can't interleave with a typed save.

---

## 10. Tests

- **`apps/budget/test_goal_plans.py`.** One test per row of the §2.5 tables, plus:
  - direct, linked × `release`/`carry`, open-ended vs target (cap);
  - typed overrides; reset; contribution change mid-history (past months
    unchanged, current month follows, typed months kept);
  - link/unlink mid-month (§9.3–9.4); funded; closed; archived;
  - a starting balance not counted as put in;
  - an outflow raising `held`;
  - `PlanTwinTest` (SQL agrees with Python);
  - `PlanInputsWriteTest` (AST).
- **`apps/budget/test_unassigned.py`.** A `GoalPlanTest` class with the Unassigned
  delta of each event above.
- **Views.** For `budget_save_goal_plan`:
  - happy path, with the cells payload;
  - negative/too-large/invalid amount → 400;
  - reset before `plan_from` → 400;
  - another book's goal → 404 (isolation table);
  - no-JS redirect.

  For quick-assign on a linked goal: writes a `GoalPlan`, not a `GoalAllocation`.
- **Migration.** Existing goals change no past month; a direct goal with an
  allocation this month gets the typed-0 row.
- **Portability.** v7 → v8 upgrade, round trip.
- **E2E (`e2e/tests/test_budget.py`, `test_goals.py`).**
  - The Goals section renders the default.
  - Typing a plan updates Unassigned in place.
  - Reset restores the default.
  - A linked goal shows "still to move" until a categorized transfer arrives, after
    which Unassigned is unchanged.
  - The `unmet_plan` radio appears only with an account ticked.

---

## 11. Build order

| M | Scope | Done when |
|---|---|---|
| M1 | Model, fields, migration `0009`, `plans.adopt/start/freeze/set_contribution`, writers wired, `PlanInputsWriteTest` | Writers freeze; no figure changes yet |
| M2 | §5: SQL subquery, `goal_monthly` keys, `held_by_goal`, `compute_unassigned`, `goal_plan()` | `test_goal_plans.py` and `GoalPlanTest` green |
| M3 | §6: budget section, endpoint, cells, autosave, noscript, isolation entry | Budget page E2E green |
| M4 | Goal form setting, goal cards/detail, linked quick-assign → plan | Goals E2E green |
| M5 | Dollar Map, Budget vs Actual / Budget & Goals, monthly review card | Report tests green |
| M6 | Portability v8, user data export, `CLAUDE.md` "Recent Changes" entry | Round trip and upgrade green |
| M7 (follow-up) | Goal rows in the multi-month grid (same endpoint per cell; "Apply to entire year" writes typed rows) | n/a |

---

## 12. What the build decided

Where the build differs from, or settles something left open in, the sections above.

- **How far `freeze` goes depends on the change.** A change to the contribution,
  the target or the links freezes the months *before* the current one and sets
  `plan_from` to the current month, so the current month follows the new settings
  at once (no row has to be rewritten). Funded, closing and archiving freeze
  *through* the current month (`through_current=True`) and set `plan_from` to next
  month, so what this month's plan already gave stays. `set_contribution` (§4) is
  therefore not needed as a separate writer: the goal form calls `plans.freeze`
  before saving whatever changed, and `goal_links.set_links`/`unlink`/`end_all`,
  `GoalService.close`, `GoalService.mark_funded` and `GoalService.archive` call it
  themselves. `PlanInputsWriteTest` fails on any attribute assignment or
  `.update()` of `monthly_contribution`, `target_amount`, `is_complete`,
  `closed_at` or `plan_from` outside `models.py`, `plans.py` and `services.py`.
- **A new goal's `plan_from` is set by `Goal.save()`** (the month it is created), so
  the form, onboarding, the YNAB import and the link preview need no extra call.
  `plans.start` from §4 doesn't exist. Portability's bulk insert carries
  `plan_from` from the file, or runs `plans.adopt_goals` for an older export.
- **The target cap is cumulative and applies to every direct plan**, typed or
  default: through any date, direct plans count at most
  `max(0, target − everything else given before that date)`
  (`plans.direct_planned_subquery`, `plans.apply_plans`). To keep a later target
  change from releasing months the cap had stopped, `freeze` writes the frozen
  default rows and then **trims the latest direct default rows** until they sum to
  what the plans actually counted (`_trim_to_counted`). Typed rows are never
  trimmed.
- **The SQL relies on one invariant about links.** The default's months
  (`plan_from` onwards) are classified as direct or linked without walking every
  month: the first one is linked if a link covers it, the rest if the goal has an
  open link. This holds because every link change freezes first. `PlanTwinTest`
  checks the SQL against the per-month Python (`plan_months`), which classifies
  each month exactly.
- **`goal_monthly` reads from the start of history** (and trims to `start` at the
  end), since the cap needs everything given before a month. It gains `flows`,
  `planned`, `plan_linked`, `plan_source` and `plan_in`. `monthly_linked` gains
  `starting`, so starting balances stay out of `put_in`.
- **`with_progress(month)`'s `allocated`** still counts manual allocations dated in
  any month (as before), but plans only through the viewed month
  (`goal_allocated_subquery(plans_end=…)`).
- **Reset** is offered for any month from `plan_from` on. After a settings change
  that includes the current month.
- **Quick-assign on a linked goal** (`_plan_more_for_linked_goal`) adds to this
  month's plan. With no amount it plans what's available, capped for a target goal
  at `target − saved − held`. The goals page's "still to put in" for a linked goal
  subtracts what the plan already holds.
- **The held line** reads "$X to move" (the linked accounts are in its tooltip),
  because naming the accounts inline widened the whole budget table.
- **The monthly review card** (`goal_plan_unmet`) only appears once the month is
  over. It says "went back to Unassigned" (`release`) or "carries into next month"
  (`carry`).
- **The Dollar Map** lists a linked goal with nothing left but money still held,
  and shows that money as its own hatched segment and waterfall step.
