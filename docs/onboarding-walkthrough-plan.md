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
| Restyled design system | `docs/restyle-plan.md`, `assets/styles/theme.css`, `app-components.css` | `koala`/`koala-dark` themes and the `.app-card` / `.app-surface` / `.money` / `.side-link` primitives the whole flow is built from (§6.1) |
| Shared MUI theme hook | `assets/javascript/common/useMuiTheme.js` | Any MUI control in the flow themes through this, not `prefers-color-scheme` |

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
   Phase B   │  About your household    6 questions   ~40s
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

The walkthrough is built **on the restyled app** (`docs/restyle-plan.md`, Phases 1–4,
merged 2026-09-17), not alongside it. That plan governs; anything below that contradicts it
is wrong and should be changed to match.

### 6.1 Design-system conformance

| Rule | What it means here |
|---|---|
| Canvas recedes, surfaces advance | Takeover panels are `.app-card` / `.app-surface` (`bg-base-100` + `border-base-300` hairline) on the `base-200` canvas. Never a bare `<div>` with a shadow. |
| `--depth: 0` — borders separate, not shadows | No `shadow-*` on any onboarding panel. The one exception the restyle allows is a true overlay: the takeover and its backdrop may carry a shadow, because they float above the app rather than sit on it. |
| One brand hue | Eucalyptus `primary` is the flow's colour: progress fill, selected option, active rail step, primary CTA. Ochre `accent` is for attention only — an unlocked-task nudge, not decoration. Nothing else introduces a hue. |
| `/70` is the muted-text token | Helper copy, question subtitles, gate reasons: `text-base-content/70`. `/40`–`/45` is for decorative icons and chevrons only. `/50` and `/60` are retired app-wide and must not come back with this feature. |
| Money uses `.money`, never `font-mono` | Opening-balance inputs, the net-worth reveal, and any figure in the finish card get tabular numerals via `.money`. |
| No hardcoded Tailwind greys | `text-gray-*`, `bg-white`, `divide-gray-*` are theme-blind. Tokens only — the restyle removed all 34 remaining instances and this feature must not reintroduce one. |
| No `pg-*` classes | The Pegasus layer is deleted. Links are `link link-primary` (the former `pg-link`). |
| Tables | `.table-quiet`, never `table-zebra`. Note it is a plain class and cannot be `@apply`-ed. |
| MUI components | If the opening-balance rows or any picker use MUI, theme them with the shared `common/useMuiTheme.js` hook. Reading `prefers-color-scheme` directly is the bug that hook exists to fix — it ignores an explicit light choice on a dark-set OS. |

**Selected-option state** reuses the sidebar's active idiom rather than inventing one:
`bg-primary/10` tint, `font-medium text-primary`, and for the task rail the same 3px
`bg-primary` left rail as `.side-link-active`. A user who has learned the nav already knows
what "selected" looks like.

**Shell fit.** Phase D's rail mounts from `templates/web/app/app_base.html`, which is now a
sticky `w-[248px] shrink-0` sidebar next to a `min-w-0` content column capped at
`max-w-[1180px]`. The rail must not compete with that sidebar: it docks bottom-right on
desktop as a collapsible `.app-surface` panel, and becomes a bottom sheet below `lg`, where
the sidebar is hidden and the mobile top nav is in play. It never adds a third vertical
column — the `shrink-0` fix exists precisely because a wide element used to squeeze the nav.

**Type** is Inter (self-hosted variable, `assets/styles/fonts.css`). Question headings take
the restyle's page-title step (`text-xl font-semibold tracking-tight`); the finish card's
net-worth figure takes the metric step (`text-[1.75rem] font-semibold tracking-tight
tabular-nums`).

### 6.2 Motion

The "fade into" is the first impression, so it is specified rather than left to the
implementer.

