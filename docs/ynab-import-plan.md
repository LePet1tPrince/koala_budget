# YNAB Import — Implementation Plan

> **Status: implemented** (`apps/ynab_import`). Every decision below was built as
> written, with the deviations listed in §7. The figures in this document are
> re-derivable by `docs/reference/checks/verify_ynab_assumptions.py` and are
> restated as tests in `apps/ynab_import/tests/`.

Goal: a new member drops their two YNAB export CSVs into an empty team and gets a
populated chart of accounts, the full transaction history, per-month budgets,
opening balances and goals — no manual categorisation.

Every number in this document was measured against the sample export in
`docs/reference/` (`My Budget as of 2026-09-14 10-50 - {Register,Plan}.csv`),
not assumed.

---

## 1. What a YNAB export actually contains

Two CSVs, both UTF-8 with a BOM on the header row, amounts written with a
**trailing** currency symbol (`134.32$`, `-0.00$`), dates as `DD-MM-YYYY`.

**Register** — 7,572 rows, Dec 2021 → Sep 2026.
`Account, Flag, Date, Payee, Category Group/Category, Category Group, Category, Memo, Outflow, Inflow, Cleared`

**Plan** — 2,958 rows = 58 months × 51 categories.
`Month ("Dec 2021"), Category Group/Category, Category Group, Category, Assigned, Activity, Available`

Sample shape:

| | count |
|---|---|
| accounts | 36 |
| distinct payees | 1,123 |
| plan categories | 51 (6 Credit Card Payments, 9 hidden) |
| months of plan data | 58 |
| plan cells with non-zero `Assigned` (excl. CC Payments) | 1,468 |
| transfer legs | 1,678 → **839 pairs, 0 unmatched** |
| split legs | 172 → 83 parent transactions |
| `Starting Balance` rows | 21 |
| plain rows | 5,704 |
| **journal entries** | **6,644** (~13,300 lines) — every one of the 7,572 rows accounted for |

### What the export does *not* contain

This is the whole difficulty. Absent from both files:

- **account type** (asset vs liability) and **on-budget vs tracking**
- **currency**
- **income categorisation** — every inflow is `Inflow: Ready to Assign`
- **split parent amounts** (only the legs)
- **YNAB targets/goals**, account closure state, payee metadata
- any **`Ready to Assign` balance** — the Plan has no RTA row at all

Everything in §3 is about recovering those from what *is* there.

---

## 2. Reconciliation: the import's integrity gate

> Every measured claim below and in §3 is re-derivable by running
> `python docs/reference/checks/verify_ynab_assumptions.py`, which exits
> non-zero if any of them stops holding. Point it at a different export to see
> which rules survive contact with someone else's budget.

Deriving activity per `(month, category)` from the Register and comparing it to
the Plan's `Activity` column:

**2,788 of 3,016 cells match to the cent.** All 228 mismatches fall into exactly
three explainable buckets:

| bucket | cells | cause |
|---|---|---|
| `Credit Card Payments` | 167 | Plan-only. These categories never appear in the Register — YNAB moves money into them internally (§3, D3). |
| `Inflow: Ready to Assign` | 58 | Register-only. YNAB never budgets RTA. |
| Sep 2026 (3 cells) | 3 | The export's own partial month. |

The three Sep 2026 cells are accounted for to the cent by scheduled/uncleared
rows the Plan snapshot excludes but the Register carries (`FreshCo -344.98`,
`CanadaHelps -50.00`, two future-dated pension transfers `-628.67`).

**Therefore:** after importing, assert register-derived activity equals the
Plan's `Activity` for every category in every **fully elapsed** month, and
report the export month separately as informational. That assertion is a real,
achievable post-import check — not a soft heuristic — and it should gate the
"your data is in" screen.

With D2's decision applied the gate extends to the whole Plan: `Activity`
reconciles as above, `Assigned` is imported verbatim plus a top-up that is
itself derived from `Available`, and KB's own `Available` then matches YNAB's on
**all 2,610 category-months**. So all three Plan columns are checkable, not just
one.

---

## 3. Methodological differences

Ranked by how much of the design they move.

### D1 — Envelope budgeting vs forecast/actual · **decided**

