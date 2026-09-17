# Guided Onboarding Walkthrough — Plan

Status: proposal. No code written yet.

A first-run experience that (1) fades in over the empty dashboard, (2) asks a short
questionnaire about income and household, (3) generates a chart of accounts from the
answers, and (4) walks the user through CSV import → categorize → budget → report, ending
in a net-worth moment once there is real data to anchor it.

**Decisions locked** (from review, 2026-09-17):

- No bootstrap/sample transactions. New teams start empty — real data only.
- CSV import only in the walkthrough. Plaid is more fragile today and is not the first-run path.
- Everything is CAD. No currency question.
- All 8 questions kept.
- Opening balances and the net-worth reveal are **gated behind real categorized
  transactions** — neither appears until the ledger can support them.
- A **downloadable sample statement** is offered at the import step, so a user with no
  file to hand still walks the real flow. It is a download, not a seed: they import it
  themselves, through the ordinary wizard, into books they can clear.

**Built so far** (branch `claude/affectionate-ptolemy-r9egme`): steps 1 and the sample
statement from §10 — see §12.

---

## 1. What already exists (reuse, don't rebuild)

| Piece | Where | Use in the walkthrough |
|---|---|---|
| Team bootstrap on create | `apps/teams/signals.py::bootstrap_team_on_create` | Structure only after §2.1; CoA generation moves behind the questionnaire |
| Template application engine | `apps/teams/services/template_engine.py::apply_template` | Sample-transaction loop deleted; then used to write the generated CoA |
| Static CoA template | `apps/teams/services/template_budget.py::PERSONAL_BUDGET_TEMPLATE` | Becomes the fallback/"skip" template |
| Onboarding checklist | `templates/web/app_home.html` (`show_onboarding`), `apps/web/views.py::team_home` | Becomes the resume surface, driven by the new state model |
| CSV import wizard (5 steps, working) | `assets/javascript/bank_feed/react/CSVUploadWizard/` | Launched in-place at Task 1 — not re-implemented |
| CSV API | `BankFeedViewSet.upload_parse` / `upload_validate_dates` / `upload_preview` / `upload_confirm` (`apps/bank_feed/views.py`) | Unchanged |
| Category auto-suggest | `apps/bank_feed/services/csv_upload.py::suggest_account_for_category` | Pre-fills Step 3 of the wizard |
| Categorize Mode (gamified, single-txn) | `apps/bank_feed/views.py::categorize_mode`, `CategorizeMode.jsx` | Task 2 target |
| Manual transaction create | `BankFeedViewSet.create` | Task 1 escape hatch for users with no CSV to hand |
| Budget autofill from actuals | `apps/budget/views.py::budget_autofill_view` | Task 3 one-click path |
| Income statement / net worth trend | `apps/reports/` | Tasks 4 and 5 targets |
| Confetti | `assets/javascript/common/confetti.js::fireConfetti` | Finale |
| Account/group create JSON API | `apps/accounts/urls.py` `api/create-account/`, `api/create-group/` | Inline edits during CoA review |
| Audit events | `apps/audit/utils.py::log_event` | Funnel instrumentation |
| `sort_order` on Account/AccountGroup | `apps/accounts/models.py` | Generated CoA sets explicit order |

---

## 2. Gaps in the current code

### 2.1 Every new team is seeded with 18 months of fake transactions — delete this

`bootstrap_team_on_create` calls `apply_template`, which loops 18 months creating 3
`BankTransaction` rows per month (`template_engine.py`, "Sample Bank Transactions"). A
user who then imports their real CSV sees 54 fabricated rows in the Inbox and a polluted
net-worth chart.

**Resolution: remove it outright.** Delete the `sample_transactions` loop from
`apply_template` and the `sample_transactions` key from `PERSONAL_BUDGET_TEMPLATE`. Teams
get structure (groups, accounts, payees) and nothing else.

Verified safe: `BOOTSTRAP_TEAM_ON_CREATE` is already `False` in both `settings_test.py`
and `settings_e2e.py`, so no backend test or E2E fixture depends on the sample rows. The
only caller is the signal.