| Moment | Motion | Timing |
|---|---|---|
| Takeover entry | Backdrop `opacity 0→1` + `backdrop-blur-none→sm`; card `opacity 0→1`, `translateY 12px→0`, `scale .98→1` | 420ms `cubic-bezier(.16,1,.3,1)`, card delayed 120ms |
| Question → question | Outgoing `opacity→0`, `translateX -16px`; incoming from `+16px`; height animated to avoid jump | 260ms out / 300ms in, 60ms overlap |
| Option select | Fills to `bg-primary/10`, border to `border-primary`, `scale 1→1.02→1` | 180ms |
| Phase → phase | Progress dot fills `primary`, heading cross-fades | 300ms |
| CoA reveal (Phase C) | Account chips stagger in, 30ms apart, capped at 400ms total | — |
| Takeover exit → Task 1 | Backdrop fades, rail docks in, CSV wizard coach mark pulses once | 380ms |
| Task unlock | Locked row's padlock cross-fades to the step number, row lifts `translateY 2px→0` | 240ms |
| Net worth reveal (Task 5) | Chart line draws left→right; the `.money` figure counts up from the pre-opening-balance value to the post | 900ms draw, 700ms count |
| Finish | `fireConfetti` from `common/confetti.js`, `burst` origin | — |

Constraints:

- Every transition wrapped in `@media (prefers-reduced-motion: reduce)` → opacity-only,
  120ms. The count-up becomes a straight set.
- Only `opacity` and `transform` are animated (no layout-triggering properties), so the
  flow stays at 60fps on a mid-range phone.
- Full-screen takeover is mobile-first: one question per screen, thumb-reachable options,
  a sticky bottom bar with Back / Continue / Skip.
- Both themes: `koala` and `koala-dark`. Theme is read from the `data-theme` attribute /
  `dark` class, not from `prefers-color-scheme`, and an in-page toggle must recolour the
  flow without a reload.
- The koala mascot from the Goals "Koala Climb" style is a natural progress motif —
  optional, cheap to add later since it is just an illustration swap.


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

1. **Question count** — 8 required plus one optional (A3) is the current draft, kept for
   v1. The exact set lives in `apps/onboarding/questions.py`; this document does not
   restate a count, because the two drifted apart once already. Cutting B6 gets to 7
   required and roughly 45 seconds. Worth an A/B test once the funnel events from §8
   exist, not before — and cheap to do, since the catalog is data (§12).
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

### Verified against the restyle

The app restyle (`docs/restyle-plan.md` Phases 1–4) merged into this branch after the
above was built. The sample-file affordance was re-checked on the new theme rather than
assumed: it renders correctly in both `koala` and `koala-dark`, uses `text-base-content/70`
(the new muted-text token) and `link link-primary` (the former `pg-link`), and introduces
no hardcoded grey, no `pg-*` class and no `table-zebra`.

Driven end to end in a real browser on the restyled UI: the link downloads
`koala-sample-statement.csv`, and uploading that file straight back through the wizard
auto-maps every column with no manual input — 69 rows, `%Y-%m-%d` detected with "All 69
dates match this format", dual-amount mode auto-selected, `Funds In` → Inflow and
`Funds Out` → Outflow.

### The `apps/onboarding` app (step 2)

Backend only — no UI, nothing user-visible yet.

`OnboardingState` (`models.py`) is one row per team (`unique_together = ["team"]`,
`BaseTeamModel`): answers, `catalog_version`, phase, `tasks_done`, and
started/completed/skipped timestamps. Team-scoped rather than user-scoped, so a second
member joining an onboarded team is not asked to set the books up again.

**The question set is data.** `questions.py` holds `QUESTION_CATALOG`; adding, cutting or
reordering a question is an edit to that one list. Nothing else counts or names questions
— the phases walked, the client payload, the server-side validation and the generated
chart of accounts are all derived from it. Two rules keep that honest, both enforced by
`validate_catalog()`:

- **A rule lives on the option that triggers it**, never in a table keyed by question id,
  so deleting a question takes its rules with it and cannot leave a dangling rule behind.
- **A cross-question dependency is a `question_id:option_value` token** in
  `Grant.requires`, checked against the catalog. The one such dependency today is a
  partner's salary account, which only makes sense alongside employment income.