YNAB is envelope: income lands in **Ready to Assign**, the user hands it out to
categories, and `Assigned` is *money allocated*. Koala Budget's `Budget` is a
*plan*: `budget_amount` per income/expense category, with
`BudgetService.available()` computing `Budget − Actual + Available(prev)` for
expenses and `Actual − Budget + Available(prev)` for income. There is no RTA
pool.

Expense `Assigned` maps onto `budget_amount` directly (1,468 rows in the
sample — see D2 for the one adjustment). Income is the gap: YNAB never assigns
to income categories, so there is nothing in the export to import.

**Decision: back-fill each income budget from its own actual.** For every
(income account, month) with activity, write `budget_amount = actual income for
that month`. KB's income formula is `Actual − Budget + Available(prev)`, so
`Budget == Actual` makes every month contribute zero and income `Available`
stays 0 throughout — including the current period, which is the point: the user
starts with no phantom budgeted income.

Left at 0 instead, income `Available` would accumulate every dollar ever
earned — $699,774 across the sample — and read as an enormous surplus.

Two implementation consequences:
- The back-fill must run **after** the D4 payee → income-account mapping, since
  "actual per income account" is only defined once the mapping exists.
- It is computed from the imported rows, not from a post-import query, so it
  stays inside the single atomic apply.

No RTA-equivalent figure is being added to KB. Worth revisiting separately: a
migrated user will look for "Ready to Assign" and no number in KB answers it.

### D2 — Negative `Available` rollover · **decided**

Measured on the sample: in **186 of 186** cases where a category's previous-month
`Available` was negative, YNAB **reset it to 0** and did not carry the negative
forward. Zero cases carried forward, across every category group.
`BudgetService.available()` always carries the negative forward, uncapped.

**Decision: keep KB's rollover exactly as it is.** Negatives carry forward;
`BudgetService` is not touched and no team setting is added.

That decision is kept, but importing YNAB's `Assigned` column verbatim under it
would have been a serious problem, so the importer does one thing differently.
Measured: replaying 58 months of history through KB's rule with the raw
`Assigned` column diverges from YNAB on **1,259 of 2,610 category-months
(48.2%)**, and lands **31 of 45 categories** on a wrong *current* `Available` —
not stale history, but the number the user budgets against:

| category | YNAB Available (Sep 2026) | KB, raw `Assigned` |
|---|---|---|
| `Monthly: Groceries` | $739.34 | **−$1,988.14** |
| `Monthly: Amroth House` | $3,759.81 | **−$11,442.53** |
| `Savings: House` | $1,503.00 | **−$15,568.84** |
| `Tax Deductible: Medical` | $0.00 | **−$2,401.82** |

A migrated user would open the budget page to find most categories deeply in the
red. That is not a divergence to explain away; it makes the imported budget
unusable.

The cause is that KB would accumulate *every historical overspend forever*,
while YNAB absorbed each one into Ready to Assign at the time. Which points at
the fix, and it is not a fudge: **that money really was assigned.** When YNAB
reset a negative to 0 it covered the overspend out of RTA — the `Assigned`
column simply does not show it. So the faithful import of what YNAB did is:

```
budget_amount(cat, m) = Assigned(cat, m) + max(0, −Available(cat, m−1))
```

With KB's unchanged carry-forward rule this reproduces YNAB's `Available`
**exactly — 0 mismatches across all 2,610 category-months**, because
`x + max(0, −x) = max(x, 0)` is precisely the reset YNAB performs.

In the sample the top-up fires in 143 months and totals $68,418.75. The only
visible cost: in those months the budget grid shows a `budget_amount` above
YNAB's `Assigned` figure — which is the accurate number, being the money that
actually went into the category. The import summary should say so.

Note this is orthogonal to §2: the reconciliation gate is on `Activity`, which
the top-up does not touch. `Assigned`, `Activity` and `Available` all reconcile.

### D3 — Credit Card Payment categories

6 categories in a `Credit Card Payments` group, present **only** in the Plan,
never once in the Register. Pure YNAB machinery: spending on a card moves budget
into the card's payment envelope.