Existing teams carrying seeded rows need a one-off cleanup — a management command
`purge_sample_transactions` matching `source=SOURCE_SYSTEM` rows that have no
`JournalEntry`, run manually, not a data migration (deleting user-visible financial rows
automatically on deploy is not acceptable).

### 2.2 No opening balances — needed, but deferred behind real data

Net worth is derived purely from journal activity (`ReportService`). With no opening
balances a user's net worth reflects only the imported window, not their actual position.

**Resolution: keep the feature, move it late.** Opening balances are *not* asked for during
the questionnaire. They surface as the first half of Task 5, once the user has categorized
transactions and has seen the ledger work — at which point "this number is only counting
what you've imported; add your starting balances" is a question they have the context to
answer. One balanced `JournalEntry` per account (asset `dr` / liability `cr`, offset to the
existing system equity account `Reconciliation Adjustments` in group `Equity Adjustments`,
already created by the template). Blank is allowed and creates nothing.

Consequence to accept: between Task 1 and Task 5 the net-worth figure on the dashboard is
the imported delta, not a true position. The walkthrough therefore does not show or
reference net worth before Task 5 — that is the reason for the gate, not just sequencing.

### 2.3 No onboarding state anywhere

`show_onboarding` is inferred each request from row counts. There is nowhere to store
answers, position in the flow, skip, or resume.

**Resolution:** new `apps/onboarding` app (§5.1).

---

## 3. Flow

```
signup ──> /a/{slug}/onboarding/
             │
   Phase 0   │  Welcome takeover — fade in, single CTA: [Set up my books]
             ▼
   Phase A   │  About your money        3 questions   ~25s
             ▼
   Phase B   │  About your household    5 questions   ~40s
             ▼
   Phase C   │  Your chart of accounts  review + inline edit
             ▼   (writes the CoA — first irreversible step)
   Phase D   │  Guided tasks, in the real app, with coach marks
             │    1 Import a CSV            (CSV wizard)          ── gate ──┐
             │    2 Categorize them         (Categorize Mode)               │
             │    3 Set a budget            (autofill + tweak)              │
             │    4 See the report          (income statement)              │
             │    5 Net worth               (opening balances, then reveal) ┘
             ▼
   Phase E   │  Finish — confetti, summary card, dismiss
             ▼
          dashboard
```

Phases 0–C are a **full-screen takeover** at its own URL. Phase D runs **inside the real
app** — no fake screens — with a persistent progress rail.

**Task 1 is a hard gate.** With sample data removed and Plaid out of scope, nothing
downstream can render without a real import. Tasks 2–5 render locked, with a one-line
reason, until `BankTransaction` exists. Two escapes so the gate is never a dead end:

- *"I don't have a file right now"* → collapses the rail, leaves the flow resumable,
  returns the user to the dashboard with a "Pick up where you left off" card.
- *"Add one manually"* → the existing manual-create form, which satisfies the gate with a
  single transaction and lets a curious user see the whole loop in 60 seconds.
- *"Download a sample file"* → `GET bankfeed/api/feed/sample_csv/` hands back a realistic
  CAD chequing statement, which the user then uploads through the same wizard. This is the
  primary escape: it exercises every step of the real flow rather than skipping past it,
  and it avoids the fabricated-history problem of §2.1 because the user imports it
  deliberately, into their own books, and can delete it.

**Task 5 is gated on `JournalEntry`, not on `BankTransaction`.** Uploading a CSV produces
uncategorized bank transactions and moves nothing — net worth only changes once Task 2
creates journal entries. Gating Task 5 on the upload alone would show the user a flat line
and undercut the payoff.

---

## 4. Content

### 4.1 Phase A — About your money

| # | Question | Type | Options | Drives |
|---|---|---|---|---|
| A1 | Where does your money come from? | multi-select cards | Employment (salary/wages) · Self-employment or freelance · Rental property · Investments & dividends · Pension / government benefits · Other | Income accounts |
| A2 | Is this just you, or you and a partner? | single | Just me · Me and a partner | Splits employment income into two accounts |
| A3 | Roughly how much lands in your account each month? *(optional)* | currency (CAD), skippable | — | Seeds income budget rows; sanity check at Task 3 |