Both halves were verified by actually doing it, not by assertion. Cutting the `extras`
question: all 69 tests still pass, no code change anywhere. Cutting `income_sources`,
which `household_shape` depends on: fails with the named error
`household_shape:partner: requires unknown question 'income_sources'`, plus the two
downstream tests that notice the Income group went empty.

A test also caught a real gap while being written: `income_sources` was a required
question a user with no matching circumstances could not honestly answer. Rather than
relax the test, `Option.catch_all` now makes the escape explicit data, and
`validate_catalog()` refuses a required question that lacks one — so a future added
question cannot deadlock the flow.

`services/builder.py::build_template(answers)` is a pure function (no database, no side
effects), so the review step can preview the chart of accounts and apply it later with no
risk the two disagree. It dedupes by name — a mortgage and a rental property both want
Property Tax — pulls in any group an account needs, and ignores answers naming questions
or options that no longer exist, because stored answers outlive the catalog that produced
them.

`services/gates.py::task_state(team)` computes what is open, closed or done, server-side,
with the reason for each lock. The two gating facts are deliberately different: a
**bank transaction** unlocks categorizing and budgeting, which need something to work on;
a non-void **journal entry** unlocks the report and net-worth steps, because only
categorizing moves a balance. `can_set_opening_balances()` is the same gate, and the
endpoint will enforce it rather than merely hiding the UI. A voided entry does not count,
matching how voids are treated everywhere else in the app.

`apply_template` gained `sort_order` on groups and accounts, so the generated account
numbers (1000s assets, 2000s liabilities, 4000s income, 5000s expenses) drive display
order on the accounts board and in reports. Templates that omit it are unaffected.

Tests: 69 across `test_catalog.py` (coherence, payload, and that no module outside the
catalog hardcodes a question id), `test_builder.py` (grants, dependencies, dedupe,
unknown-answer tolerance, determinism), `test_apply.py` (the generated template actually
applies, is idempotent, merges on re-run, creates no transactions, and isolates teams),
`test_gates.py` (the transaction/entry boundary, void handling, team isolation) and
`test_models.py`.

### The takeover UI (step 3)

The questionnaire, end to end: welcome → 9 questions, one per screen → the chart of
accounts is built and the user lands on the dashboard. Skip and resume both work.

`/a/{slug}/onboarding/` is a full-screen takeover on its own URL rather than a modal over
the dashboard — the questions read faster without the app behind them, and a real URL is
what makes the flow resumable by navigating back to it. Site nav and footer are suppressed
on it, so nothing shows through the backdrop that the user can't act on.

`team_home` redirects an unfinished team into it. Endpoints: `api/answers/` (merges rather
than replaces, so posting one phase at a time never drops an earlier one),
`api/complete/` (builds and applies the chart of accounts, creates the first goal) and
`api/skip/` (applies the stock template — skipping must not leave a team with no accounts
to work in).

**The bootstrap conflict, resolved.** `bootstrap_team_on_create` was still applying the
stock 16-account template to every new team, which would have handed the user a mortgage
and a line of credit before they were asked whether they had either, and made the
questionnaire decorative. A new `ONBOARDING_ENABLED` setting gates it: when on, bootstrap
creates nothing and onboarding owns the chart of accounts; when off, the old behaviour
returns and nobody is sent through the flow. Onboarding applies a template on both exits,
so neither path leaves a team empty. Migration `0002` marks pre-existing teams complete so
a deploy does not throw them all into the walkthrough.

`OnboardingShell.jsx` never names a question — it switches on *kind* and *phase*, both of
which are data, so editing the catalog needs no frontend change. Answers save in the
background between screens; a failed save is swallowed rather than blocking, because every
answer is posted again with the final submit, so the worst case is a resume losing a few
answers rather than the flow stalling.

Two bugs the work surfaced:

- `catalog_payload()` was not carrying `catch_all`, so the client's mutual-exclusion logic
  ("none of these" clearing the other picks, and vice versa) was reading `undefined`. The
  step-2 test asserting the payload's shape had locked in the wrong shape; both are fixed.