KB models a credit card as a liability account and card spending as expense
against that liability. There is no payment envelope and nothing to map.

**Discard them as categories — but mine them first.** Their names are exactly the
user's credit-card account names, which makes the Plan a free, exact
credit-card-account list. On the sample this identified all 6 liabilities with no
false positives, and it is the strongest type signal in the export (see D7).

### D4 — Income has no categories · **decided**

All 1,133 inflow rows carry the single category `Inflow: Ready to Assign`. KB
needs income *accounts* (4000s) for the income statement, the budget page's
Income section and every report.

The 43 distinct payees on those rows are meaningful: `BBC Income` (351),
`Interest` (183), `World Vision` (140), `CHURCH OF THE R PAY` (81),
`Timmy's Pension` (80), `Credit Card Rewards Redemption` (78), `CCB`, `Viv EI`,
`Starting Balance`…

Options:
- **(a)** One `Income` account. Everything lands there; the income statement has
  a single row forever.
- **(b)** Derive an income account per payee above a threshold, rest to
  `Other Income`. Zero-touch, guesses wrong sometimes (`Starting Balance` and
  `reconcile` are not income sources).
- **(c)** Wizard step: show the 43 payees with counts and totals, pre-grouped by
  (b), let the user merge/rename/drop before applying.

**Decision: (c)** — a mapping screen, pre-filled by the heuristic. It is one
screen, it is the highest-leverage screen in the flow, and the existing "Map
Categories" step of the CSV wizard is the same shape, so
`Step4MapCategories` / `suggest_account_for_category` can be followed closely.

The screen must also let a payee be marked **not income** — `Starting Balance`
(14 rows), `reconcile` and `Reconciliation Balance Adjustment` are bookkeeping,
not earnings, and routing them to an income account would overstate income on
every report. `Starting Balance` rows are already claimed by the opening-balance
pass (§1), so the mapping screen should exclude them rather than ask.

### D5 — On-budget vs tracking accounts

Not in the export. Recoverable signal, exact on the sample:

> An account is **on-budget** if its `Starting Balance` row carries a category,
> or if any of its rows carries a category. Otherwise it is **tracking**.

That splits the sample 22 on-budget / 14 tracking, with the `Starting Balance`
signal and the any-categorised-row signal agreeing on every account that has
both, and every tracking account it finds is genuinely one (TFSAs, FHSAs, GICs, pensions, RESP, home equity).

KB has no on/off-budget concept: every account is in one chart of accounts and
every transaction needs both legs. The consequence is D6 and the 122
uncategorized non-transfer rows (TFSA interest/growth, mortgage principal
credited to `Amroth Equity`), which have no counter-account in the export.

Proposal: import tracking accounts as ordinary asset accounts, and post their
uncategorized activity against a new non-system income/expense pair
(`Investment Income` / `Investment Loss`) rather than the system
`Reconciliation Adjustments` — these are real economic events, not bookkeeping
plugs, and burying them in equity would understate income.

### D6 — Transfers that carry a category · **decided**

315 transfer legs carry a category; 306 of those are in the `Savings` group
(`House` 189, `Retirement` 120, `RESP` 17, `Emergency Fund`, `Savings Expenses`).
This is YNAB's idiom for "move $500 to the TFSA *and* record it as budgeted".

In double-entry that movement is asset → asset. Posting it to an expense account
as well would break net worth.

Options:
- **(a)** Import as a plain transfer, drop the category. Net worth correct,
  budget history loses the savings assignment (and 306 rows of the user's
  `Savings` budget then reconcile to nothing).
- **(b)** Import as a transfer **and** create a KB `Goal` per `Savings`
  category with a `GoalAllocation` for the month. The categories *are* goals —
  `Emergency Fund`, `House`, `RESP`, `Retirement` map one-to-one onto what
  `budget.Goal` exists for.
- **(c)** Post to an expense account. Net worth wrong. Rejected.

**Decision: (b)** — map YNAB's `Savings` categories onto KB `Goal`s, with one
carve-out: `Investment Gain/Loss` (57 rows) is not a goal but a valuation
change, so it goes to the D5 income/expense pair. The wizard confirms the
mapping (step 4 in §4) rather than assuming it, since `Savings Expenses` is a
spending category wearing a savings label and belongs with the expenses.

