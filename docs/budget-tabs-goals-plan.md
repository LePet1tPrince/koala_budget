# Budget page: goals as budget rows, condensed rows, section tabs

Status: built — steps 1–2 (density + tabs) in one PR, step 3 (goals) in its own PR · Scope: `/a/{team}/{book}/budget/` (single-month page only)

Three changes, one page:

1. **Goals are budgeted on the budget page.** A goal row's Budgeted amount *is* the month's
   `GoalAllocation` — the same record the goals page writes. Available = the goal's cumulative
   saved balance as of the month end.
2. **Denser rows.** Smaller inputs, less padding, one header row per group instead of header + subtotal.
3. **Tabs: Income · Goals · Expenses.** One section on screen at a time.

No migrations. No change to the Unassigned formula. No change to the goals page.

---

## 1. Current state (facts the plan builds on)

| Fact | Where |
|---|---|
| Every figure on the page comes from `_budget_figures(book, month)`; sections are `income`, `expense` only. | `apps/budget/views.py:75` |
| Categories = income/expense accounts (`_budget_categories`, `budgeted_account_types`). Goal backing accounts are equity → never listed. | `apps/budget/views.py:549`, `services.py:19` |
| Autosave posts `{category_id, month, amount}` to `budget_save_amount`, which returns `cells` (`_budget_cells`) keyed like the templates' `data-budget-cell`. | `views.py:352`, `views.py:209`, `assets/javascript/budget/budget-autosave.js` |
| Month change swaps `#budget-swap` in place, re-fetching the current URL with `?month=` replaced (other query params kept). | `assets/javascript/budget/month-swap.js` |
| Goal money: `GoalAllocation(book, goal, month, amount)`, unique per `(book, goal, month)`; withdrawals are negative allocations. | `apps/budget/models.py` |
| Goals page *adds* to the month's allocation (`goal_assign_available`, `goal_withdraw`); `goal_allocation_update_view` (no-JS) *sets* it with no closed/cap checks; `GoalService.edit_allocation` sets it with closed/archived refusal and the "can't take back spent money" cap. | `views.py:966`, `views.py:1058`, `views.py:1485`, `services.py:456` |
| `with_progress(month)`: `saved_previous`, `saved_this_month`, `spent` (through month end), `spent_this_month`. **`allocated`/`left` are all-time** (future-month allocations included). | `models.py` `GoalQuerySet.with_progress` |
| Unassigned subtracts `Σ max(0, allocated_to_month_end − spent_to_month_end)` over non-archived goals. Goal allocations already move Unassigned; nothing new to wire. | `apps/budget/unassigned.py` |
| Row markup today: `table table-sm`; amount input `input input-bordered input-sm w-28` in a `py-1` cell (~40px row); per group: header row + rows + subtotal row; per section: header row (`text-lg`) + total row + spacer row. | `templates/budget/components/budget_table.html`, `apps/budget/forms.py:71` |
| Sidebar summary sums income + expense together (`sidebar:assigned`, `sidebar:available`). Auto-Assign scopes by `.budget-row-checkbox` across the whole page. | `templates/budget/components/budget_sidebar.html` |

---

## 2. Decisions

| # | Decision | Status |
|---|---|---|
| D1 | **Goal row Available = the goal's balance at month end** = Σ allocations through the month (manual + linked accounts) − Σ spent through the month. For a goal never spent from, this **equals cumulative saved**. Alternative (literal "cumulative saved", ignoring spending) rejected: it would break the row equation `Available = previous + Budgeted − Actual`, disagree with the goals page's "Left", the Cover dialog, and Unassigned. | Confirmed |
| D2 | **Goal row Budgeted = this month's manual `GoalAllocation.amount`**, editable. Typing **sets** it (like every budget cell), the goals page buttons **add** to it — same row either way. Money from linked accounts is not editable here; it shows as a note ("+ $120 from Savings") and counts in Available. | Recommended |
| D3 | **Goal row Actual = spent from the goal this month** (`spent_this_month`: goal-account lines + linked spending). Column header on the Goals tab reads "Spent". | Recommended |
| D4 | **Default tab = Expenses.** Last tab remembered in a `budget_tab` cookie; `?tab=` overrides. | Recommended |
| D5 | **Tab labels carry the section's Budgeted total** ("Income $5,000 · Goals $1,200 · Expenses $3,800"), so the split of income is readable without switching. Expenses tab adds an overspent-count badge, Goals a behind-plan count. | Recommended |
| D6 | Multi-month grid (`budget/grid/`) does **not** get goals in this change. | Out of scope |

