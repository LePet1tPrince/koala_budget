# Guided Onboarding Walkthrough — Plan

Status: proposal. No code written yet.

A first-run experience that (1) fades in over the empty dashboard, (2) asks a short
questionnaire about income and household, (3) generates a chart of accounts from the
answers, and (4) walks the user through import → categorize → budget → report → net worth
with in-app coach marks, ending in a "your net worth moved" moment.

---

## 1. What already exists (reuse, don't rebuild)

| Piece | Where | Use in the walkthrough |
|---|---|---|
| Team bootstrap on create | `apps/teams/signals.py::bootstrap_team_on_create` | Replaced by questionnaire-driven generation (see §2.1) |
| Template application engine | `apps/teams/services/template_engine.py::apply_template` | Extended, then used to write the generated CoA |
| Static CoA template | `apps/teams/services/template_budget.py::PERSONAL_BUDGET_TEMPLATE` | Becomes the fallback/"skip" template |
| Onboarding checklist | `templates/web/app_home.html` (`show_onboarding`), `apps/web/views.py::team_home` | Becomes the resume surface, driven by the new state model |
| CSV import wizard (5 steps, working) | `assets/javascript/bank_feed/react/CSVUploadWizard/` | Launched in-place at Task 1 — not re-implemented |
| CSV API | `BankFeedViewSet.upload_parse` / `upload_validate_dates` / `upload_preview` / `upload_confirm` (`apps/bank_feed/views.py`) | Unchanged |
| Category auto-suggest | `apps/bank_feed/services/csv_upload.py::suggest_account_for_category` | Pre-fills Step 3 of the wizard |
| Categorize Mode (gamified, single-txn) | `apps/bank_feed/views.py::categorize_mode`, `CategorizeMode.jsx` | Task 2 target |
| Budget autofill from actuals | `apps/budget/views.py::budget_autofill_view` | Task 3 one-click path |
| Income statement / net worth trend | `apps/reports/` | Tasks 4 and 5 targets |
| Confetti | `assets/javascript/common/confetti.js::fireConfetti` | Finale |
| Account/group create JSON API | `apps/accounts/urls.py` `api/create-account/`, `api/create-group/` | Inline edits during CoA review |
| Audit events | `apps/audit/utils.py::log_event` | Funnel instrumentation |
| `sort_order` on Account/AccountGroup | `apps/accounts/models.py` | Generated CoA sets explicit order |

---

## 2. Blocking gaps found in the current code

These must be resolved for the walkthrough to deliver its promise. Each is a real
change, not a nicety.

### 2.1 Every new team is seeded with 18 months of fake transactions

`bootstrap_team_on_create` calls `apply_template`, which loops 18 months and creates
3 `BankTransaction` rows per month (`template_engine.py`, "Sample Bank Transactions").
A user who then imports their real CSV sees 54 fabricated rows in the Inbox and a
polluted net-worth chart — the exact opposite of the moment this walkthrough is built
around.

**Resolution:** split bootstrap into *structure* (groups/accounts/payees) and *demo data*
(sample transactions). Structure generation moves behind the questionnaire; demo
transactions become opt-in via a "Explore with sample data" branch at Phase 0 and are
tagged so they can be wiped in one action.

### 2.2 No opening balances

Net worth is derived purely from journal activity (`ReportService`). A user who imports
90 days of CSV starts at a net worth of ~$0 and the chart shows only the delta over that
window. "Watch your net worth go up" has no anchor.

**Resolution:** an opening-balance micro-step in Phase C. For each asset/liability account
the user confirms a current balance as of a chosen date; one balanced `JournalEntry` per
account (asset `dr` / liability `cr`, offset to the existing system equity account
`Reconciliation Adjustments`, group `Equity Adjustments`, already created by the template).
Zero/blank is allowed and skips the entry.

### 2.3 No onboarding state anywhere

`show_onboarding` is inferred each request from row counts. There is nowhere to store
answers, position in the flow, skip, or resume.

**Resolution:** new `apps/onboarding` app (§5.1).

---

## 3. Flow