A1 is the only required question in Phase A. A3 is explicitly optional and skippable with
one click — asking for a number early is the highest-drop-off moment in budgeting-app
onboarding.

### 4.2 Phase B — About your household

| # | Question | Type | Options | Drives |
|---|---|---|---|---|
| B1 | Where do you live? | single | Rent · Mortgage · Own outright · Live with family / other | Housing expense + mortgage liability |
| B2 | Kids at home? | single | No · Yes | Childcare / kids' activities / education expenses |
| B3 | How do you get around? | multi | Car with a loan · Car paid off · Transit · Bike / walk | Vehicle asset, car-loan liability, fuel/insurance/transit expenses |
| B4 | Any of these debts? | multi | Credit card · Line of credit · Student loan · Other loan · None | Liability accounts |
| B5 | Where do you save or invest? | multi | TFSA · RRSP · RESP · Non-registered / brokerage · Savings account · Not yet | Investment asset accounts |
| B6 | Anything else you spend on regularly? | multi chips | Pets · Travel · Fitness · Hobbies · Subscriptions · Charity · Medical | Optional expense accounts |

Canadian registered-account names (TFSA/RRSP/RESP) match the go-to-market focus in
`docs/marketing-plan.md`. All amounts throughout the app are CAD; no currency is asked or
displayed as a choice.

### 4.3 Optional Phase B+ — first goal

One question: "What's the first thing you want to save for?" — free text + target amount
+ optional date, or Skip. Creates a `Goal` (auto-creates its equity account), so the Goals
page isn't empty on first visit.

### 4.4 Answer → chart of accounts

Every rule is additive on top of a **base set** that every team gets: `Chequing Account`,
`Savings Account`, `Credit Card`, `Groceries`, `Utilities`, `Transportation`, `Dining Out`,
`Entertainment`, `Miscellaneous`, plus the system `Equity Adjustments` group.

| Answer | Creates |
|---|---|
| A1 Employment | Income: `Salary Income` (+ `Salary — Partner` when A2 = partner) |
| A1 Self-employment | Income: `Self-Employment Income`; Expense group `Business Expenses` with `Business Supplies`, `Professional Fees` |
| A1 Rental | Asset: `Rental Property`; Income: `Rental Income`; Expenses: `Property Tax`, `Property Maintenance`, `Property Insurance` |
| A1 Investments | Income: `Dividend & Interest Income` |
| A1 Pension / benefits | Income: `Pension & Benefits` |
| A1 Other | Income: `Other Income` |
| B1 Rent | Expense: `Rent`, `Tenant Insurance` |
| B1 Mortgage | Liability: `Mortgage`; Expenses: `Mortgage Interest`, `Property Tax`, `Home Insurance`, `Home Maintenance` |
| B1 Own outright | Expenses: `Property Tax`, `Home Insurance`, `Home Maintenance` |
| B2 Kids | Expense group `Family`: `Childcare`, `Kids' Activities`, `Education` |
| B3 Car with a loan | Asset: `Vehicle`; Liability: `Car Loan`; Expenses: `Fuel`, `Car Insurance`, `Car Maintenance` |
| B3 Car paid off | Asset: `Vehicle`; Expenses: `Fuel`, `Car Insurance`, `Car Maintenance` |
| B3 Transit | Expense: `Transit` |
| B4 Credit card | (already in base — asks for a nickname instead) |
| B4 Line of credit | Liability: `Line of Credit` |
| B4 Student loan | Liability: `Student Loan`; Expense: `Student Loan Interest` |
| B4 Other loan | Liability: `Other Loan` |
| B5 TFSA / RRSP / RESP / Brokerage | Asset accounts of the same name in `Investment Accounts` |
| B6 chips | One expense account per chip in `Variable Expenses` |

`has_feed=True` for asset/liability accounts a bank would report (chequing, savings,
credit card, line of credit) — matching the existing template convention, and determining
which accounts can receive a CSV at Task 1. Property and vehicle assets get
`has_feed=False`.