---

## 3. Part A — Goals on the budget page

### 3.1 Which goals are rows

For month **M**: goals with `is_archived=False`, and either open (`closed_at IS NULL`) or with a non-zero Budgeted/Spent/Available figure for M (closed during or after M). Closed rows render read-only with a `Closed` badge. Order = `Goal.Meta.ordering` (`order`, `target_date`, `name`). One group, no group header row.

**Invariant (tested):** `Σ max(0, row.available)` over goal rows == `compute_unassigned(book, M).goals`. Guarantees the Goals tab and the net-worth card's "In goals" agree.

### 3.2 Figures — `_goal_section(book, month)` in `views.py`, called from `_budget_figures`

One `with_progress(M)` query + one `GoalAllocation` query for M:

| Field | Source |
|---|---|
| `budgeted` | `GoalAllocation.amount` for (goal, M), else 0 |
| `linked` | `saved_this_month − budgeted` (what linked accounts brought in during M) |
| `actual` | `spent_this_month` |
| `available` | `saved_previous + saved_this_month − spent` (month-end; **not** `goal.left`, which counts future months) |
| `previous` | `available − budgeted − linked + actual` (for the sidebar's "left over") |
| `meter` | `_goal_card_progress(goal, saved_previous + saved_this_month, saved_this_month)` — the goals page's bar function (target: saved ÷ target; open-ended: this month ÷ monthly contribution), fed month-end figures instead of the goals page's all-time `allocated`. New CSS variant `.budget-meter.is-goal` (`--meter: var(--color-secondary)`, the equity hue used on the balance sheet). |
| `plan` | `goal_plan(goal, M)` → muted inline text after the name: "$417 needed", "Funded", "Open-ended · $200/mo", or nothing. |

`sections` becomes `[income, goal, expense]` (income omitted when `budget_future_income` is off, as now). Section key `"goal"`, label "Goals".

### 3.3 Saving — one writer

New `GoalService.set_month_allocation(goal, month, amount)` (in `services.py`):

- refuses archived / closed goal → `GoalAllocationError`;
- if `amount < current`, refuses when the goal's balance (as of `max(this month, latest allocation month)`) would go below 0 — the existing `edit_allocation` cap and message;
- `amount == 0` deletes the row; otherwise upsert;
- returns the old amount.

`edit_allocation(allocation, amount)` becomes `set_month_allocation(allocation.goal, allocation.month, amount)`. `goal_allocation_update_view` (no-JS goals page) switches to it, gaining the closed/cap checks it lacks today.

Endpoint: **extend `budget_save_amount`** — body takes `goal_id` *or* `category_id` (both or neither → 400).

- `goal_id` resolved with `Goal.objects.filter(book=request.book)` → another book's id is a 400, nothing written.
- `GoalAllocationError` → 400 `{error}`; the existing client `fail()` path shows it (toast + `input-error`, value left in place).
- Change logged as `AuditEvent.GOAL_CONTRIBUTION_EDITED` with `{goal_id, goal_name, month, from, to, undo, via: "budget"}` (existing type; metadata only, no migration).
- Response: same shape, `cells` from `_budget_figures`.

No-JS: `budget_month_view` POST accepts `goal_id` + `budget_month` + `budget_amount` → `set_month_allocation`.

### 3.4 Cells

| Key | Value |
|---|---|
| `goal:<goal_pk>:available` | toned currency |
| `goal:<goal_pk>:meter` | `{value, tone, width}` |
| `goal:<goal_pk>:budgeted` | raw `"0.00"` (Auto-Assign confirm reads it off the checkbox, as for categories) |
| `group:goal:0:budgeted\|available`, `section:goal:budgeted\|available` | as for other sections |

`budget-autosave.js`: `makeRow` reads `data-goal-id` or `data-category-id` and posts the matching key; checkbox map keyed `goal:<pk>:budgeted` for goal checkboxes.

### 3.5 Interactions

- **Unassigned**: typing $X into a goal moves Unassigned by −$X (the pill already re-reads after every non-GET fetch). Filling a negative goal's hole leaves Unassigned unchanged up to the shortfall (`max(0, left)` term) — same as on the goals page.
- **Cover dialog**: `cover_goals[].left` switches from `goal.left` (all-time) to the row's month-end `available`, and is repainted from the `goal:<pk>:available` cell after a save, so the dialog never offers a stale balance.
- **Actual popover**: not mounted on goal rows (linked spending has no lines on the goal account, so the popover's list would not sum to the figure). Spent links to `goal_detail#activity`.
- **Hide**: not offered on goal rows. Closing the goal is the equivalent; a row link opens the goal page.
- **Goals page**: unchanged. Assigning there and typing here edit the same `GoalAllocation`.

---

## 4. Part B — Condensed rows

All in `budget_table.html`, `forms.py`, `app-components.css`.

| # | Change | Rows saved / height |
|---|---|---|
| C1 | `.budget-table :where(tbody td)` → `padding-block: 0.125rem; padding-inline: 0.5rem` (keeps `table-sm`'s 0.75rem font). | — |
| C2 | Amount input `input-sm w-28` → `input-xs w-24 text-xs` (24px vs 32px with `--size-field: 0.25rem`). Drop the cell's `py-1`. | row ≈ 28px from ≈ 40px |
| C3 | Category cell: drop the `<div class="font-medium">` wrapper, `pl-8` → `pl-4`, `truncate max-w-64` + `title` = full name. Goal plan text sits on the same line. | no wrapped rows |
| C4 | **Group header carries the subtotals** (Budgeted / Actual / Available on the header row, as the hidden group already does). Subtotal row removed. | −1 row per group |
| C5 | Section header row and spacer row removed (the tab names the section, Part C). Section total moves to a `<tfoot>` row, `position: sticky; bottom: 0`, opaque background. | −2 rows per section; total always visible |
| C6 | "How it works" alert → closed `<details>` ("How Available works") under the table. | ~120px less scroll |
| C7 | Meter column `w-32` → `w-28`; meter label stays. | — |

Acceptance: a `budget-row`'s `getBoundingClientRect().height` ≤ 28px at default zoom (E2E assertion, ±1px); no horizontal scroll at ≥ `lg`; testids unchanged.

---

## 5. Part C — Tabs

### 5.1 Markup (`budget_table.html` → one panel per section)

- Tab bar between the net-worth card and the table: `role="tablist"`, `tabs tabs-box`, one `<a role="tab" href="?tab=<key>&month=…" aria-selected aria-controls>` per section, `data-testid="budget-tab-<key>"`. Label + `data-budget-cell="tab:<key>:budgeted"` figure (D5) + badge.
- One panel per section: `<div role="tabpanel" id="budget-panel-<key>" data-testid="budget-panel-<key>">` holding **its own `<table>`** (own `thead`, own select-all checkbox, own sticky `tfoot` total). Inactive panels carry `hidden`, set **server-side** from the resolved tab → correct first paint, works without JS (tabs are plain links).
- Goals tab headers: Budgeted · Spent · Available. Income/Expenses unchanged.

### 5.2 State

Resolution (server, `_budget_tab(request, sections)`): `?tab=` → `budget_tab` cookie → `"expense"`; a value naming an absent section (income with future income off) falls back to `"expense"`. `budget_category_visibility`'s fragment renders with tab = the category's own section.

Client (new `assets/javascript/budget/budget-tabs.js`, imported by the page): click/keyboard switches `hidden` + `aria-selected`, `history.replaceState` sets `?tab=`, writes the cookie (`SameSite=Lax`, path `/`, 1 year). Month swaps keep `?tab` because `urlForMonth` copies the current URL. Re-binds on `budget:swapped`.

Keyboard: ←/→/Home/End within the tablist (WAI-ARIA tabs, automatic activation).

### 5.3 Sticky stack

Page header (`--budget-header-h`) → tab bar (`top: var(--budget-header-h)`, publishes `--budget-tabs-h` via `ResizeObserver`, same pattern as the header) → `thead th` at `top: calc(var(--budget-header-h) + var(--budget-tabs-h))` → sticky `tfoot`.

### 5.4 Things that must become tab-scoped

| Thing | Change |
|---|---|
| Autosave Enter/↑/↓ (`focusRow`) | skip inputs with any `[hidden]` ancestor (`closest('[hidden]')`, replacing `closest('tr[hidden]')`), so focus never moves into another tab. |
| Select-all + shift-click | per panel. |
| Sidebar summary | three summary blocks, one per section, shown with their tab (`data-tab-for="<key>"`). Keys `sidebar:<key>:assigned\|available` replace `sidebar:assigned\|available`. Goals block: Saved before {month} · Budgeted · From linked accounts · Spent · Available. |
| Auto-Assign | card shows the active tab's actions; checked rows read from the active panel only. `budget_autofill_view` gains `section` (`income\|expense\|goal`) and only touches that section (the no-JS forms post it too). Goals actions: **Assigned last month** (copy previous month's manual allocations), **Monthly plan** (set to `goal_plan(...)["needed"]` for goals that have a plan), **Assign zero**. Every goal write goes through `set_month_allocation`; refusals (closed, cap) are listed in the flash message, the rest applied. No "Spent last month" / "Reset available to zero" for goals. |
| Hidden categories | unchanged, inside their tab's panel. `budget-hidden-open` storage keyed by section as now. |

---

## 6. Files

| File | Change |
|---|---|
| `apps/budget/views.py` | `_goal_section`; `_budget_figures` adds goal section + per-section sidebar summaries; `_budget_cells` goal/tab/sidebar keys; `budget_save_amount` `goal_id`; `budget_month_view` no-JS `goal_id` + tab context; `_budget_tab`; `budget_autofill_view` `section` + goal actions; `budget_category_visibility` tab; `cover_goals` month-end balance |
| `apps/budget/services.py` | `GoalService.set_month_allocation`; `edit_allocation` delegates to it |
| `apps/budget/forms.py` | `BudgetAmountForm` widget classes (C2) |
| `templates/budget/components/budget_table.html` | tab bar, panels, goal rows, merged group headers, sticky tfoot, `<details>` |
| `templates/budget/components/budget_sidebar.html` | per-section summary + Auto-Assign blocks |
| `templates/budget/budget_home.html` | load `budget-tabs.js` |
| `assets/javascript/budget/budget-autosave.js` | goal rows, tab-aware `focusRow`, cover reads goal balance from cells |
| `assets/javascript/budget/budget-tabs.js` | new (Vite entry) |
| `assets/styles/app/tailwind/app-components.css` | `.budget-table` density, `.budget-meter.is-goal`, sticky tab bar/tfoot |
| `e2e/pages/budget.py` | `select_tab(key)`, `active_tab()`, `goal_row(name)`, `set_goal_budget(name, amount)` |

---

## 7. Tests

**Backend** (`apps/budget/tests.py`, new `apps/budget/test_budget_goals.py`):

- Goal section figures: budgeted/linked/actual/available per §3.2, including a linked account and a future-month allocation (available ≠ `goal.left`).
- Invariant §3.1 against `compute_unassigned` for: plain goal, overspent goal, goal closed in M, goal closed before M, future allocation.
- Save: sets (not adds); 0 deletes the row; closed / archived → 400; lowering below spent → 400, nothing written; another book's `goal_id` → 400; both/neither id → 400; audit event with `via: "budget"`; response cells include `goal:*`, `section:goal:*`, `networth:*`; goals page reads the same amount afterwards.
- No-JS POST with `goal_id`.
- `goal_allocation_update_view` now refuses a closed goal.
- Autofill per section: income/expense untouched by a `goal` run and vice versa; goal actions incl. a refused goal.
- Tab resolution: query > cookie > default; income tab absent with future income off → expense; visibility fragment opens the category's tab.
- Update existing assertions on `sidebar:assigned` (`tests.py:548`) to the per-section keys.

**Isolation** (`apps/books/tests/test_isolation.py`): `budget_save_amount` stays in `WRITES`; add an explicit cross-book `goal_id` case.

**E2E** (`e2e/tests/test_budget.py`):

- Goals tab: type 250 into a goal row → row Available +250, pill −250, goals page card shows 250 this month.
- Tabs: only the active panel visible; `?tab=` in URL; reload and month change keep the tab; ↓ from the last Income row does not focus an Expenses input.
- Density: row height ≤ 28px.
- Existing tests: `budget-row` testid stays on income/expense rows only (goal rows use `budget-goal-row`), so `get_budget_row_count` is unchanged; `budget-grand-total` / `budget-total-income` move into the tfoot of their panels (still in the DOM; `test_books.py` counts unaffected).

---

## 8. Build order (one PR each)

1. **Density (C1–C4, C6–C7).** Template/CSS only; no behaviour change. Smallest diff, measurable.
2. **Tabs (Part C + C5)** for Income/Expenses: panels, sticky stack, tab state, per-section sidebar + Auto-Assign scoping.
3. **Goals (Part A)**: `set_month_allocation`, goal section, save path, Goals tab, goal Auto-Assign actions.

Each PR updates `CLAUDE.md` "Recent Changes".

---

## 9. Risks

| Risk | Mitigation |
|---|---|
| Two meanings of "left" (all-time vs month-end) leak into the page | Rows and cover dialog use month-end only; invariant test against `compute_unassigned`. |
| Save latency: `_budget_figures` adds two goal queries per save | Measure before/after on the YNAB sample book; goal subqueries are already used per page load on the goals page. |
| Sticky offsets wrong when the header wraps (narrow widths) | Both heights published by `ResizeObserver`, never hard-coded. |
| Hidden panels still hold checked checkboxes → Auto-Assign hits rows not on screen | Auto-Assign reads the active panel only; server enforces `section`. |

---

## 10. Build notes (what changed from the plan)

Steps 1 and 2 shipped together, as one PR.

- **Row height is 25px**: a 20px field (`.budget-amount` trims `input-xs`'s 24px height — daisyUI sizes an input by height, so the box is the padding) + 2×2px cell padding + the row's 1px border. The table's `btn-xs` buttons are trimmed to 20px too, or the Hide button holds the row at 29px. The E2E guard is ≤ 26px row, ≤ 20px field.
- **The amount field is `max-w-24`**, not `w-24`: the shared widget template prepends `w-full`, which had always overridden the width class (the old `w-28` never applied).
- **Column headings and the total stick from `lg` up only.** Below `lg` a panel scrolls sideways, which makes it a scroll container; a sticky offset inside it pushed the headings down over the rows. The tab bar sits outside the panels and sticks at every width.
- **`budget-table` stays on the outer card** (one element, as the page objects expect); each panel's table is `budget-table-<key>`.
- **Phone layout fixed in passing**: below `lg` the fixed-width sidebar covered the table. The sidebar now sits below the table there, full width and not sticky.
- **Auto-Assign is per tab** in step 2 already (one button set per section, each posting `section`), so step 3 only adds the Goals tab's set.

Step 3:

- **The Goals tab exists without future income**: tabs are `[income?, goal, expense]`.
- **The goal tab's empty state links to New Goal**; a book with goals but no categories still gets the tabs.
- **One group, no group header row** on the Goals tab: the section total in the tfoot is the only subtotal.
- **`goal_allocation_update_view` (the goals page's no-JS "Set month") moved onto `set_month_allocation` too**, so it gains the closed/archived refusal and the spent-money cap it never had.
- **Idle fields follow their cells.** Covering a category from a goal changes that goal's contribution for the month, so `budget-autosave.js` updates any field nobody is typing in from its repainted `:budgeted` cell.