```
signup ──> /a/{slug}/onboarding/
             │
   Phase 0   │  Welcome takeover — fade in, 2 choices
             │    [Set up my books]  [Explore with sample data]
             ▼
   Phase A   │  About your money        3 questions   ~25s
             ▼
   Phase B   │  About your household    5 questions   ~40s
             ▼
   Phase C   │  Your chart of accounts  review + edit + opening balances
             ▼   (writes the CoA — first irreversible step)
   Phase D   │  Guided tasks, in the real app, with coach marks
             │    1 Import transactions      (CSV wizard / Plaid)
             │    2 Categorize them          (Categorize Mode)
             │    3 Set a budget             (autofill + tweak)
             │    4 See the report           (income statement)
             │    5 See net worth            (net worth trend)
             ▼
   Phase E   │  Finish — confetti, summary card, dismiss
             ▼
          dashboard
```

Phases 0–C are a **full-screen takeover** at its own URL. Phase D runs **inside the real
app** — no fake screens — with a persistent progress rail. This is deliberate: the
questionnaire is faster as a focused flow, while the tasks must build muscle memory on
the real UI.

---

## 4. Content

### 4.1 Phase A — About your money

| # | Question | Type | Options | Drives |
|---|---|---|---|---|
| A1 | Where does your money come from? | multi-select cards | Employment (salary/wages) · Self-employment or freelance · Rental property · Investments & dividends · Pension / government benefits · Other | Income accounts |
| A2 | Is this just you, or you and a partner? | single | Just me · Me and a partner | Splits employment income into two accounts |
| A3 | Roughly how much lands in your account each month? *(optional)* | currency, skippable | — | Seeds income budget rows; enables a sanity check in Phase D Task 3 |

A1 is the only required question in Phase A. A3 is explicitly labelled optional and
skippable with one click — asking for a number early is the highest-drop-off moment in
budgeting-app onboarding.

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
`docs/marketing-plan.md`.

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
credit card, line of credit) — matching the existing template convention. Property and
vehicle assets get `has_feed=False`.

The rule table lives in `apps/onboarding/coa_rules.py` as declarative data, not branching
code, so it is unit-testable and diffable.

### 4.5 Phase C — review the generated chart of accounts

Not a wall of text. Grouped by type, each account a chip the user can rename inline or
remove with an ✕. One "+ Add" per group. A one-line explainer per type
("Assets — what you own"). Confirming writes everything through `apply_template` in a
single transaction.

Then, in the same phase, the opening-balance step (§2.2): one row per asset/liability
account, currency input, "as of" date defaulting to the first of the current month,
all blank by default with a "I'll do this later" escape.

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
| `mode` | `CharField` | `real` / `sample` (the Phase 0 branch) |

Extends `BaseTeamModel` per repo convention, so it is team-scoped via `for_team` and
carries the team FK. Nothing financial lives here — the CoA is written to the real models.

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
| POST | `api/opening-balances/` | `{rows: [{account_id, amount, as_of}]}` | Creates balanced entries; returns net worth |
| POST | `api/task/` | `{slug, action: complete\|skip}` | Updates `tasks_done` |
| POST | `api/skip/` | — | Applies `PERSONAL_BUDGET_TEMPLATE` (structure only), marks skipped |

Server-side re-derivation on `apply-coa`: the client sends the *edited* list, but the
server re-validates every account against team scope, name uniqueness per type, and the
`AccountForm` rules — the client list is treated as a request, not as truth.

### 5.3 Frontend

New Vite entry `onboarding-app` → `assets/javascript/onboarding/onboarding-app.jsx`.

```
assets/javascript/onboarding/
  onboarding-app.jsx        mount + phase router
  OnboardingShell.jsx       fade/step orchestration, progress dots, back/skip
  QuestionCard.jsx          renders one catalog entry (single/multi/currency/text)
  CoaReview.jsx             grouped chips, inline rename/remove/add
  OpeningBalances.jsx       currency rows + as-of date
  TaskRail.jsx              Phase D persistent rail (rendered app-wide)
  Coachmark.jsx             anchored spotlight + tooltip
  api.js                    fetch helpers, js-cookie CSRF
```

Phase D's rail and coach marks mount from `templates/web/app/app_base.html`, gated on
`onboarding_active` from a new context processor — so they overlay the Inbox, Budget and
Reports pages without touching those templates.

Stack: React 19 + DaisyUI, consistent with the rest of the app. **No new dependency** —
the fade is CSS, the coach-mark positioning is `getBoundingClientRect` + a fixed-position
portal (same technique already used for the CSV wizard's body-portaled category dropdown
and date toast).

### 5.4 Entry points and redirect

