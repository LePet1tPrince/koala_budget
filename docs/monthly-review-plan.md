# Guided Monthly Review — Plan & Requirements

Status: proposal. No code written yet. Implement §7 in order.

Reference design: `docs/reference/bender_review_2026_08.html` (committed on `develop`) —
a hand-built static dashboard with a 9-slide guided walkthrough over it. This plan
reproduces its structure and narrative voice against live Koala data, **minus the
mortgage/housing slide and every housing metric** (that feature does not exist yet), and
adds a new first step the reference does not have: a transaction-and-reconciliation
health check.

---

## Context

Koala's six reports each answer one question in isolation. Nothing walks a user through
their month. After the monthly work is done — import, categorize, reconcile — the user is
left staring at a list of report links with no idea which one to open or what it should
say.

The onboarding walkthrough solved the same problem for first-run. This does it for the
recurring loop: **once a month, hold the user's hand through their own numbers and tell
them what changed.**

Two things must be true that are not true of the existing reports:

1. **It must first tell the user whether the data is trustworthy.** A report built on a
   month with three uncategorized transactions and a credit card that has not synced since
   the 9th is worse than no report — it is confidently wrong. Step 1 exists to catch the
   missing-data case *before* showing a single figure.
2. **Every figure must be measured against something.** "You spent $4,210" is not an
   insight. "You spent $4,210 — $680 more than your 3-month average" is. This is the
   single most important thing the reference document does, and it does it with a
   user-switchable comparison window that applies to every screen at once.

Decisions locked (from review, 2026-09-18):

- Lives under Reports: `/a/{slug}/reports/monthly-review/?month=YYYY-MM`.
- The walkthrough ends on a **permanent month dashboard** at that same URL — always
  viewable on its own, for any month, without re-walking the steps.
- Insights are **deterministic Python rules**. No LLM. No `apps/ai` involvement.
- No mortgage, housing, property, or equity-in-a-house metrics anywhere.

---

## 1. What already exists (reuse, don't rebuild)

| Piece | Where | Use here |
|---|---|---|
| Income/expense figures, grouped, per period | `apps/reports/services.py::ReportService.get_income_statement_data(start, end, period=)` | The engine for every income & spending figure, including the 12-month matrix |
| Balance sheet | `ReportService.get_balance_sheet_data(as_of)` | Net worth step, composition table |
| Net worth series | `ReportService.get_net_worth_trend_data_by_date_range(start, end)` | Net worth chart (returns `assets`/`liabilities`/`net_worth` per month) |
| Balance composition by group | `ReportService.get_balance_composition_data(start, end)` | The stacked "what it is made of" chart |
| Budget vs actual merge | `apps/reports/views.py::budget_vs_actual` → nested `build_section()` | **Port this into a service** — it is already the exact spent/assigned/over/unbudgeted merge the budget steps need |
| Rollover `available` | `apps/budget/services.py::BudgetService.get_available_by_category(month, categories)` | The overspent-vs-covered-by-carryover distinction (§4.3). Use this bulk method, **not** the recursive `available()` |
| Budget category ordering | `apps/budget/views.py::_budget_categories(team)` | Income-first ordering so the breakdown matches the budget page |
| Reconciliation state | `JournalLine.is_reconciled` (`apps/journal/models.py:136`) | Step 1 |
| Per-account feed activity | `apps/bank_feed/views.py::_annotate_feed_account_activity(accounts, team)` | Step 1 — already computes `uncategorized_count`, `latest_transaction_date`, `latest_reconciled_date` in 3 fan-out-safe queries |
| Balance annotations | `apps/accounts/querysets.py` — `with_balance()`, `with_categorized_balance()`, `with_reconciled_balance()`, `NOT_VOID` | Step 1 |
| Goal allocations | `apps/budget/models.py::GoalAllocation`, `GoalQuerySet.with_progress()` | The saving step |
| Series folding to 8 | `apps/reports/views.py::_fold_group_series`, `_fold_float_series`, `CHART_SERIES_LIMIT` | Every chart |
| Chart palette + theme | `assets/javascript/reports/chart-theme.js` (`MONEY`, `seriesColors`, `getInk`, `getSurface`, `GRID`, `observeTheme`, `currency`, `monthLabel`) | Every chart |
| Guided-flow architecture | `apps/onboarding/` end to end | The pattern this app clones — see §5 |
| Shared UI primitives | `assets/javascript/common/` — `Modal`, `Toast`, `Icon`, `Spinner`, `PickerPopover` | The walkthrough chrome |
| Month picker | `assets/javascript/budget/react/BudgetMonthPicker` | Month selection on the dashboard |
| Month stickiness | `apps/budget/views.py::_month_from_request` (session-persisted) | Same pattern for `?month=` |
| `currency` filter | `apps/web/templatetags/currency_tags.py` | Server-rendered figures |
| Audit events | `apps/audit/utils.py::log_event` | Funnel instrumentation |

