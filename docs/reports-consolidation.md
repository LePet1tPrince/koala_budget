# Reports consolidation

Reference for replacing the seven standalone reports with three. The three new
reports live beside the old ones (nothing old was changed) so the two sets can be
compared before the old ones are deleted.

## 1. What exists today

Reports home (`/reports/`) links nine things. Two are workflows, not reports, and
are out of scope: **Monthly Review** and **Reconciliation Status**. The account
drill-down (`reports:account_activity`) is a shared detail page, not a report.
That leaves **seven** reports:

| # | Report | URL | Time control | Default |
|---|--------|-----|--------------|---------|
| 1 | Income Statement | `income-statement/` | any date range + Total/Month/Quarter/Year | current month |
| 2 | Balance Sheet | `balance-sheet/` | one as-of day | today |
| 3 | Net Worth Trend | `net-worth-trend/` | month range | last 12 months |
| 4 | Cash Flow | `cash-flow/` | month range | last 12 months |
| 5 | Budget vs Actual | `budget-vs-actual/` | one month | current month |
| 6 | Goal Progress | `goal-progress/` | none | all time |
| 7 | Dollar Map | `dollar-map/` | one month | current month |

They answer three questions, with heavy overlap:

- **Where did money come from and go, over a period?** — 1, 4
- **What am I worth, and how is that changing?** — 2, 3
- **Is my plan holding (budget, goals, unassigned money)?** — 5, 6, 7