The rule table lives in `apps/onboarding/coa_rules.py` as declarative data, not branching
code, so it is unit-testable and diffable.

### 4.5 Phase C — review the generated chart of accounts

Not a wall of text. Grouped by type, each account a chip the user can rename inline or
remove with an ✕. One "+ Add" per group. A one-line explainer per type
("Assets — what you own"). Confirming writes everything through `apply_template` in a
single transaction, then exits the takeover straight into Task 1.

No opening balances here — see §2.2.

---

## 5. Technical design

### 5.1 New app: `apps/onboarding/`

```
apps/onboarding/
  models.py          OnboardingState
  questions.py       QUESTION_CATALOG (declarative, serialized to the client)
  coa_rules.py       ANSWER_RULES (§4.4)
  services/
    builder.py       build_template(answers) -> template dict for apply_template
    opening.py       create_opening_balances(team, rows) -> JournalEntry list
    gates.py         task_state(team) -> per-task locked/available/done
  views.py           takeover view + JSON endpoints
  urls.py
  tests.py
```

`OnboardingState(BaseTeamModel)` — one row per team (`unique_together = ["team"]`):

| Field | Type | Notes |
|---|---|---|
| `answers` | `JSONField(default=dict)` | Raw answers, versioned by `catalog_version` |
| `catalog_version` | `PositiveSmallIntegerField` | So old answers stay interpretable when questions change |
| `phase` | `CharField(choices)` | `welcome`/`income`/`household`/`review`/`tasks`/`done` |
| `tasks_done` | `JSONField(default=list)` | Task slugs completed in Phase D |
| `started_at` / `completed_at` / `skipped_at` | `DateTimeField(null=True)` | Funnel + resume |

Extends `BaseTeamModel` per repo convention, so it is team-scoped via `for_team`. Nothing
financial lives here — the CoA is written to the real models. `mode` is gone: with sample
data removed there is only one path.

### 5.2 Endpoints

All `login_and_team_required`, all under `/a/{team_slug}/onboarding/`. CSRF via
`X-CSRFToken` header (same pattern as the accounts board), `ensure_csrf_cookie` on the
takeover view.

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `` | — | Takeover page; mounts React |
| POST | `api/answers/` | `{phase, answers}` | Saves answers, advances `phase`; idempotent |
| POST | `api/preview-coa/` | `{answers}` | Generated CoA (no writes) — powers Phase C |
| POST | `api/apply-coa/` | `{accounts, groups}` | Writes CoA atomically; returns created accounts |
| GET | `api/tasks/` | — | Per-task `locked`/`available`/`done` + the gate reason |
| POST | `api/opening-balances/` | `{rows: [{account_id, amount, as_of}]}` | Creates balanced entries; returns net worth. **400 if the team has no `JournalEntry`** — the gate is enforced server-side, not just hidden in the UI |
| POST | `api/task/` | `{slug, action: complete\|skip}` | Updates `tasks_done` |
| POST | `api/skip/` | — | Applies `PERSONAL_BUDGET_TEMPLATE` (structure only), marks skipped |

Server-side re-derivation on `apply-coa`: the client sends the *edited* list, but the
server re-validates every account against team scope, name uniqueness per type, and the
`AccountForm` rules — the client list is a request, not truth.

### 5.3 Frontend

New Vite entry `onboarding-app` → `assets/javascript/onboarding/onboarding-app.jsx`.

```
assets/javascript/onboarding/
  onboarding-app.jsx        mount + phase router
  OnboardingShell.jsx       fade/step orchestration, progress dots, back/skip
  QuestionCard.jsx          renders one catalog entry (single/multi/currency/text)
  CoaReview.jsx             grouped chips, inline rename/remove/add
  OpeningBalances.jsx       currency rows + as-of date (Task 5, not Phase C)
  TaskRail.jsx              Phase D persistent rail, lock states, gate reasons
  Coachmark.jsx             anchored spotlight + tooltip
  api.js                    fetch helpers, js-cookie CSRF
```