**Nothing equivalent exists.** Grep confirms no monthly-review, insight-generation, or
narrative code anywhere in the repo.

---

## 2. Architecture decision: one payload, no fetching

The reference document precomputes **every comparison window at once** and switches
between them client-side with zero recomputation. Copy this exactly. It is why its
baseline toggle feels instant and why every slide can share one number set.

Consequence: **the whole review is one JSON blob shipped in `json_script` on the page.**
No data endpoint, no loading spinner, no request waterfall.

- Changing the **baseline** (1m / 3m / 6m / 12m) is pure client-side reslicing.
- Changing the **month** is a full page navigation to `?month=YYYY-MM`.
- The only POSTs are tiny state writes (step seen, review completed, review dismissed).

This is materially simpler than onboarding's chatty endpoint set, and it is affordable:
the expensive work is *one* `get_income_statement_data(period="month")` call across the
13-month window, from which all four baselines are arithmetic.

**Both the walkthrough and the dashboard are React**, rendered from the same payload by
the same components. Rendering the dashboard in Django would mean writing every table,
delta and drill-down twice, and the baseline toggle would need a round trip.

### Payload budget
Cap drill-down transaction lists at **200 rows per category** and the "biggest
transactions" list at **25**. Measure the payload on a 300-transaction month during
implementation; if it exceeds ~250 KB, move `cat_txns` behind a lazy
`GET .../transactions/?category=<id>&month=` endpoint and keep everything else inline.

---

## 3. Data contract

One builder assembles everything:

```python
# apps/monthly_review/services/review.py
def build_review(team, month: date) -> dict:
    """Everything the walkthrough and the dashboard need, for one month,
    with every comparison baseline precomputed. Pure read; no writes."""
```

Returned shape (this is the contract the React app codes against — keep it stable):

```python
{
  "month": "2026-08-01",
  "month_label": "August 2026",
  "prev_label": "July 2026",
  "is_current_month": False,          # partial months get a warning banner

  "health": { ... },                  # §4.1

  "current": {                        # the month under review
    "income": Decimal, "spend": Decimal, "net": Decimal,
    "saved": Decimal, "savings_rate": float,
    "transaction_count": int,
  },

  "baselines": {                      # keyed "1m" | "3m" | "6m" | "12m"
    "3m": {
      "id": "3m", "label": "3-month average", "short": "3-mo",
      "against": "the 3-month average",       # sentence fragment for ledes
      "span": "May – Jul 2026",
      "months": 3,
      "clamped": False,               # True when the ledger starts inside the window
      "keys": ["2026-05-01", ...],
      "avgs": {"income", "spend", "net", "saved", "savings_rate"},
      "streams": [{"payee", "amount", "avg", "vs_avg", "new": bool}],
      "cat_avg": {account_id: Decimal},
      "saving_rows": [{"goal", "amount", "prev", "avg", "vs_avg"}],
    },
    ...
  },
  "baseline_order": ["1m", "3m", "6m", "12m"],
  "default_baseline": "3m",

  "budget": {                         # §4.4
    "groups": [{"name", "assigned", "spent", "prev", "available", "count",
                "categories": [{"id","name","assigned","spent","prev",
                                "available","count","unbudgeted"}]}],
    "totals": {"assigned", "spent", "available"},
    "overspent":      [{"category","group","assigned","spent","available","over"}],
    "over_assigned":  [ same shape ],
  },

  "biggest": [{"date","payee","category","account","amount","entry_url"}],
  "cat_txns": {account_id: [{"date","payee","memo","account","amount"}]},

  "net_worth": {
    "series":  [{"key","label","net","assets","liabilities"}],   # 13 months
    "stack":   [{"bucket","values":[float]}],                    # by account group
    "now": {"net","assets","liabilities"},
    "prev": {...},
    "by_account": [{"name","type","balance","change"}],
  },

  "insights": [ {Insight}, ... ],     # §6
  "notes": [str, ...],                # "How these numbers are built" footnotes
}
```