- The view called `state.start()` on GET, which advanced past `welcome` and meant the
  welcome screen never rendered. `mark_seen()` now records the first sight of the flow for
  the funnel, and `start()` — which moves the phase — happens when the user actually
  begins.

Verified in a browser on both themes: the dashboard bounces an un-onboarded team into the
takeover, Continue stays disabled until a required question is answered, and a full
run-through as a renting household with a paid-off car, a student loan, kids, a TFSA and
an RRSP produced exactly those accounts and no others — `Salary Income — Partner` present
via the dependency, `Vehicle` without a `Car Loan`, no `Mortgage`, and none of the stock
template's unasked-for accounts. The named goal reached the dashboard's "To reach all
goals" card, its backing account in a real `Goals` group rather than the system equity one.

### Chart-of-accounts review (step 4)

Phase C now sits between the last question and completion: the generated chart, grouped
by type, each account a chip the user can rename in place or drop, with an "Add" per
group.

**The client posts edits, not a chart of accounts.** This is the security-relevant choice.
A wholesale list would let a client invent an account inside the system equity group, flip
`is_system`, or attach an account to a group no answer created. Instead the payload is a
diff — `{removed, renamed, added}` — and the server rebuilds the chart from the *stored
answers* and applies the diff to its own set, so none of that is expressible. Both
`api/preview-coa/` and the apply path rebuild from the same `build_template`, so what the
user reviews and what they get cannot drift.

Refused outright, each with a user-facing message and nothing written: removing the system
reconciliation account (opening balances and reconciliation post against it), adding to a
group outside the generated chart, a blank or over-long name, and a name that collides
within its account *type* — the same uniqueness rule `AccountForm` and the accounts board
use, checked case-insensitively.

Every edit round-trips through the server: changing a chip re-posts the diff and redraws
from the response, so the list on screen is always the server's answer rather than an
optimistic guess. A rejected edit leaves the previous list up with the reason above it.
Edits reset whenever review is re-entered, because they are keyed by generated account
name and changing an answer can remove the account a rename referred to.

**Deviation from §5.2:** there is no separate `api/apply-coa/`. `api/complete/` takes the
same optional `edits` payload and remains the one endpoint that finishes the flow —
applying the chart, creating the first goal and marking the state complete. A second
endpoint that did the apply half would have been a name for something `complete` already
does.

A bug the tests caught: `parse_edits` iterated a bare string character by character, so
`{"removed": "Rent"}` read as a request to remove accounts named "R", "e", "n", "t". The
container types are now checked before iterating.

Verified in a browser in both themes: 28 accounts generated for a mortgage-holding
household with kids, a car loan and a line of credit; renaming Groceries → Food & Drink
and removing Pets left 27, and the database afterwards held exactly that — the rename
applied, Pets gone, Travel untouched, the system account still present and still hidden
from review.

### The guided task rail (step 5)

Phase D, over the real app. `OnboardingState.complete()` now moves to the `tasks` phase
rather than straight to `done`: `completed_at` is what stops `team_home` redirecting into
the takeover, but the walkthrough is not over, and the phase is what keeps the rail on
screen. `finish_tasks()` ends it, when every task is done or the user dismisses it.

The rail is docked bottom-right, not added as a third column — the shell is a sticky
248px sidebar beside a capped content column, and `shrink-0` exists precisely because a
wide element used to squeeze the nav. Below `lg` it spans the width and sits clear of the
mobile dock.

`onboarding_rail` (context processor) decides only *whether* the rail renders, on one
query against `phase`. The rail then fetches its own state from `GET api/tasks/`, so the
gate computation — several existence queries — never runs on a page that will not show
one. The script loads in `app_base.html`'s body rather than `page_js`, because child
templates define their own `page_js` and would override it on exactly the pages the rail
is for.

**A detected task cannot be claimed by the client.** `POST api/task/` refuses any task
with `auto_detected=True`; accepting a claim would let the checklist say a user imported
transactions when they never did. Only the "go and look at this" tasks are reportable, and
those complete by the user arriving on the page — checked against *every* open task rather
than just the current one, since the order is a suggestion and someone who opens the
report with a half-written budget has plainly done that step.