Phase D's rail and coach marks mount from `templates/web/app/app_base.html`, gated on
`onboarding_active` from a new context processor — so they overlay the Inbox, Budget and
Reports pages without touching those templates.

Stack: React 19 + DaisyUI, consistent with the rest of the app. **No new dependency** —
the fade is CSS, the coach-mark positioning is `getBoundingClientRect` + a fixed-position
portal (the technique already used for the CSV wizard's body-portaled category dropdown
and date toast).

### 5.4 Entry points and redirect

`apps/web/views.py::team_home` redirects to the takeover when `OnboardingState` for the
team has `completed_at IS NULL AND skipped_at IS NULL`. The redirect fires once per team,
not per user. The state row is created lazily on first `team_home` hit rather than in the
team `post_save` signal, to keep the signal cheap; existing teams get `completed_at = now()`
in the data migration and never see the flow.

---

## 6. Motion and visual design

The "fade into" is the first impression, so it is specified rather than left to the
implementer.

| Moment | Motion | Timing |
|---|---|---|
| Takeover entry | Backdrop `opacity 0→1` + `backdrop-blur-none→sm`; card `opacity 0→1`, `translateY 12px→0`, `scale .98→1` | 420ms `cubic-bezier(.16,1,.3,1)`, card delayed 120ms |
| Question → question | Outgoing `opacity→0`, `translateX -16px`; incoming from `+16px`; height animated to avoid jump | 260ms out / 300ms in, 60ms overlap |
| Option select | Card border → `--color-primary`, `scale 1→1.02→1` | 180ms |
| Phase → phase | Progress dot fills, heading cross-fades | 300ms |
| CoA reveal (Phase C) | Account chips stagger in, 30ms apart, capped at 400ms total | — |
| Takeover exit → Task 1 | Backdrop fades, rail slides in from the right, CSV wizard coach mark pulses once | 380ms |
| Task unlock | Locked row's padlock cross-fades to the step number, row lifts `translateY 2px→0` | 240ms |
| Net worth reveal (Task 5) | Chart line draws left→right; the number counts up from the pre-opening-balance figure to the post | 900ms draw, 700ms count |
| Finish | `fireConfetti` from `common/confetti.js`, `burst` origin | — |

Constraints:

- Every transition wrapped in `@media (prefers-reduced-motion: reduce)` → opacity-only,
  120ms. The count-up becomes a straight set.
- Only `opacity` and `transform` are animated (no layout-triggering properties), so the
  flow stays at 60fps on a mid-range phone.
- Full-screen takeover is mobile-first: one question per screen, thumb-reachable options,
  a sticky bottom bar with Back / Continue / Skip.
- Theme: DaisyUI tokens only (`--color-primary`, `--color-base-*`), so light and dark both
  work without a second palette.
- The koala mascot from the Goals "Koala Climb" style is a natural progress motif —
  optional, cheap to add later since it is just an illustration swap.

---

## 7. Behaviour rules

- **Skippable at every step.** "Skip setup" applies `PERSONAL_BUDGET_TEMPLATE` structure
  and drops the user on the dashboard with the existing checklist.
- **Resumable.** State is server-side; closing the tab mid-flow resumes at the same phase.
  No `localStorage` dependency.
- **Idempotent.** `apply-coa` uses `get_or_create` (as `apply_template` already does), so a
  double submit cannot duplicate accounts.
- **Non-destructive.** The walkthrough only ever adds. Re-running it on a team that already
  has accounts merges by name and never deletes.
- **Phase D is non-blocking.** The user can navigate anywhere; the rail persists with live
  task state and a collapse toggle.
- **Task completion is inferred from real data**, not from clicking "Done": Task 1 completes
  when `BankTransaction` exists, Task 2 when a `JournalEntry` exists, Task 3 when a `Budget`
  row exists, Task 4 on income-statement view, Task 5 when opening balances are submitted
  (or explicitly skipped) and the net-worth report is viewed.
- **Gates are computed server-side** in `services/gates.py` and returned by `api/tasks/`.
  The UI renders what the server says; it does not decide.