### Baseline rules (non-negotiable — these are what make the comparison honest)
- **A baseline never includes the month under review.** `3m` for August 2026 means May,
  June, July.
- A baseline is **clamped** to the team's first month of activity. A 12-month baseline on
  a 4-month-old ledger becomes a 4-month baseline with `clamped: True`, and every screen
  says "clamped to where the data starts". Never average over months that do not exist —
  that is how you tell someone their spending doubled when they simply have no history.
- `1m` is literally last month, not an average. Where a table would show two identical
  columns under a 1-month baseline, drop the redundant column (the reference does this on
  the saving step).
- A team with **zero** prior months gets `baselines: {}`, `default_baseline: None`, and
  every screen falls back to absolute figures with an explanatory line. Do not divide by
  zero, do not show "+∞%", do not hide the review.

### Definitions to pin down
- **Income / spend / net** — `get_income_statement_data(month_start, month_end)`:
  `total_income`, `total_expenses`, `net_profit`. Voided entries already excluded.
- **Saved** — `sum(GoalAllocation.amount)` for the month across non-archived goals. This
  is Koala's savings concept (budget-side earmarking), *not* a cash movement into a
  savings account. **Say so in `notes`**, because it will not tie to any bank balance and
  a user who assumes otherwise will think the app is broken. (See §10, open decision 1.)
- **Savings rate** — `saved / income * 100`, `0.0` when income is zero.
- **Streams** — income accounts, but labelled by **payee** where the entry has one, falling
  back to the account name, to match the reference's "where the money came from" framing.
  A stream is `new` when it has activity this month and none in the baseline window.
- **Overspent** vs **over-assigned**: a category is *overspent* when its rollover
  `available` (from `BudgetService.get_available_by_category`) ends the month **negative**;
  it is *over-assigned* when `spent > assigned` but `available >= 0` (carried-over cushion
  absorbed it). These are two different user problems and the reference is right to
  separate them — only the first is a real hole.

---

## 4. The steps

Nine screens. Progress dots, Back / Next, "Skip to dashboard", arrow-key navigation,
clickable dots — all copied from the reference. Steps 2–8 carry the baseline toggle bar;
switching it rebuilds the current step in place.

### 4.1 Step 1 — Is this month's data complete? *(new; not in the reference)*
The trust gate. Per **feed account** (`Account.has_feed=True`, non-system):

| Column | Source |
|---|---|
| Transactions this month | `BankTransaction` count, non-archived, `posted_date` in month |
| Uncategorized | `journal_entry__isnull=True` — same definition as `_annotate_feed_account_activity` |
| Reconciled / unreconciled | `JournalLine.is_reconciled` on the line whose `account` is the bank account |
| Last transaction | `Max("posted_date")`, all time |
| Balance vs reconciled balance | `with_balance()` / `with_reconciled_balance()` |

Flags raised (each becomes an `Insight`, each links to the Inbox filtered appropriately):

- `no_transactions` — a feed account with **zero** transactions in the month. *"Chequing
  has no transactions in August. Did an import get missed?"* — the single most valuable
  flag in the whole feature.
- `stale_account` — last transaction is more than **14 days** before month end (tunable,
  `MONTHLY_REVIEW_STALE_DAYS`, `getattr(settings, ...)` pattern per
  `transfer_detection.get_window_days()`).
- `uncategorized` — count > 0, with the count.
- `unreconciled` — count > 0, with the count and the balance gap.
- `balance_gap` — `balance != reconciled_balance`, showing the difference.

**This step never blocks.** It warns and offers "Fix in Inbox →", and Next always works.
A user reviewing a month they know is incomplete is a legitimate case.

Reaching step 2 with zero flags gets a plain green "Everything's accounted for" state.