Coach marks are portaled to the body, fixed-positioned, and fail-safe: they poll briefly
for their anchor and render nothing if it never appears. The rail's own copy carries the
instruction, so a missing mark costs a nicety rather than the guidance — which matters,
since the anchors point at controls in components free to change.

Two fixes the browser run forced:

- The import task's anchor pointed at the upload button, which only exists *after* an
  account is selected — so the mark never appeared on the page the user actually lands on.
  It now rings the account cards, the real first action. (`LineApp.jsx` gained a
  `categorize-mode-btn` testid so the categorize anchor is real too.)
- Coach marks were placed below their anchor, which on the bank feed covered the next
  account card — hiding one of the things it was pointing at. They now prefer the side,
  falling back to below and then above.

Verified in a browser: a freshly onboarded team sees Import available with everything else
locked and explained; the rail survives navigation; seeding a transaction and a categorized
entry flips Import and Categorize to done and unlocks the rest; visiting the income
statement marks "See where the money went" done, and it stays done across a reload.

### Opening balances and the net-worth reveal (step 6)

The §2.2 gap, closed. Net worth is `sum(dr - cr)` over asset and liability lines, so a
ledger holding only an imported window reports the *change* over that window rather than
what the user has. `services/opening.py::create_opening_balances()` writes one balanced
entry per account — asset debited, liability credited, each against the system equity
account that already exists for reconciliation — so `sum(dr - cr)` moves by exactly what
the user said.

Task 5 opens a dialog rather than navigating (`Task.dialog`, so it stays data). Asking
inside the rail beats sending the user to a report and hoping they find a prompt there.

**The gate is enforced, not hidden.** `POST api/opening-balances/` refuses a team with no
non-void `JournalEntry`, and the `GET` reports the gate rather than the accounts. Anchoring
a net worth before any categorized activity gives the user nothing to sanity-check it
against — which is the whole reason the step was deferred to here.

Refused with a user-facing message, nothing written: a non-numeric amount, a negative one
(a debt is entered as what is owed, so a minus sign is nearly always a misunderstanding),
an income or expense account, and an account belonging to another team. Those last two are
refused rather than silently dropped — dropping them would leave the user believing they
had set a balance. A blank or zero is not an error: that is how an account is skipped.
Re-submitting skips accounts that already have an opening balance, since the step can be
revisited and a second entry would silently double the figure.

**The reveal happens in the dialog**, not on the report page: the before/after pair is
already in hand there, so the number the user has been squinting at counts up to the one
they recognise, with a link onward to the trend. A bug caught in the browser: the figure
rendered as "CA$4,458" because `Intl` with `style: 'currency'` writes CAD that way, which
looked foreign next to every other "$" on the page; it now matches the `currency` template
filter exactly.

Also fixed: `existing_opening_balances()` counted the equity offset account, which carries
a line on every one of these entries, so it reported as "already has an opening balance" —
meaningless for an account nobody is asked about.

**Deviation from §6.2:** the chart-draw animation on the net-worth report page is not
built. The count-up reveal lives in the dialog instead, which needed no changes to the
reports templates and puts the moment where the user already is.

Verified in a browser in both themes, then against the ledger: entering $2,500 chequing,
$1,200 savings and $800 TFSA on a team sitting at −$42 produced three entries, each
balancing to the cent, and a net worth of exactly $4,458.

### The finish card, instrumentation and the resume nudge (step 7)

**The funnel from §8 exists.** Six `AuditEvent` types (audit migration `0005`) record
`ONBOARDING_STARTED` (first sight of the takeover, once),
`ONBOARDING_PHASE_COMPLETED` (`{phase, next}` — the phase being *left*),
`ONBOARDING_COMPLETED` (`{accounts, answers}`), `ONBOARDING_SKIPPED` (`{phase}` where
they bailed), `ONBOARDING_TASK_COMPLETED` (`{task}`, once per task) and
`ONBOARDING_FINISHED` (`{reason: all_tasks_done | dismissed, tasks_done}`).