`Goal.target_amount` is non-nullable and the export carries **no YNAB targets**.
**Decision: set `target_amount` to the amount already saved** — no extra wizard
screen.

One consequence to build for, because it is functional rather than cosmetic.
`apps/budget/views.py:717` computes a goal's `funded` state as
`is_complete or (target_amount > 0 and saved >= target_amount)`, so every
imported goal arrives funded: the ✓ Funded / Treetop / WINNER badge shows, the
goal counts toward "on pace or funded", **and the quick-assign button is
disabled** — `goal_assign_available` 400s on a funded goal. A migrated user
cannot put money into `House` or `Retirement` until they raise the target.

So the importer must:
- leave `is_complete = False`, so the goals stay in `Goal.objects.active()` and
  remain editable rather than being treated as finished;
- say plainly in the import summary that targets were set to the amount already
  saved and need raising for any goal still being saved for, linking to the
  goals page.

That keeps the no-extra-screen decision while making the one blocked action
discoverable instead of a dead button.

Note `GoalAllocation` is `unique_together ["team", "goal", "month"]`, so
multiple transfers in a month sum into one allocation row. And `Goal.save()`
auto-creates a backing equity account, so goal names must not collide with
imported account names (`RESP` is both an account and a category in the sample —
different types, so the `AccountForm` per-type uniqueness rule is satisfied, but
the importer must not rely on that holding for every export).

### D7 — Account type inference

Rule, in order: liability if the account name appears in `Credit Card Payments`
(D3), **or** its running balance is never positive, **or** its `Starting Balance`
is negative. Otherwise asset.

On the sample: 6 liabilities, 30 assets, correct throughout. 12 accounts cross
zero (overdrawn chequing) and are correctly kept as assets by the ordering of the
rules.

Known weak spot: a mortgage or car loan tracked in YNAB is a liability whose
balance is never positive → caught. But a *home equity* tracking account is a
positive asset (`Amroth Equity`, +194,190.58) → also caught, correctly, as an
asset. The failure mode is a liability that was paid down past zero at some
point. **Needs a review screen** listing each account with its inferred type,
group and opening balance before anything is written — which is also where the
user fixes institution names and drops accounts they don't want.

### D8 — Splits

83 parent transactions, 172 legs, memos prefixed `Split (i/n)`. KB handles these
natively as a multi-line `JournalEntry`, so the mapping is good — the grouping is
the fiddly part:

- 3 of the 80 `(account, date)` buckets contain **two different splits** — which
  is why the correct walk yields 83 groups, not 80. Grouping by account+date
  alone both undercounts and merges unrelated legs.
- 1 bucket is **not contiguous** in file order (an unrelated row sits between two
  splits on `BBC Chequing 2024-04-30`).
- A split leg can itself be a **transfer** (`Viv's Paycheck (TD) 2026-05-28`:
  leg 1 an expense, leg 2 `Transfer : Cash`) — and that leg is also one half of a
  transfer pair, so naive handling double-counts the movement. Measured: **3 of
  the 839 transfer pairs have exactly one leg inside a split**, and none has
  both. Those 3 pairs must **merge into** the split's entry rather than becoming
  entries of their own — which is where the 6,644 total comes from
  (83 splits + 836 standalone transfer pairs + 21 opening + 5,704 plain).

Algorithm: scan in file order; on `(1/n)` open a group; consume the next
expected `(k/n)` within the same `(account, date)`, skipping unrelated rows;
close at `(n/n)`. Then resolve transfer legs *within* a split against the pairing
pass, not independently.

### D9 — Reconciliation state

`Cleared` column: 7,368 `Reconciled`, 98 `Cleared`, 106 `Uncleared`.