### 4.2 Step 2 — The month at a glance
Four cards with vs-baseline deltas: **Money in · Money out · Saved · Left over**.
Baseline toggle introduced here with its explanatory lede ("every baseline is the period
*before* August, never including it").

### 4.3 Step 3 — Where the money came from
Horizontal bar chart, this month vs baseline average, per stream (top 10, tail folded to
"Other" at `CHART_SERIES_LIMIT`). Full table beside it: Source · This month · Average ·
vs average, with a `new` badge, totalled. Lede names the count of streams and the
up/down delta.

### 4.4 Step 4 — What blew through the budget
Two tinted card grids: **Overspent** (red, ended negative) then **Over the assignment**
(amber, covered by carry-over). Each card: category, group, over-by amount, "spent $X
against $Y assigned", ending available. Empty state is a green "Every category stayed
inside its budget."

### 4.5 Step 5 — The biggest line items
Top 10 single transactions: Date · Payee · Category · Account · Amount · Share of spend,
totalled, with the lede stating what share of the month those 10 represent. Rows link to
the transaction.

### 4.6 Step 6 — The whole breakdown
Every category that moved, grouped as the budget groups it, income section first
(`_budget_categories` ordering). Columns: Group/category · Assigned · Spent · Last month ·
vs average · Available · Items. **Click a row to unfold its transactions inline** — they
must reconcile exactly to the "spent" figure.

> Implementation note carried from the reference: build the drill-down `<td>` and set
> `innerHTML` on **it**, not on the `<tr>` — setting HTML on a row parses in row context
> and mis-nests the inner table's `<thead>`. In React this means rendering a real
> `<tr><td colSpan>` sibling, not dangerouslySetInnerHTML on a row.

### 4.7 Step 7 — What we put away
Savings-rate cards (Saved, Savings rate, Left over after everything) plus a per-goal table:
Destination · This month · Last month · [baseline average] · vs baseline. The average
column is **suppressed when the baseline is 1m**, since it would duplicate "last month".
Goal rows carry a progress meter (`progress progress-accent`, as on the dashboard).

### 4.8 Step 8 — What it all adds up to
Stacked net-worth chart over the baseline span (bars when ≤ 4 points — a 2-point area
chart is unreadable), beside a composition table: Type · Balance · Share · Change since
the window start. Lede states the closing figure and the change over the period.

### 4.9 Step 9 — That's the month
Four headline numbers, a short recap, and **"Open the month dashboard →"**. Fires
`fireConfetti({ origin: 'cannons' })` from `assets/javascript/common/confetti.js` —
`'sky'` and `'cannons'` are the only named origins; any other string is read as an
`{x,y}` point and yields NaN.

### 4.10 The month dashboard (the landing surface)
Same payload, everything at once, no step gating. Top to bottom:

1. Header: month title, month picker, baseline toggle, **"▶ Walk me through August"**,
   Export CSV.
2. Health strip — a compact one-line version of step 1; expands on click.
3. The month at a glance — 4 cards.
4. Where it went & what's left — 4 cards.
5. Income sources table.
6. Two charts side by side: income/spend/saving flow · net worth composition.
7. Budget detail table with the same inline drill-down.
8. Two tables side by side: largest transactions · net worth by account.
9. "How these numbers are built" notes list.

---

## 5. Technical design

### 5.1 New app: `apps/monthly_review/`

```
apps/monthly_review/
  apps.py                  MonthlyReviewConfig  → register in settings.PROJECT_APPS
  models.py                MonthlyReviewState
  urls.py                  app_name = "monthly_review"
  views.py                 1 page view + 3 JSON POSTs
  services/
    __init__.py
    health.py              account_health(team, month) -> dict            §4.1
    baselines.py           build_baselines(monthly_matrix, month) -> dict §3
    budget.py              budget_breakdown(team, month) -> dict          §4.4/4.6
    review.py              build_review(team, month) -> dict              §3
    insights.py            generate(review) -> list[Insight]              §6
  migrations/
    0001_initial.py
    0002_existing_teams_have_no_reviews.py   # no-op guard; see below
  tests/
    test_baselines.py test_health.py test_budget.py
    test_insights.py test_review.py test_views.py
```

`services/budget.py` should be written by **moving** the nested `build_section()` out of
`apps/reports/views.py::budget_vs_actual` into a shared service and having both callers
use it. Do not copy-paste it — a second divergent copy of the budget/actual merge is a
correctness bug waiting to happen.

### 5.2 Model

```python
class MonthlyReviewState(BaseTeamModel):
    month = models.DateField()                      # normalized to day 1 in save()
    step = models.PositiveSmallIntegerField(default=0)
    steps_seen = models.JSONField(default=list)
    baseline = models.CharField(max_length=4, default="3m")
    notes = models.TextField(blank=True, default="")
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    dismissed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ["team", "month"]
        ordering = ["-month"]
```

Properties/mutators mirroring `OnboardingState`: `is_finished`, `mark_seen()`, `start()`,
`advance(step)`, `complete()`, `dismiss()`.

Figures are **never** stored — the review always recomputes from the ledger, so correcting
an old transaction corrects every review that touches it. `notes` is the only user content.

Migration `0002` is deliberately a no-op documenting that existing teams need nothing:
a team with no `MonthlyReviewState` row simply has no reviewed months. Do not backfill.

### 5.3 Endpoints

All `@login_and_team_required`; JSON ones also `@require_POST`. Mounted under the existing
reports path so the URL reads as a report:

```python
# koala_budget/urls.py, inside team_urlpatterns
path("reports/monthly-review/", include("apps.monthly_review.urls")),
```

| Name | Path | Purpose |
|---|---|---|
| `monthly_review:home` | `""` | `@ensure_csrf_cookie`. `?month=YYYY-MM` (session-sticky via the `_month_from_request` pattern). Renders the payload into `json_script`. |
| `monthly_review:api_step` | `api/step/` | `{step: int}` → records progress. |
| `monthly_review:api_complete` | `api/complete/` | Marks the month reviewed; returns the recap numbers. |
| `monthly_review:api_dismiss` | `api/dismiss/` | Suppresses the dashboard nudge for this month. |
| `monthly_review:export` | `export/` | CSV of the breakdown, following `apps/reports/exports.py`. |

Defaults: no `?month=` → **last complete month** (not the current one — a half-finished
month has nothing to review). Reviewing the current month is allowed via the picker and
raises an `is_current_month` banner.

Guard: a month before the team's first journal activity returns the page with an empty
state, not a 404.

### 5.4 Frontend

New Vite entry in `vite.config.ts` (`build.rollupOptions.input`):

```js
'monthly-review-app': path.resolve(__dirname, './assets/javascript/monthly_review/monthly-review-app.jsx'),
```

```
assets/javascript/monthly_review/
  monthly-review-app.jsx    entry: JSON.parse(#monthly-review-props), inject api.js
  api.js                    post() wrapper w/ X-CSRFToken, matching onboarding/api.js
  ReviewApp.jsx             owns { mode: 'walkthrough' | 'dashboard', step, baseline }
  BaselineBar.jsx           the comparison toggle — rendered on steps 2-8 and the dashboard
  Dashboard.jsx             §4.10
  steps/
    StepHealth.jsx  StepGlance.jsx  StepIncome.jsx  StepOverspent.jsx
    StepBiggest.jsx StepBreakdown.jsx StepSaving.jsx StepNetWorth.jsx StepRecap.jsx
  parts/
    StatCard.jsx  DeltaChip.jsx  FlagCard.jsx  DrillTable.jsx  InsightList.jsx
  charts/
    streams-chart.js  flow-chart.js  networth-stack-chart.js
```

- Every section under `parts/` and `steps/` takes the **already-sliced** baseline data, so
  no component recomputes anything.
- Charts import from `../reports/chart-theme.js` and register `observeTheme()`.
- Copy the onboarding transition classes wholesale: new `.review-*` rules alongside the
  `.onboarding-*` ones in `assets/styles/app/tailwind/app-components.css`, **including the
  `@media (prefers-reduced-motion: reduce)` block.**
- Walkthrough chrome is an in-page mode, **not** a takeover — the review page extends
  `web/app/app_base.html` and keeps the sidebar. (Onboarding suppressed nav because a
  first-run user has nowhere to go; a returning user must be able to leave mid-review.)
- `data-testid` on every interactive element and every table, per house style.

### 5.5 Navigation and entry points

1. `templates/reports/reports_home.html` — a seventh row, **first in the list**, with a
   "Reviewed" / "Not yet reviewed" badge for last month.
2. `templates/web/components/app_nav_menu_items.html` — a `side-link-sub` under Reports
   (mirroring how Goals nests under Budget). **Do not add a mobile-dock slot** — the dock
   is full at six.
3. `templates/web/app_home.html` — a nudge card, on the pattern of the existing
   `show_resume` card, shown when last month has no `MonthlyReviewState` with
   `completed_at` or `dismissed_at`, and the team has activity in it. Wired by a small
   vanilla entry, same shape as `onboarding-resume`.
4. `apps/bank_feed/` — once an account's uncategorized count hits zero, the feed shows a
   "Review this month →" link. (Nice-to-have; defer if step 7 runs long.)
5. `active_tab = "reports"` in the view context.

### 5.6 Settings

```python
MONTHLY_REVIEW_ENABLED = True      # settings.py, beside ONBOARDING_ENABLED
```

Tunables live next to the logic and are read with `getattr(settings, ...)`, per
`transfer_detection.get_window_days()`: `MONTHLY_REVIEW_STALE_DAYS` (14),
`MONTHLY_REVIEW_BASELINE_MONTHS` (`(1, 3, 6, 12)`), `MONTHLY_REVIEW_DRILL_LIMIT` (200).

---

## 6. The insight engine

`apps/monthly_review/services/insights.py` — pure, deterministic, no DB access (it reads
the assembled review dict), fully unit-testable.

```python
@dataclass(frozen=True)
class Insight:
    kind: str          # "no_transactions" | "overspent" | "income_down" | ...
    severity: str      # "good" | "info" | "warn" | "bad"
    step: int          # which step surfaces it
    title: str         # one line, already interpolated
    body: str = ""     # one or two sentences
    url: str = ""      # where to act on it
    metric: Decimal | None = None
    delta: Decimal | None = None
```

Rules, by step:

| Step | Rule | Severity |
|---|---|---|
| 1 | Feed account with no transactions this month | bad |
| 1 | Account stale > `STALE_DAYS` before month end | warn |
| 1 | Uncategorized transactions remain | warn |
| 1 | Unreconciled transactions remain / balance gap | warn |
| 1 | All clear | good |
| 2 | Net positive / negative, and by how much vs baseline | good / bad |
| 3 | Income down > 10% vs baseline | warn |
| 3 | A baseline stream is **absent** this month (missing paycheque) | bad |
| 3 | A new stream appeared | info |
| 4 | Each overspent category | bad |
| 4 | Each over-assigned-but-covered category | warn |
| 4 | Nothing overspent | good |
| 5 | Top 10 account for > 50% of spend | info |
| 6 | Biggest mover vs baseline, up and down | info |
| 6 | A category with spend and **no budget** | warn |
| 7 | Savings rate up / down vs baseline | good / warn |
| 7 | Nothing saved this month | warn |
| 8 | Net worth up / down on the month, and over the window | good / bad |

**Copy rules** — the reference's voice is the target, and it is worth matching:
- Plain sentences, no jargon, no exclamation marks. "Groceries ended August $212 in the
  red" beats "⚠️ Budget variance detected!"
- Always name the comparison: *"…$680 more than your 3-month average of $3,530."*
- Every warning names the next action and links to it.
- All strings through `gettext` / `{% translate %}`.
- Thresholds (10%, 50%, 14 days) are module constants, not literals inline.

---

## 7. Implementation order

Each step is independently shippable and testable.

1. **`apps/monthly_review/` skeleton** — app, model + migrations, settings registration,
   URL mount, empty page view rendering "Nothing yet". Backend tests for the model.
2. **`services/baselines.py`** — the comparison-window machinery, driven by the 13-month
   matrix from `get_income_statement_data(period="month")`. Unit tests first, covering:
   clamping, zero-history, a 1-month baseline, and the "baseline excludes the current
   month" invariant. **This is the highest-risk piece — build it first and test it hard.**
3. **`services/health.py`** — step 1's data, on `_annotate_feed_account_activity`'s
   three-query pattern. Tests for each flag.
4. **`services/budget.py`** — move `build_section()` out of `apps/reports/views.py`, have
   `budget_vs_actual` use the moved version, add the overspent / over-assigned split.
   Existing report tests must still pass untouched.
5. **`services/review.py`** — assemble the full payload. A test that asserts the payload's
   top-level keys, so the frontend contract is locked before any JSX is written.
6. **`services/insights.py`** — the rules. Table-driven tests: a hand-built review dict in,
   an expected insight list out.
7. **Frontend: the dashboard** (`Dashboard.jsx` + `BaselineBar` + charts + drill-down).
   Ship this first — it is the durable artifact and it proves the payload.
8. **Frontend: the walkthrough** — the nine steps over the same components, with the step
   chrome, transitions and confetti.
9. **Entry points** — reports home row, nav sub-link, dashboard nudge card, CSV export.
10. **Instrumentation** — 5 new `AuditEvent` types (§8) and a migration.
11. **E2E suite** (§9).

---

## 8. Instrumentation

New `AuditEvent` constants **and** matching `EVENT_TYPE_CHOICES` entries (both lists —
they are parallel) in `apps/audit/models.py`, plus a migration for the `choices` change:

| Constant | Metadata |
|---|---|
| `MONTHLY_REVIEW_STARTED` | `{month}` |
| `MONTHLY_REVIEW_STEP_COMPLETED` | `{month, step, next}` — records the step being **left**, which is what turns a completion rate into "which step loses people" |
| `MONTHLY_REVIEW_COMPLETED` | `{month, steps_seen, flags}` |
| `MONTHLY_REVIEW_DISMISSED` | `{month, step}` |
| `MONTHLY_REVIEW_BASELINE_CHANGED` | `{month, from, to}` — tells us which default is right |

Emit via `log_event(AuditEvent.X, request=request, metadata={...})`.

---

## 9. Testing

**Backend** (`apps/monthly_review/tests/`), Django `TestCase` with `setUpTestData`,
following `apps/reports/tests.py` for the accounts/journal fixture and
`apps/onboarding/tests/test_views.py` for the team/user/`post_json` fixture. Minimum:

- `test_baselines.py` — clamping at ledger start; a team with one month of history; a team
  with none; 1m ≠ average; **the current month never appears in its own baseline**.
- `test_health.py` — one test per flag, plus the all-clear case.
- `test_budget.py` — overspent vs over-assigned split with a real carried-over balance;
  unbudgeted-category-with-spend.
- `test_review.py` — payload keys present; voided entries excluded everywhere; a month
  before first activity returns the empty state.
- `test_insights.py` — table-driven, one case per rule.
- `test_views.py` — happy path, month defaulting, `?month=` parsing, **a permission test**
  (a non-member gets a 404, per `login_and_team_required`), and each POST endpoint.

**E2E** (`e2e/tests/test_monthly_review.py`, POM in `e2e/pages/monthly_review.py`):
uses `authenticated_page`, `team`, `requires_vite`; seeds via `e2e/factories.py`
(`feed_transaction`). Cover: the page loads with real figures; walking all nine steps; the
baseline toggle changes a visible figure; a drill-down row unfolds; the health step flags a
zero-transaction account; skip-to-dashboard; completing marks the month reviewed and the
dashboard nudge disappears.

> E2E caution from the onboarding suite: the shared `team` fixture must remain usable. If
> the dashboard nudge or a review overlay changes what `/a/{slug}/` renders, existing
> tests that assert on the dashboard will break — check `e2e/tests/` before wiring §5.5.3.

**Manual verification** (`.claude/skills/verify`): run the app, create a team with ≥4
months of varied data, and walk every step at a 390px viewport as well as desktop.
Confirm: figures tie to the income statement and balance sheet for the same month; the
drill-down rows sum exactly to their category's "spent"; charts recolour on a theme flip;
`prefers-reduced-motion` kills the transitions.

---

## 10. Open decisions for the builder

1. **"Saved" = goal allocations.** This is the assumption in §3. It is the only savings
   concept Koala has, but it is budget-side — it will not tie to any bank balance. The
   alternative (net increase in non-chequing asset accounts) ties to cash but requires the
   user to have classified their accounts in a way the app does not currently ask for.
   **Recommendation: ship goal allocations, say so plainly in `notes`, revisit.**
2. **Default baseline.** `3m` is proposed — long enough to smooth a lumpy month, short
   enough to reflect a recent change. `MONTHLY_REVIEW_BASELINE_CHANGED` events will tell
   us within a month whether users reach for something else.
3. **Payee-vs-account for income streams.** §3 proposes payee-with-account-fallback, to
   match the reference. If real data shows most income entries carry no payee, switch to
   account-only and drop the fallback.
4. **The bank-feed entry point** (§5.5.4) is the one genuinely optional item here. Cut it
   first if the build runs long.

---

## Explicitly out of scope

- Any mortgage, housing, property-equity, amortization, payoff-projection or buyout metric.
  The reference document's step 6 and its entire House tab are **not** being ported.
- LLM-generated narrative. Insights are deterministic Python.
- Emailed or scheduled monthly reviews.
- Multi-month or year-in-review comparison. One month at a time.
- Storing computed figures. The review always recomputes from the ledger.
