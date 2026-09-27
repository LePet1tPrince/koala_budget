# Reports consolidation

Reference for replacing the seven standalone reports with three reports plus
progress bars on the budget page. The new reports live beside the old ones
(nothing old was changed) so the two sets can be compared before the old ones
are deleted.

## 1. What exists today

Reports home (`/reports/`) linked nine things. Two are workflows, not reports:
**Monthly Review** (stays) and **Reconciliation Status**, which moved to a
**Reconciliations** tab in Accounts (§7). The account
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
| Composition tab (two stacked-area charts: assets, liabilities) | Merge | one diverging stacked area on Net Worth → **By group** (default view): assets up from zero, debts down, net-worth line through the middle (§3B) |
| Monthly table (assets, liabilities, NW, change) | **Cut** | every value is in the chart tooltip |

### 4. Cash Flow

| Element | Verdict | Where / why |
|---|---|---|
| Money in / out / net / average per month | Merge | Income & Spending stats (avg is the net's sub-line) |
| In/out bars + net line (+ goal spending) | Keep | Income & Spending hero chart (same chart code) |
| Monthly in/out/net table | **Cut** | identical to the Income / Expenses / Net rows of the statement in *By period* |

### 5. Budget vs Actual

The whole report moves onto the **budget page** (§3D); no report replaces it.

| Element | Verdict | Where / why |
|---|---|---|
| Per-category meters (expense + income) | Keep | budget page, new progress column; they update as amounts autosave |
| Budgeted / Spent / Left columns | Merge | the budget page's own Budgeted / Actual / Available columns |
| "Left" = budget − spent this month | **Replaced** | by **Available** (rollover included), which the budget page already shows. The old "Left" disagreed with it whenever money rolled over |
| "Over" / "No budget" badges | Merge | the bar turns red when Available < 0 (the page's existing Cover button appears on the same rows); over-budget-but-covered-by-rollover is not flagged, because nothing is wrong |
| Summary stats (Budgeted / Spent / over-count) | Merge | the budget page's sidebar summary |
| Goals "pay yourself first" (assigned / needed / spent) | Merge | with Goal Progress rows in Budget & Goals (§6) |

### 6. Goal Progress

| Element | Verdict | Where / why |
|---|---|---|
| Per-goal allocated / spent / left / target / % / target date | Merge | Budget & Goals → Goals, one row per goal |
| Needed per month | Merge | one formula: BvA's (measured from the start of the month, so assigning doesn't move the target). Goal Progress used a second formula from today; the two disagreed mid-month |
| Totals (saved, target, overall %) | Keep | Goals section header |
| "Saved over time" chart (8 lines + dashed projections + dotted spent) | **Cut** | the densest chart in the app for what the progress bar, "needed this month" and target date already state. Per-goal history remains on the goal's account page (Allocated vs Spent chart) |

### 7. Dollar Map

Budget & Goals **is** the Dollar Map, with one change.

| Element | Verdict | Where / why |
|---|---|---|
| Stats (net worth, in envelopes, in goals, Unassigned) | Keep | Budget & Goals stats |
| Allocation bar with net-worth marker | Keep | same include |
| Goals list | Merge | with Goal Progress into the Goals table |
| **Envelope list** (one line per category) | **Cut → one total** | the card shows total allocated, split into rolled over / this month's unspent budget, plus overspent-carried. Per-category detail is on the budget page |
| Overspent list | **Cut → one total** | a line on the envelopes card |
| Income-due list | **Cut → one total** | a line on the Unassigned card |
| Waterfall chart + table | Keep | unchanged, below the report |

## 3. The three reports, and the budget page

Each page: one header (title, one time control, one secondary action), one stats
strip (≤4), one hero visual, one table. Sub-views are one toggle deep.

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
- Hero, two views of one chart card:
  - **By group** (default): diverging stacked area. Each account group is a band
    signed by its effect on net worth — assets stack up from zero, debts down —
    and the net-worth line runs through; every month the bands sum exactly to the
    line. A group that crosses zero (overdraft, card in credit) is split by sign
    and the part on the unexpected side is **hatched**; legend and tooltip still
    treat it as one group. At most 5 asset bands and 3 debt bands (tail folds into
    "Other assets"/"Other debts"); hue order per side validated with the dataviz
    palette checker in light and dark (`net-worth-composition-chart.js` header).
  - **Totals**: assets/liabilities bars + net-worth line (the old chart).
- Table: assets and liabilities by group, **Start / End / Change** per account,
  group and section; Net worth row in the footer.

### C. Budget & Goals — `reports:budget_goals` (`/reports/budget-and-goals/`)

*Where is every dollar going?* Replaces 6 + 7. It is the Dollar Map with the
envelopes as one total.

- Control: month (prev / this / next).
- Stats: Net worth (+ income due) · In budget envelopes · In goals · Unassigned.
- Hero: allocation bar.
- Cards: **Budget envelopes** (total allocated; rolled over / this month's unspent;
  overspent carried) · **Unassigned** (with income still due).
- **Goals** table: saved toward target, by-date, this month assigned vs needed, left.
- Waterfall (net worth → Unassigned), chart + table.

### D. Budget page — progress bars (replaces 5)

Every row of the budget table gets a bar between Category and Budgeted:

- Expense: spent ÷ what there was to spend (this month's budget + positive rollover).
  A full bar means Available = 0. Red once Available < 0.
- Income: received ÷ expected (info colour).
- No budget and some spending: full red bar, "—" instead of a percentage.

`_meter()` in `apps/budget/views.py` computes it; the autosave response carries
`row:<pk>:meter` (`{value, tone, width}`) and `budget-autosave.js` repaints the
bar in place (width animates, off under reduced motion).

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
| Budget vs actual per category + income | D · budget page bars + its own columns |
| Composition (assets / liabilities by group over time) | B · By group chart |
| Dollar Map envelope list | C · envelopes total (per category: budget page) |
| Goal allocated/spent/left/target/%/date/needed | C · Goals |
| Unassigned, allocation bar, the Unassigned sum | C · stats, bar, "How this adds up" |

Deliberately gone: Spending Trends chart, Goal "saved over time" chart, Dollar
Map per-envelope / overspent / income-due lists (now totals), Balance Sheet
equity section, monthly tables on Cash Flow and Net Worth Trend, arbitrary as-of
day, BvA's rollover-blind "Left".

## 6. Deleting the old reports later

Remove the seven views, their templates, their `urls.py` entries, their rows in
`apps/books/tests/test_isolation.py`, their `BACK_LABELS` entries, their tests,
and the reports-home links.

Repoint these links first (old → new):

| Call site | Old | New |
|---|---|---|
| `templates/web/components/app_nav_menu_items.html` (Reports submenu, 6 links) | all six | the three new reports |
| `templates/web/components/app_nav_menu_items.html` (Budget vs Actual) | `budget_vs_actual` | drop (it is the budget page) |
| `templates/web/app_home.html:36` | `dollar_map` | `budget_goals` |
| `templates/web/app_home.html:57` | `income_statement` | `spending` |
| `templates/web/app_home.html:71` | `net_worth_trend` | `net_worth` |
| `templates/budget/components/unassigned_pill.html:24` | `dollar_map` | `budget_goals` |
| `templates/budget/components/budget_table.html:125` | `account_activity?source=budget` | `accounts:account_detail` + `return_to` |
| `apps/onboarding/services/gates.py:94,102` (task `url_name`) | `income_statement`, `net_worth_trend` | `spending`, `net_worth` |
| tests: `apps/budget/test_unassigned.py`, `test_goals_envelopes.py`, `apps/books/tests/test_books.py`, `apps/accounts/tests.py` | old names | new names (the `budget_vs_actual` tests in `test_goals_envelopes.py` / `test_books.py` cover future-income hiding: port them to the budget page) |

Keep these JS entries — the new reports use them: `cash-flow-chart`,
`income-statement-sankey`, `net-worth-chart`, `net-worth-composition-chart`,
`dollar-map-chart`, `ReportsDateRangePicker`, `NetWorthTrendMonthPicker`. Safe
to drop with the old reports: `expense-trend-chart`, `balance-composition-chart`,
`goal-progress-chart`. `ReportService.get_balance_composition_data` stays (the
composition chart reads it). Keep the CSV exports (`export_*`): the new reports link them.
`reports:account_activity` (+ its export) can go once `budget_table.html` is
repointed.

## 7. Reconciliations moved to Accounts

Reconciliation Status left Reports home. The hub (`reconciliation:hub`, URL
unchanged at `/reconcile/`) now renders inside the Accounts shell
(`accounts/manage_base.html`) as a **Reconciliations** tab after Institutions,
with a matching sidebar sub-item; the per-account workspace and statement pages
highlight Accounts → Reconciliations in the nav. The hub keeps its
`reconcile-hub` testid, so the E2E page object is unchanged.