KB flags `is_reconciled`/`is_cleared` **per `JournalLine`**; YNAB flags per
transaction. Set the flag on the **bank-account leg only**, following the
transfer-mirror precedent already in the codebase ("the two legs reconcile
independently, per-`JournalLine` `is_reconciled`").

### D10 — Closed accounts and hidden categories · **decided**

13 of 36 accounts end at exactly `0.00` — emptied and abandoned rather than
closed (YNAB doesn't export closure state). 9 categories sit in
`Hidden Categories`.

**Decision: import everything, all visible.** No `Account.is_archived` field and
no migration — `Account` has no such field today (`JournalLine` does), and this
import is not the reason to add one.

History and the §2 gate stay complete. The cost is clutter: the accounts board
and every category picker carry ~22 entries the user has finished with. Two
things make that cheaper without a model change:
- Put the hidden categories in their own account group (`Hidden`, or the
  export's own group name) with a high `sort_order`, so the board's Type → Group
  → Account ordering parks them at the bottom of their section rather than
  interleaving them with live categories.
- The categorize-mode search already ranks by `matchScore()`, so a dead category
  only surfaces when its name is actually typed.

If the clutter turns out to matter, `Account.is_archived` is a later, separate
change — and one that pays off beyond the importer.

### D11 — Free ordering

Checked: all 58 months in the Plan list groups and categories in **one identical
order** (`Credit Card Payments, Monthly, Cumulative, Tax Deductible, Savings,
Hidden Categories`). That is the user's own arrangement, and it maps directly
onto `AccountGroup.sort_order` / `Account.sort_order`, so the imported chart of
accounts arrives in the order they already know — through the board, reports,
budget page and grid.

Account numbers follow the project convention (1000s/2000s/3000s/4000s/5000s)
assigned in Plan order within each block.

### D12 — Staging vs direct posting · **decided**

Does the register land in `BankTransaction` (the feed, awaiting categorisation)
or straight into the journal?

**Decision: straight to the journal.** 6,644 `JournalEntry` rows,
`source=SOURCE_IMPORT`, `status=STATUS_POSTED`, and **no** `BankTransaction`
rows. The register is already categorised; creating feed rows would present
7,572 already-answered questions.

This also settles the 122 uncategorized tracking rows (§D5): they post to the
`Investment Income` / `Investment Loss` pair rather than landing in the feed, so
the user's first sight of the app is a populated dashboard and not a to-do list.

Corollary to flag: the team's bank feed then starts empty, and the first
Plaid/CSV sync will re-import anything overlapping the register's end date. The
importer should record its cut-off date per account so that sync can warn.

### D13 — Currency

No currency field in either file; amounts are bare `$`. Assume the team's
currency and say so in the import summary. A YNAB budget in another currency
will import with the right numbers and the wrong symbol.

---

## 4. Implementation

New Django app `apps/ynab_import`, mirroring how `apps/onboarding` is built
(pure functions for anything that both previews and applies, rules as data).

### Phase 1 — Parsing and inference (pure, no DB)

`apps/ynab_import/services/parse.py`
- `parse_register(file) -> list[RegisterRow]`, `parse_plan(file) -> list[PlanRow]`
- Reuse `csv_upload.detect_encoding` and `csv_upload.parse_amount` as-is: its
  `re.sub(r"[$€£¥₹\s]", "", value)` strips the symbol wherever it sits, so
  YNAB's trailing form parses correctly (verified: `134.32$` → `134.32`,
  `-130.18$` → `-130.18`, `157,118.75$` → `157118.75`). BOM via `utf-8-sig`.
- `identify(files)` — which upload is the Register and which the Plan, from
  headers, so the user drops two files without labelling them.

`apps/ynab_import/services/analyse.py` — pure, returns a `Migration` dataclass
- transfer pairing (§D8 + D6), split grouping (§D8), `Starting Balance`
  extraction, account type + on/off-budget inference (§D5, D7), income payee
  clustering (§D4), category → group mapping with `sort_order` (§D11)
- Deliberately pure so the review screens preview exactly what gets applied —
  the same discipline as `onboarding.services.builder.build_template`.

Tests: the sample export is the fixture, and
`docs/reference/checks/verify_ynab_assumptions.py` already re-derives every
figure this plan asserts (8/8 passing) — port its checks as the Phase 1 test
body rather than restating them. Assert 839 transfer pairs / 0 unmatched, 83
split groups, 6 liabilities, 22 on-budget accounts, 6,644 entries.

### Phase 2 — Apply

`apps/ynab_import/services/apply.py`, one `transaction.atomic` block:
1. `AccountGroup` / `Account` / `Institution` / `Payee` (1,123 payees →
   `bulk_create(ignore_conflicts=True)`)
2. `Budget` rows **first**, including the D2 top-up and the D1 income
   back-fill — because `JournalLine` carries a `budget` FK that must point at
   them (see "Bulk insert" below)
3. `JournalEntry` + `JournalLine` in batches, with the balance assertion run
   per entry in Python before insert (`full_clean` on 6,641 entries is its own
   query storm)
4. `Goal` / `GoalAllocation` (§D6)
5. Opening balances from the `Starting Balance` rows (§1). Reuse
   `onboarding.services.opening.create_opening_balances`, but note its signature
   is `(team, rows, as_of)` — **one** date for the whole batch, while the sample
   export carries **13 distinct dates across its 21 rows** (each account opened
   when the user added it, from 2021-12-01 to 2026-04-30). Group the rows by date
   and call it once per group; posting them all on one date would put the money
   in the wrong months and break §2.
6. `AuditEvent` (new type `YNAB_IMPORT`, audit migration) recording counts,
   date range and every inference the user accepted
7. Run the §2 reconciliation and store the result

Idempotency: a second run on a non-empty team must refuse, not merge. Guard on
"team has any non-void `JournalEntry`" and offer a wipe-and-retry instead.

Given the volume (6,644 entries, ~13,300 lines), run it as a **Celery task**
with progress, not in the request.

#### Bulk insert · **decided**

`JournalLine.save()` calls `_calculate_budget()` — one `Budget` query per line —
and `post_save` then writes an `AuditLog` row via `apps/audit/signals.py`. At
~13,300 lines the naive path is roughly **26,600 extra queries** (a SELECT and
an INSERT each), which is the difference between a 20-second import and a
10-minute one.

`bulk_create` already bypasses `save()` and its signals entirely, so the work is
not to add a bulk path but to make the existing one correct:

- **Resolve `budget_id` in memory.** Build `{(category_id, month): budget_id}`
  from the `Budget` rows created in step 2 and assign `line.budget_id` before
  `bulk_create`. Skipping this leaves every imported line's `budget` NULL, which
  silently breaks nothing visible today but is wrong and would be hard to trace
  later.
- **Add `JournalLine.objects.bulk_create_for_import(lines, budget_map)`** on the
  queryset rather than open-coding it in the importer, so the budget resolution
  lives next to the `save()` override it is standing in for. A comment on
  `save()` pointing at it stops the two drifting.
- Batch with `batch_size` and keep it inside the atomic block.

**Consequence to accept deliberately:** `bulk_create` skips the audit signals, so
an import writes **no row-level `AuditLog` entries**. That is the right outcome —
13,300 field-diff rows for a single import is noise, and the `AuditEvent` from
step 6 is the meaningful record — but it is a real behaviour difference from
every other write path in the app, and it needs a comment where it happens and
a line in `docs/testing-guide.md`.

### Phase 3 — Wizard

Vite entry `ynab-import-app`, reusing `common/Modal`, `Combobox`, `Toast` and the
`Step*` shape of the CSV wizard:

1. **Drop** both CSVs (auto-identified)
2. **Accounts** — review inferred type / group / opening balance, rename, drop (§D7)
3. **Income** — map the 43 inflow payees to income accounts (§D4)
4. **Savings → Goals** — confirm which `Savings` categories become goals, and
   set a target for each (§D6)
5. **Preview** — counts, date range, net worth, and what will be skipped
6. **Apply** — progress, then the reconciliation result (all three Plan columns,
   §2), plus a note naming the D2 top-up months and the D1 income back-fill so
   neither looks like a number the importer invented

Entry points — **decided: both.**
- A "Coming from YNAB?" branch on the onboarding takeover's welcome screen. It
  is the right moment, and it **skips the questionnaire entirely**: the export
  answers every question in `QUESTION_CATALOG` better than the user can, so
  `build_template()` is never called and `OnboardingState` goes straight to the
  `tasks` phase via `complete()`.
- A standalone page for a team already past onboarding but still empty, so a
  user who clicked through first and only then found their export is not forced
  into a new team.

Both call the same Phase 2 apply; only the chrome differs.

### Phase 4 — Tests

- Unit: parsing, pairing, splits, inference — sample export as fixture
- Integration: apply to a fresh team, then assert **§2's reconciliation passes
  for all 57 elapsed months** — on `Activity`, on `Assigned`, and on
  `BudgetService.available()` against YNAB's `Available` (the D2 claim, which is
  exact and so belongs in a test, not a comment) — that income `Available` is 0
  in every month (D1), that net worth equals the sum of inferred closing
  balances, and that every `JournalEntry` balances
- A regression test pinning `bulk_create_for_import` to populate `budget_id`,
  since a NULL there is invisible until something reads it
- E2E (`e2e/tests/test_ynab_import.py` + `e2e/pages/ynab_import.py`): drop both
  files, walk the wizard, land on a dashboard with a non-zero net worth
- Note the `team` fixture is marked past onboarding, so a YNAB-import test needs
  the `unonboarded_team` fixture

---

## 5. Decisions — all settled

| | question | resolution |
|---|---|---|
| **D1** | Envelope vs forecast/actual | Import expense `Assigned`; back-fill income budgets to equal actuals so income `Available` is 0 and the current period starts with no phantom budgeted income. No RTA figure added. |
| **D2** | YNAB resets negative `Available`; KB carries it forward | Keep KB's rollover unchanged — negatives carry forward, no setting, `BudgetService` untouched. Importer writes `Assigned + max(0, −PrevAvailable)`, recording the money YNAB actually assigned to cover each overspend, which reproduces YNAB's `Available` exactly (0/2,610 mismatches). |
| **D3** | Credit Card Payment categories | Discard as categories; use their names as the credit-card account list. |
| **D4** | Income has no categories | Wizard screen mapping the 43 inflow payees to income accounts, pre-filled by heuristic, with a "not income" option for bookkeeping payees. |
| **D5** | On-budget vs tracking | Import tracking accounts as ordinary assets; their 122 uncategorized rows post to a new `Investment Income` / `Investment Loss` pair. |
| **D6** | Categorised transfers to tracking accounts | Map the `Savings` categories onto KB `Goal`s (`Investment Gain/Loss` carved out). `target_amount` = amount already saved, `is_complete` left False, and the import summary must flag that every imported goal arrives `funded` with its assign button disabled until the target is raised. |
| **D7** | Account type inference | CC-payment list, then never-positive balance, then negative starting balance; everything else an asset. Shown for review before anything is written. |
| **D8** | Splits | Walk `(i/n)` in file order within `(account, date)`; 83 groups. The 3 transfer pairs with one leg inside a split merge into that split's entry. |
| **D9** | Reconciliation state | Set `is_reconciled`/`is_cleared` on the bank-account leg only, per the transfer-mirror precedent. |
| **D10** | Zero-balance accounts and hidden categories | Import everything, all visible. No `Account.is_archived` field, no migration. Park hidden categories in their own high-`sort_order` group so the board's ordering keeps them out of the way. |
| **D11** | Ordering | Take group and category `sort_order` from the Plan's own ordering, which is identical across all 58 months. |
| **D12** | Staging vs direct posting | Straight to the journal: 6,644 posted entries, `source=SOURCE_IMPORT`, no `BankTransaction` rows. |
| **D13** | Currency | Assume the team's currency; state the assumption in the import summary. |
| **entry** | Where the import starts | Both — a "Coming from YNAB?" branch on the onboarding takeover (skipping the questionnaire entirely) and a standalone page for an existing empty team. |
| **perf** | `JournalLine.save()`'s per-line budget lookup | `bulk_create` already skips `save()`; add `bulk_create_for_import` resolving `budget_id` from an in-memory map. Accepts skipping row-level audit logs. |
| **re-run** | Importing over a team that already has data | Refuse, guarding on "team has any non-void `JournalEntry`"; offer wipe-and-retry. |

Nothing is blocking. Phase 1 can start.

## 6. Risks

- **`BudgetService.available()` is recursive per category per month.** 45
  categories × 58 months on the budget page and the grid, after import. Existing
  teams are small; a migrated team is not. Needs a look before Phase 3 ships —
  and D2 raises the stakes, since the top-up is only correct if `available()`
  keeps behaving exactly as it does today.
- **`JournalLine.save()`'s per-line budget lookup** (Phase 2 step 2) is the
  difference between a 20-second import and a 10-minute one.
- Inference is only as good as the export. Every inferred value is shown for
  review before anything is written — that is the mitigation, and it is why
  Phase 1 is pure.
- The sample is one budget from one country. Rules that are exact here
  (`Starting Balance` categorisation, the CC-payment account list) should be
  treated as strong signals with a review step, never as guarantees.

---

## 7. What was built, and where it differs

Everything in §4 exists: `apps/ynab_import/services/{parse,analyse,build,apply,reconcile,payload,session}.py`,
a `YnabImport` row holding the uploaded export, a Celery task with progress, a
six-screen wizard (`assets/javascript/ynab_import/`), and both entry points.
Measured on the sample: 6,623 transactions + 13 opening balances, 13,335 lines,
104 accounts, 1,872 budgets, 3 goals — written in about two seconds.

Seven places where building it taught us something the plan did not say.

**A `build` step between analysis and apply.** §4 had `analyse` returning a
`Migration` that `apply` wrote. In practice the user's answers have to be folded
in somewhere, and doing it inside `apply` would have put decisions back in the
step that is supposed to have none. `build(analysis, choices) -> ImportPlan` is
that fold: pure, and called by the preview screens *and* the apply, so the
"preview shows exactly what is applied" promise is structural rather than a
convention.

**The reconciliation compares the import, not the export.** §2 describes
comparing register-derived activity to the Plan's `Activity` — a check on the
export's internal consistency, which would pass even if the importer dropped
every row. `check_activity` instead sums the *planned journal lines* per category
per month, so it fails if a transaction is lost, posted to the wrong category, or
posted on the wrong side. Money that YNAB counted against a category while moving
it between the user's own accounts is subtracted (it cannot post to a category
without misstating net worth) and reported as a count, so the deviation is
measured rather than hidden. Two further checks were added: `Available` replayed
under KB's rollover against YNAB's column, and each account's closing balance.