`apps/web/views.py::team_home` redirects to the takeover when `OnboardingState` for the
team has `completed_at IS NULL AND skipped_at IS NULL`. The redirect fires once per team,
not per user — a second team member joining an onboarded team never sees it. State row is
created lazily on first `team_home` hit rather than in the team `post_save` signal, to
keep the signal cheap and avoid a migration-time backfill for existing teams (existing
teams get `completed_at = now()` in the data migration and never see the flow).

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
| Takeover exit → Phase D | Backdrop fades, rail slides in from the right | 380ms |
| Net worth reveal (Task 5) | Chart line draws left→right; the number counts up | 900ms draw, 700ms count |
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
- The koala mascot from the Goals "Koala Climb" style is a natural progress motif here —
  optional, and cheap to add later since it is just an illustration swap.

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
  when `BankTransaction` count > 0, Task 2 when a `JournalEntry` exists, Task 3 when a
  `Budget` row exists, Tasks 4/5 on report page view. A user who already did the thing
  never gets told to do it.
- **Multi-user teams:** the flow is team-scoped and shown to the first admin only.

---

## 8. Instrumentation

`log_event` (`apps/audit/utils.py`) with new `AuditEvent` types
`ONBOARDING_STARTED`, `ONBOARDING_PHASE_COMPLETED` (`{phase}`),
`ONBOARDING_COMPLETED`, `ONBOARDING_SKIPPED` (`{phase}` where they dropped).
This gives a funnel per phase and per question without a third-party analytics dependency,
and answers the only question that matters post-launch: which question is losing people.

---

## 9. Testing

**Backend** (`apps/onboarding/tests.py`, Django `TestCase` + `setUpTestData`):
- `build_template` for each single-answer case, and for a maximal answer set (asserts no
  duplicate account names, every account has a valid group, every group a valid type).
- `apply-coa` is idempotent across two identical POSTs.
- Cross-team permission test: team A cannot read or write team B's state (required by the
  repo's "happy path + permission test" rule).
- Opening balances produce balanced entries (`sum(dr) == sum(cr)`) and the resulting net
  worth equals the sum of entered asset balances minus liabilities.
- Skip path applies the fallback template and sets `skipped_at`.

**E2E** (`e2e/`, POM at `e2e/pages/onboarding.py`):
- Full happy path: signup → all questions → CoA review → CSV import → categorize →
  budget → report shows the imported spend → net worth is non-zero.
- Skip path lands on the dashboard with the legacy checklist.
- Resume: reload mid-flow, land on the same phase.

Testids: `onboarding-takeover`, `onboarding-question-{id}`, `onboarding-continue`,
`onboarding-skip`, `coa-review`, `coa-chip-{slug}`, `opening-balances`, `task-rail`,
`task-{slug}`, `onboarding-finish`.

---

## 10. Implementation order

Each phase is independently shippable and leaves the app in a working state.

| # | Scope | Depends on |
|---|---|---|
| 1 | Split `bootstrap_team_on_create` into structure vs. sample data; gate sample data behind a flag (§2.1) | — |
| 2 | `apps/onboarding` app: model, migration, catalog, rules, `build_template`, tests | 1 |
| 3 | Opening-balance service + endpoint (§2.2), usable on its own from the accounts page | 1 |
| 4 | Takeover UI: Phases 0/A/B, motion spec, skip/resume | 2 |
| 5 | Phase C: CoA review + opening balances UI | 3, 4 |
| 6 | Phase D: task rail, coach marks, inferred completion | 4 |
| 7 | Phase E: finish card, confetti, audit events; retire the old checklist into a resume card | 6 |
| 8 | E2E suite | 7 |

Phases 1–3 are backend-only and carry the risk; 4–7 are UI on a settled contract.

---

## 11. Open decisions

1. **Sample-data branch** — keep "Explore with sample data" at Phase 0, or drop demo data
   entirely? Keeping it needs a one-click wipe, or users will end up with fake history
   permanently mixed into real books.
2. **Currency question** — the app has no currency field; Canadian focus implies CAD.
   Ask, or hardcode until multi-currency exists?
3. **Plaid vs CSV at Task 1** — offer both, or lead with Plaid and treat CSV as the
   fallback? Plaid is faster but adds a credential step at the highest-anxiety moment.
4. **Question count** — 8 required questions is the current draft. Cutting B6 and A3 gets
   to 6 and roughly 45 seconds. Worth an A/B test once the funnel events from §8 exist.
5. **Where opening balances live long-term** — the Phase C step is the first use, but it
   is a generally missing feature; it may deserve a permanent home on the account detail
   page.