- **Multi-user teams:** the flow is team-scoped and shown to the first admin only.

---

## 8. Instrumentation

`log_event` (`apps/audit/utils.py`) with new `AuditEvent` types
`ONBOARDING_STARTED`, `ONBOARDING_PHASE_COMPLETED` (`{phase}`),
`ONBOARDING_TASK_COMPLETED` (`{slug}`), `ONBOARDING_COMPLETED`,
`ONBOARDING_SKIPPED` (`{phase}` where they dropped).

Given Task 1 is now a hard gate with no sample-data bypass, the single most important
metric is the **Task 1 conversion rate** — what fraction of users who finish the
questionnaire actually import a CSV, versus taking the "no file right now" escape and
never returning. That number decides whether Plaid needs to come back into the first-run
path.

---

## 9. Testing

**Backend** (`apps/onboarding/tests.py`, Django `TestCase` + `setUpTestData`):

- `build_template` for each single-answer case, and for a maximal answer set (asserts no
  duplicate account names, every account has a valid group, every group a valid type).
- `apply-coa` is idempotent across two identical POSTs.
- Cross-team permission test: team A cannot read or write team B's state (required by the
  repo's "happy path + permission test" rule).
- `gates.task_state` — Task 2 locked with no `BankTransaction`; Task 5 locked when
  transactions exist but no `JournalEntry` does; all unlocked once both exist.
- `api/opening-balances/` returns 400 when the team has no `JournalEntry`.
- Opening balances produce balanced entries (`sum(dr) == sum(cr)`) and the resulting net
  worth equals imported activity plus the entered asset balances minus liabilities.
- Skip path applies the fallback template and sets `skipped_at`.