**`Starting Balance` rows of zero write no entry.** 8 of the sample's 21 are for
accounts that were added empty. An entry with nothing on either side is not a
journal entry, so those rows are accounted for and skipped — which is why the
books hold 6,636 entries rather than 6,644.

**A savings category that was spent down does not become a goal.** `House` nets
−$20,464 across its categorised transfers: saved for, then spent on a house. D6
as written would have created a goal reading "$20,464 still to save" and put that
on the dashboard. Those categories are counted and named in the summary instead.

**Spending against a goal category needs somewhere to go.** 23 rows in the sample
spend directly against `House` rather than transferring into it. They post to an
expense account of the same name (the goal's backing account is `Goal: House`, so
there is no collision), with no budget of its own — the assignments became the
goal. The summary says so, and the wizard's Savings step is the escape hatch.

**Two fallback pairs, not one.** D5 routes an uncategorised row on a *tracking*
account to `Investment Income`/`Investment Loss`. On an everyday account an
uncategorised row is a category the user never picked, and calling that investment
activity would be a fiction, so those go to
`Uncategorized Income`/`Uncategorized Expense`. A row whose payee is YNAB's own
`Reconciliation Balance Adjustment` posts to the system equity account, which is
what that account is for.

**`create_opening_balances` gained a sign.** §4 step 5 noted the single-date
signature; the rows are grouped by date and it is called once per group, as
planned. It also now swaps sides on a negative amount — an overdrawn chequing
account or a card in credit. `parse_rows` still refuses a negative from a user,
so the endpoint's contract is unchanged.

Two risks in §6 played out as follows. `JournalLine.save()`'s per-line budget
lookup was the difference it was predicted to be, and
`bulk_create_for_import` resolves the link from an in-memory map instead.
`BudgetService.available()`'s recursion is still a month-at-a-time query chain:
it is correct after import (tested against YNAB's own figures) but a migrated
team is the first one large enough for its cost to matter, and it remains worth a
look.
