# YNAB Import — Implementation Plan

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
| split legs | 172 → 80 parent transactions |
| `Starting Balance` rows | 21 |
| plain rows | 5,701 |
| **estimated journal entries** | **~6,641** (~13,300 lines) |

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

---

## 3. Methodological differences and the decisions they force

Ranked by how much of the design they move.

### D1 — Envelope budgeting vs forecast/actual · **decision required**

YNAB is envelope: income lands in **Ready to Assign**, the user hands it out to
categories, and `Assigned` is *money allocated*. Koala Budget's `Budget` is a
*plan*: `budget_amount` per income/expense category, with
`BudgetService.available()` computing `Budget − Actual + Available(prev)` for
expenses and `Actual − Budget + Available(prev)` for income. There is no RTA
pool and no concept of unassigned money.

Consequences:
- YNAB `Assigned` maps cleanly onto `Budget.budget_amount` for **expense**
  categories. 1,468 rows in the sample.
- For **income** there is nothing to map: YNAB never assigns to income
  categories, so a migrated team has empty income budgets and every income
  category shows `Available = Actual`.
- A migrated user will look for "Ready to Assign" and not find it. There is no
  number in KB that answers "how much is unbudgeted right now".

Options:
- **(a)** Import expense `Assigned` only; leave income budgets empty. Simplest,
  honest, and the numbers that do exist are exactly right.
- **(b)** Back-fill income budgets from actual income per month, so income rows
  read `Available = 0`. Tidier-looking, but invents a plan the user never made.
- **(c)** Add a derived "Ready to Assign"-alike figure to the budget page
  (`total income actual − total expense budgeted` for the month). New feature,
  outside the importer.

Recommendation: **(a)** for the importer, and treat **(c)** as a separate
product question. **This is the one decision I would not make without you** —
it decides whether the migration feels like YNAB or like a different tool.

### D2 — Negative `Available` rollover · **decision required**

Measured on the sample: in **186 of 186** cases where a category's previous-month
`Available` was negative, YNAB **reset it to 0** and did not carry the negative
forward. Zero cases carried forward. This holds across every category group,
including credit-card payment categories.

`BudgetService.available()` **always** carries the negative forward, with no cap.

So from a migrated user's first overspend onward, KB's `Available` diverges from
the YNAB figure they remember, and the divergence compounds for the life of the
category.

Options:
- **(a)** Leave `BudgetService` alone; explain the difference in the import
  summary. Cheapest; the historical Available column will disagree with YNAB
  everywhere an overspend ever happened.
- **(b)** Add a team setting (`overspend_rolls_forward`, default current
  behaviour) and honour it in `available()`. Correct fix, touches the one method
  every budget surface depends on — needs its own test pass across the budget
  page, grid, `budget-vs-actual` report and the account-activity budget chart.
- **(c)** Importer-only: where YNAB reset a negative, write a compensating
  amount into the next month's `budget_amount` so KB's carry cancels out. Gets
  the numbers to match with no code change to `available()`, at the cost of
  `budget_amount` values that are not what YNAB said was assigned — which then
  looks wrong in the budget grid.

Recommendation: **(b)**, because (c) corrupts the meaning of the stored plan and
(a) leaves the headline "your numbers came across" claim false.

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

### D4 — Income has no categories · **decision required**

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

Recommendation: **(c)**. It is one screen, it is the highest-leverage screen in
the whole flow, and the existing "Map Categories" step of the CSV wizard is the
same shape — `Step4MapCategories` / `suggest_account_for_category` can be
followed closely.

### D5 — On-budget vs tracking accounts

Not in the export. Recoverable signal, exact on the sample:

> An account is **on-budget** if its `Starting Balance` row carries a category,
> or if any of its rows carries a category. Otherwise it is **tracking**.

That splits the sample 21 on-budget / 15 tracking, and every tracking account it
finds is genuinely one (TFSAs, FHSAs, GICs, pensions, RESP, home equity).

KB has no on/off-budget concept: every account is in one chart of accounts and
every transaction needs both legs. The consequence is D6 and the 122
uncategorized non-transfer rows (TFSA interest/growth, mortgage principal
credited to `Amroth Equity`), which have no counter-account in the export.

Proposal: import tracking accounts as ordinary asset accounts, and post their
uncategorized activity against a new non-system income/expense pair
(`Investment Income` / `Investment Loss`) rather than the system
`Reconciliation Adjustments` — these are real economic events, not bookkeeping
plugs, and burying them in equity would understate income.

### D6 — Transfers that carry a category · **decision required**

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

Recommendation: **(b)**, with one carve-out: `Investment Gain/Loss` (57 rows) is
not a goal, it is a valuation change — send it to the D5 income/expense pair.

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

80 parent transactions, 172 legs, memos prefixed `Split (i/n)`. KB handles these
natively as a multi-line `JournalEntry`, so the mapping is good — the grouping is
the fiddly part:

- 3 of 80 `(account, date)` buckets contain **two different splits**, so
  grouping by account+date alone is wrong.
- 1 bucket is **not contiguous** in file order (an unrelated row sits between two
  splits on `BBC Chequing 2024-04-30`).
- A split leg can itself be a **transfer** (`Viv's Paycheck (TD) 2026-05-28`:
  leg 1 an expense, leg 2 `Transfer : Cash`) — and that leg is also one half of a
  transfer pair, so naive handling double-counts the movement.

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

### D10 — Closed accounts and hidden categories