**Also update** `apps/teams/tests/` to assert `apply_template` creates **no**
`BankTransaction` rows (locks in §2.1 so the seed can't come back by accident).

**E2E** (`e2e/`, POM at `e2e/pages/onboarding.py`):

- Full happy path: signup → 8 questions → CoA review → CSV import → categorize → budget →
  income statement shows the imported spend → opening balances → net worth non-zero.
- Gate path: after the questionnaire, Tasks 2–5 render locked; importing unlocks Task 2;
  categorizing unlocks Task 5.
- Escape path: "I don't have a file right now" returns to the dashboard with a resume card.
- Skip path lands on the dashboard with the legacy checklist.
- Resume: reload mid-flow, land on the same phase.

Testids: `onboarding-takeover`, `onboarding-question-{id}`, `onboarding-continue`,
`onboarding-skip`, `coa-review`, `coa-chip-{slug}`, `task-rail`, `task-{slug}`,
`task-{slug}-locked`, `opening-balances`, `onboarding-finish`.

---

## 10. Implementation order

Each phase is independently shippable and leaves the app in a working state.

| # | Scope | Depends on |
|---|---|---|
| 1 | Delete sample transactions from `apply_template` + template (§2.1); add `purge_sample_transactions` command; add the regression test | — |
| 2 | `apps/onboarding` app: model, migration, catalog, rules, `build_template`, `gates`, tests | 1 |
| 3 | Takeover UI: Phases 0/A/B, motion spec, skip/resume | 2 |
| 4 | Phase C: CoA review + `apply-coa` | 2, 3 |
| 5 | Phase D: task rail, gates, coach marks, inferred completion, Tasks 1–4 | 4 |
| 6 | Opening-balance service + endpoint, wired as Task 5 (§2.2) | 5 |
| 7 | Phase E: finish card, confetti, audit events; retire the old checklist into a resume card | 6 |
| 8 | E2E suite | 7 |

Phase 1 ships on its own and is worth doing immediately regardless of the rest of this
plan — it removes fake financial data from every new account today.

Phases 1–2 are backend-only and carry the risk; 3–7 are UI on a settled contract.

---

## 11. Open decisions

1. **Question count** — 8 required questions is the current draft, kept for v1. Cutting B6
   and A3 gets to 6 and roughly 45 seconds. Worth an A/B test once the funnel events from
   §8 exist, not before.
2. **Where opening balances live long-term** — Task 5 is the first use, but it is a
   generally missing feature; it likely deserves a permanent home on the account detail
   page so users can correct a starting balance later.
3. **When Plaid rejoins the first-run path** — deliberately out of scope now. Revisit when
   the Task 1 conversion number from §8 exists, or when Plaid reliability improves.
4. **Whether the sample statement needs a one-click undo.** It is built (§12) and is
   opt-in, so there is no silent fake history — but a user who imports it and then wants
   their books clean currently has to delete the rows by hand. A "remove the sample data"
   action would be cheap if that turns out to bite.

---

## 12. Built so far

Implementation step 1 of §10, plus the sample statement from open decision 4.

### Seeded fake transactions removed

`apply_template` (`apps/teams/services/template_engine.py`) creates structure only —
account groups, accounts, payees. The 18-month × 3-row `BankTransaction` loop and the
`sample_transactions` key in `PERSONAL_BUDGET_TEMPLATE` are gone, along with the now-unused
`month_start` argument and `account_map`.

Found while removing it: **every one of the three seeded rows had an inverted sign.**
`BankTransaction.amount` follows the Plaid convention (positive = money out), but the seed
recorded a salary deposit as `+1000.00` (an outflow) and a grocery purchase as `-50.00`
(an inflow). Any new team's opening numbers were not merely fictional, they were backwards.
Deleting the seed resolves it; the detail is recorded here because it is the reason to
distrust any figure a pre-change team saw before its first real import.

`purge_sample_transactions` (`apps/teams/management/commands/`) cleans up teams created
before this change. Dry run by default, `--delete` to apply, `--team <slug>` to scope. It
only removes rows that are unmistakably seed data: `source=system`, **not** categorized,
and matching a seeded description — so a row the user has since categorized, or any row of
their own, is left alone. A management command rather than a data migration, because
deleting user-visible financial records should be deliberate and dry-runnable.

Tests: `apps/teams/tests/test_bootstrap.py` — structure is created, **no** `BankTransaction`
or `JournalEntry` is, the template no longer declares `sample_transactions`, and
`apply_template` stays idempotent.

### Sample bank statement

`apps/bank_feed/services/sample_csv.py::build_sample_csv()` renders a fictional Canadian
chequing account, served by `GET /a/{slug}/bankfeed/api/feed/sample_csv/` as a file
download. Offered from step 1 of the upload wizard ("Don't have a statement handy?"),
so it is useful outside onboarding too.

Two design points, both load-bearing:

- **Dual `Funds In` / `Funds Out` columns, not a single `Amount`.** Under the Plaid
  convention a single-column file would need a *negative* number for a paycheque, which
  looks wrong to anyone who opens it. The dual form reads naturally, is auto-detected by
  the column-mapping keyword list, and is converted correctly by the dual-column branch of
  `preview_transactions`. This is the same convention the old seed got backwards.
- **Dates generated relative to today** — three complete months plus the current month to
  date. A file with hardcoded dates would describe ancient history a year on, and would
  land outside the budget month the walkthrough then asks the user to set. Deterministic
  (fixed variation factors, no randomness), so the same day always yields the same file.

Roughly 70 transactions: semi-monthly payroll, rent, utilities, phone, transit, fuel,
groceries, subscriptions, dining. Net positive by about $1,700/month, so net worth
visibly climbs — the payoff the walkthrough is built around. No `Category` column, so the
rows land uncategorized and the categorize step still has its job.

Tests: `apps/bank_feed/tests/test_sample_csv.py` — the file is pushed through the real
parse/preview/create pipeline rather than asserted on as text. Covers the date window,
no future-dated rows, determinism, short months (Feb), header auto-mapping, zero parse
errors, inflows landing as negative amounts (a paycheque must not read as spending),
rows arriving uncategorized, a positive net after import, and endpoint auth including a
non-member refusal.

### Not yet built

Everything else in §10: the `apps/onboarding` app, the takeover UI, the task rail and
gates, opening balances, and the E2E suite.