Four reports are built on the same query (`get_income_statement_data`: 1, 4, 5 and
the Sankey). Two render the same balance roll-up (`get_balance_sheet_data` and the
trend's running totals: 2, 3). Three read the same budget/goal state (5, 6, 7).

## 2. Element-by-element verdict

`Keep` = in a new report. `Merge` = kept, but combined with a duplicate. `Cut` =
not carried over.

### 1. Income Statement

| Element | Verdict | Where / why |
|---|---|---|
| Total income / expenses / net profit | Keep | Income & Spending stats |
| Savings rate ("% of income kept") | Keep | Income & Spending stats |
| Goal spending + net after goal spending | Keep | stats + statement section |
| Grouped, collapsible P&L table, frozen panes | Keep | Income & Spending → Statement |
| Total / By Month / By Quarter / By Year | Merge | one toggle: **Total \| By period**; the period is picked from the range length (≤24 mo → month, ≤8 yr → quarter, else year) |
| Income Flow (Sankey) | Keep | Income & Spending → Flow tab |
| Spending Trends (stacked bars by expense group) | **Cut** | same numbers as the group rows in *By period*; 8-hue stacked bars are harder to read than the table |
| Account links → drill-down | Keep | now link to the account page with the same range (see §4) |
| Export CSV | Keep | links the existing export |

### 2. Balance Sheet

| Element | Verdict | Where / why |
|---|---|---|
| Total assets / liabilities / net worth | Keep | Net Worth stats |
| Debt ratio ("% of assets") | Keep | Net Worth stats |
| Grouped assets + liabilities table | Keep | Net Worth table, now with **Start / End / Change** columns |
| **Equity section** | **Cut** | holds only bookkeeping plugs (opening balances, reconciliation adjustments). Its total is not net worth (there is no retained-earnings line), so it reads as a second, conflicting "worth" figure. Still in the old balance-sheet CSV |
| Arbitrary as-of **day** | **Cut** | replaced by "as of end of range"; the account page gives any day's balance |
| Export CSV | Keep | links the existing export (as of range end) |

### 3. Net Worth Trend

| Element | Verdict | Where / why |
|---|---|---|
| Net worth, change over period, % change | Keep | Net Worth stats |
| Assets / liabilities bars + net worth line | Keep | Net Worth hero chart (same chart code) |
| Composition tab (stacked areas by group) | **Cut** | the table's per-group Start→End change says what moved net worth, exactly. Monthly Review already draws composition |
| Monthly table (assets, liabilities, NW, change) | **Cut** | every value is in the chart tooltip |

### 4. Cash Flow

| Element | Verdict | Where / why |
|---|---|---|
| Money in / out / net / average per month | Merge | Income & Spending stats (avg is the net's sub-line) |
| In/out bars + net line (+ goal spending) | Keep | Income & Spending hero chart (same chart code) |
| Monthly in/out/net table | **Cut** | identical to the Income / Expenses / Net rows of the statement in *By period* |

### 5. Budget vs Actual

| Element | Verdict | Where / why |
|---|---|---|
| Budgeted / Spent / over-count | Keep | Budget & Goals stats |
| Expense rows with meters, grouped | Keep | Budget & Goals → Spending |
| "Left" = budget − spent this month | **Replaced** | by **Available** (rollover included), the figure the budget page and Dollar Map use. The old "Left" disagrees with the budget page whenever money rolled over |
| "Over" / "No budget" badges | Merge | one **Overspent** badge (Available < 0) + "No budget"; over-budget-but-covered-by-rollover is no longer flagged, because nothing is wrong |
| Income section (future-income books) | Keep | Budget & Goals → Income |
| Goals "pay yourself first" (assigned / needed / spent) | Merge | with Goal Progress rows (§6) |

### 6. Goal Progress

| Element | Verdict | Where / why |
|---|---|---|
| Per-goal allocated / spent / left / target / % / target date | Merge | Budget & Goals → Goals, one row per goal |
| Needed per month | Merge | one formula: BvA's (measured from the start of the month, so assigning doesn't move the target). Goal Progress used a second formula from today; the two disagreed mid-month |
| Totals (saved, target, overall %) | Keep | Goals section header |
| "Saved over time" chart (8 lines + dashed projections + dotted spent) | **Cut** | the densest chart in the app for what the progress bar, "needed this month" and target date already state. Per-goal history remains on the goal's account page (Allocated vs Spent chart) |

### 7. Dollar Map

| Element | Verdict | Where / why |
|---|---|---|
| Unassigned figure + state wording | Keep | Budget & Goals headline stat |
| Allocation bar with net-worth marker | Keep | Budget & Goals, under the stats (same include) |
| Net worth / in envelopes / in goals stats | Merge | "How this adds up" table |
| Waterfall chart | **Cut** | kept as its table ("How this adds up", collapsed). Bars add nothing the seven-line sum doesn't |
| Goals / envelopes / overspent / income-due lists | **Cut** | each figure is already a row: goal *Left*, envelope *Available*, *Overspent* badge, income *To go* |

## 3. The three reports

Each page: one header (title, one time control, one secondary action), one stats
strip (≤4), one hero visual, one table. One page has tabs; none nests.

### A. Income & Spending — `reports:spending` (`/reports/spending/`)

*Where money came from and went, over any range.* Replaces 1 + 4.

- Control: date range, default **this year to date** (the old defaults — one month
  for the statement, twelve for cash flow — were each wrong for the other half).
- Stats: Money in · Money out (+ goal spending) · Kept (savings rate) · Average per month.
- Hero: in/out bars + net line per period.
- Tabs: **Statement** (grouped P&L, Total | By period) · **Flow** (Sankey).

### B. Net Worth — `reports:net_worth` (`/reports/net-worth/`)

*What I own and owe, and what changed.* Replaces 2 + 3.

- Control: month range, default last 12 months. Balances are as of the range end
  (today, if the range reaches it).
- Stats: Net worth · Change over period (%) · Assets · Liabilities (debt ratio).
- Hero: assets/liabilities bars + net-worth line.
- Table: assets and liabilities by group, **Start / End / Change** per account,
  group and section; Net worth row in the footer.

### C. Budget & Goals — `reports:budget_goals` (`/reports/budget-and-goals/`)

*Is the plan holding this month?* Replaces 5 + 6 + 7.

- Control: month (prev / this / next).
- Stats: Unassigned · Spent (of budgeted; overspent count) · In envelopes · Set aside for goals (of needed).
- Hero: allocation bar; "How this adds up" (the Unassigned sum) collapsed beneath.
- Sections: **Goals** (saved toward target, by-date, this month assigned vs needed,
  left) · **Spending** (assigned, spent, meter against what was available to
  spend, Available, grouped) · **Income** (only for books that budget future income).

## 4. Drill-downs

The old reports link to `reports:account_activity`, whose back link is chosen by a
`?source=` flag that only knows the old reports. The new reports link to the
account page (`accounts:account_detail`) instead, carrying the report's range and
`?return_to`, so its back link reads "Back to Income & Spending" etc. The account
page renders the same activity section, balance chart and budget chart. When the
old reports are deleted, `reports:account_activity` and its export can go with them.

## 5. Coverage check (old → new)

| Old figure | New location |
|---|---|
| Income statement totals, groups, accounts, goal spending | A · Statement |
| Per-account per-month amounts | A · Statement, By period |
| Sankey | A · Flow |
| Cash flow monthly in/out/net | A · hero chart; A · Statement By period (totals rows) |
| Balance sheet assets/liabilities by group/account | B · table (End column) |
| Net worth trend points | B · hero chart (tooltip) |
| Budget vs actual per category | C · Spending |
| Budget vs actual income | C · Income |
| Goal allocated/spent/left/target/%/date/needed | C · Goals |
| Unassigned, allocation bar, the Unassigned sum | C · stats, bar, "How this adds up" |

Deliberately gone: Spending Trends chart, Composition charts, Goal "saved over
time" chart, Dollar Map bucket lists and waterfall chart, Balance Sheet equity
section, monthly tables on Cash Flow and Net Worth Trend, arbitrary as-of day,
BvA's rollover-blind "Left".

## 6. Deleting the old reports later

Remove the seven views, their templates, their `urls.py` entries, their rows in
`apps/books/tests/test_isolation.py`, their `BACK_LABELS` entries, their tests,
and the reports-home links.

Repoint these links first (old → new):

| Call site | Old | New |
|---|---|---|
| `templates/web/components/app_nav_menu_items.html` (Reports submenu, 6 links) | all six | the three new reports |
| `templates/web/app_home.html:36` | `dollar_map` | `budget_goals` |
| `templates/web/app_home.html:57` | `income_statement` | `spending` |
| `templates/web/app_home.html:71` | `net_worth_trend` | `net_worth` |
| `templates/budget/components/unassigned_pill.html:24` | `dollar_map` | `budget_goals` |
| `templates/budget/components/budget_table.html:125` | `account_activity?source=budget` | `accounts:account_detail` + `return_to` |
| `apps/onboarding/services/gates.py:94,102` (task `url_name`) | `income_statement`, `net_worth_trend` | `spending`, `net_worth` |
| tests: `apps/budget/test_unassigned.py`, `test_goals_envelopes.py`, `apps/books/tests/test_books.py`, `apps/accounts/tests.py` | old names | new names |

Keep these JS entries — the new reports use them: `cash-flow-chart`,
`income-statement-sankey`, `net-worth-chart`, `ReportsDateRangePicker`,
`NetWorthTrendMonthPicker`. Safe to drop with the old reports:
`expense-trend-chart`, `balance-composition-chart`, `goal-progress-chart`,
`dollar-map-chart`. Keep the CSV exports (`export_*`): the new reports link them.
`reports:account_activity` (+ its export) can go once `budget_table.html` is
repointed.