13 of 36 accounts end at exactly `0.00` — emptied and abandoned rather than
closed (YNAB doesn't export closure state). 9 categories sit in
`Hidden Categories`.

Decision needed: import and archive, or skip? Skipping loses history and breaks
the §2 reconciliation. Recommendation: import everything, and mark hidden
categories' accounts + zero-balance-with-no-recent-activity accounts as archived
so they stay out of the pickers. (Note `Account` has no `is_archived` field —
`JournalLine` does. This may need a small model addition, or the accounts board's
group ordering used to park them.)

### D11 — Free ordering

Checked: all 58 months in the Plan list groups and categories in **one identical
order** (`Credit Card Payments, Monthly, Cumulative, Tax Deductible, Savings,
Hidden Categories`). That is the user's own arrangement, and it maps directly
onto `AccountGroup.sort_order` / `Account.sort_order`, so the imported chart of
accounts arrives in the order they already know — through the board, reports,
budget page and grid.

Account numbers follow the project convention (1000s/2000s/3000s/4000s/5000s)
assigned in Plan order within each block.

### D12 — Staging vs direct posting · **decision required**

Does the register land in `BankTransaction` (the feed, awaiting categorisation)
or straight into the journal?

The pitch is "drop the CSVs and everything is populated", and the register is
**already categorised** — so: direct `JournalEntry` rows,
`source=SOURCE_IMPORT`, `status=STATUS_POSTED`, and **no** `BankTransaction`
rows. Creating feed rows would present 7,572 already-answered questions.

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

Tests: the sample export is the fixture. Assert 839 transfer pairs / 0
unmatched, 80 split groups, 6 liabilities, 21 on-budget accounts.

### Phase 2 — Apply

`apps/ynab_import/services/apply.py`, one `transaction.atomic` block:
1. `AccountGroup` / `Account` / `Institution` / `Payee` (1,123 payees →
   `bulk_create(ignore_conflicts=True)`)
2. `Budget` rows **first** — `JournalLine.save()` looks up its `Budget` on every
   save, so budgets must exist before lines, and lines must be `bulk_create`d
   with `budget_id` resolved in memory. **~13,300 lines: a naive per-line
   `save()` is ~13,300 extra queries.** This is the main performance trap.
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

Given the volume, run it as a **Celery task** with progress, not in the request.

### Phase 3 — Wizard

Vite entry `ynab-import-app`, reusing `common/Modal`, `Combobox`, `Toast` and the
`Step*` shape of the CSV wizard:

1. **Drop** both CSVs (auto-identified)
2. **Accounts** — review inferred type / group / opening balance, rename, drop (§D7)
3. **Income** — map the 43 inflow payees to income accounts (§D4)
4. **Savings → Goals** — confirm which `Savings` categories become goals (§D6)
5. **Preview** — counts, date range, net worth, and what will be skipped
6. **Apply** — progress, then the reconciliation result

Entry points: the onboarding takeover (a "Coming from YNAB?" branch on the
welcome screen, which is exactly the right moment and skips the questionnaire
entirely) and a standalone page for an existing empty team.

### Phase 4 — Tests

- Unit: parsing, pairing, splits, inference — sample export as fixture
- Integration: apply to a fresh team, then assert **§2's reconciliation passes
  for all 57 elapsed months**, net worth equals the sum of inferred closing
  balances, and every `JournalEntry` balances
- E2E (`e2e/tests/test_ynab_import.py` + `e2e/pages/ynab_import.py`): drop both
  files, walk the wizard, land on a dashboard with a non-zero net worth
- Note the `team` fixture is marked past onboarding, so a YNAB-import test needs
  the `unonboarded_team` fixture

---

## 5. Decisions I need from you

| | question | my recommendation |
|---|---|---|
| **D1** | Envelope vs forecast/actual: import expense `Assigned` only, back-fill income budgets, or build a Ready-to-Assign figure? | Import expense only; treat RTA as a separate product question |
| **D2** | YNAB resets negative `Available` to 0 (186/186 measured); KB carries it forward. Accept the divergence, add a team setting, or fudge `budget_amount`? | Add the setting — it is the only option that is both accurate and honest |
| **D4** | Income: one account, auto-derive from 43 payees, or a mapping screen? | Mapping screen, pre-filled by the heuristic |
| **D6** | Categorised transfers to tracking accounts: drop the category, or turn the 6 `Savings` categories into KB Goals? | Goals, with `Investment Gain/Loss` carved out |
| **D10** | Zero-balance accounts and 9 hidden categories: import-and-archive or skip? | Import and archive (skipping breaks §2) |
| **D12** | Register straight to the journal as posted, or through the bank feed? | Straight to the journal; no `BankTransaction` rows |

Also worth your call, lower stakes: whether this lives in the onboarding
takeover as a branch (my assumption) or as its own page, and whether a
migrated team should be able to re-run the import over existing data (my
assumption: no — refuse, offer wipe-and-retry).

---

## 6. Risks

- **`BudgetService.available()` is recursive per category per month.** 45
  categories × 58 months on the budget page and the grid, after import. Existing
  teams are small; a migrated team is not. Needs a look before Phase 3 ships.
- **`JournalLine.save()`'s per-line budget lookup** (Phase 2 step 2) is the
  difference between a 20-second import and a 10-minute one.
- Inference is only as good as the export. Every inferred value is shown for
  review before anything is written — that is the mitigation, and it is why
  Phase 1 is pure.
- The sample is one budget from one country. Rules that are exact here
  (`Starting Balance` categorisation, the CC-payment account list) should be
  treated as strong signals with a review step, never as guarantees.