The per-phase pair is the point: a completion rate says people drop out, while these say
*which question* loses them. The completed event carries the answers too, so a question
that turns out to drive nothing in the chart of accounts can be spotted and cut — which
is exactly the §11 open decision about trimming the question count.

Verified end to end rather than only in tests: a clean run recorded `started` →
`phase_completed` (income→household) → `phase_completed` (household→goal) →
`completed {accounts: 28}` with all nine answers attached. An abandoned run showed as a
start with phase events and no completion — the drop-off signal working as intended.

**The finish card** fires when the last task lands, over whatever page the user is on,
with the shared `fireConfetti` the Goals page already uses. It shows their own numbers —
accounts built, transactions imported, net worth — rather than a slogan, since that is
the whole argument for having done this. The summary is computed only when the walkthrough
actually ends, so the ordinary task POST stays a cheap write.

**The old three-step checklist on the dashboard is retired.** It duplicated the task rail
with none of its gates. What replaces it is a narrower nudge: a "Finish setting up" card
shown only to a team that skipped or dismissed the guide *and* still lacks accounts,
transactions or a budget. `POST api/task/ {action: "resume"}` puts the rail back, keeping
whatever tasks were already done.

A bug this surfaced: the `net_worth` task was **uncompletable**. It is not auto-detected,
and step 5's arrival-completion excluded tasks carrying a dialog — so nothing could ever
mark it done and the walkthrough could never finish. The exclusion is gone: the dialog is
a shortcut that makes the figure meaningful, but the task is "watch your net worth move",
which is done by looking at it. Also fixed: the finish card asked `fireConfetti` for an
`origin` of `'burst'`, which is not one of the module's two named origins — anything else
is read as an `{x, y}` point, so it would have produced `NaN` positions.

### The E2E suite (step 8)

17 Playwright tests in `e2e/tests/test_onboarding.py`, with page objects in
`e2e/pages/onboarding.py` (the takeover, the task rail, and the dashboard nudge).
All 45 E2E tests in the repo pass.

**A regression this caught before it shipped.** `settings_e2e` inherits
`ONBOARDING_ENABLED = True`, and the shared `team` fixture created a team with no
`OnboardingState` — which is by definition un-onboarded. Every existing E2E test would
have been redirected into the takeover instead of the page it was about, and the
fixture's `wait_for_url` would not have caught it, because `/a/{slug}/onboarding/` still
matches `**/a/{slug}/**`. The fixture now marks the team past the walkthrough, which is
the state any test that is not *about* onboarding actually wants; `unonboarded_team` and
`onboarding_page` are the opt-in for the ones that are.

`OnboardingPage.answer_all()` walks whatever question is on screen rather than a fixed
sequence, so adding or cutting a catalog entry does not break the suite — the same
property §12's step 2 set up on the server, carried through to the tests.

Two bugs in the tests themselves, both found by running them rather than by reading them:

- The net-worth assertion read the revealed figure the instant it appeared and caught it
  mid-count-up (`$65.70` on its way to `$2,458.00`). `revealed_net_worth()` now polls
  until two consecutive reads agree.
- A test asserted an onboarded team sees no resume nudge, but the fixture team is
  onboarded *and empty* — exactly who the nudge is for. It now gives the team accounts,
  a transaction and a budget first, and a second test covers the other half of the rule.

Coverage: the redirect into the flow; welcome → questions; a required question disabling
Continue; answers surviving a reload; the review reflecting the answers (rent but no
mortgage, a vehicle but no car loan); a removed account staying out of the books; the
generated chart matching the answers; skip still leaving a usable chart; the rail's gates
before and after real data; the rail persisting across pages; opening balances moving net
worth to a checked figure; the gate holding before anything is categorized; dismiss →
resume; and the old checklist being gone.

### Not yet built

Nothing — steps 1–8 of §10 are complete. What remains are the §11 open decisions, now
answerable from the funnel events rather than by guessing.
