# Koala Budget — Testing Guide

This document is the living record of testing patterns, conventions, and coverage. Agents must read this before writing tests and append new patterns and edge cases after each feature.

---

## Test Frameworks

| Layer | Framework | Runner |
|-------|-----------|--------|
| Backend unit/integration | Django `TestCase` + DRF `APIClient` | `make test` |
| E2E browser tests | Playwright + pytest | `make test-e2e` |
| Coverage reporting | coverage.py | Minimum 50% enforced |

---

## Backend Test Structure

### File locations
- `apps/{app}/tests.py` — single-file tests for smaller apps
- `apps/{app}/tests/` — directory with multiple test files for complex apps (e.g. `bank_feed`)
- Test settings: `koala_budget/settings_test.py`

### Class structure
```python
class MyFeatureTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Create shared fixtures once for the whole class
        cls.team = TeamFactory.create()
        cls.user = UserFactory.create()
        cls.membership = MembershipFactory.create(team=cls.team, user=cls.user, role=Membership.ADMIN)

    def setUp(self):
        # Per-test setup (auth, etc.)
        self.client.force_login(self.user)
        set_current_team(self.team)

    def test_happy_path(self):
        ...

    def test_permission_denied_for_non_member(self):
        ...
```

### Naming conventions
- Test class: `{Feature}Tests` or `{Model}Tests`
- Test method: `test_{what_is_being_tested}_{condition_if_needed}`
- Examples: `test_create_journal_entry`, `test_create_journal_entry_unbalanced_raises_error`

### Must-have test cases (minimum for every new feature)
1. **Happy path** — the normal successful flow
2. **Permission test** — non-team-member cannot access; member cannot do admin actions
3. **Validation test** — invalid input raises appropriate error or returns 400
4. **Team isolation test** — data from one team is not visible to another team

### API endpoint tests
```python
def test_create_endpoint(self):
    response = self.client.post(
        reverse("api:myapp:model-list"),
        data={...},
        format="json",
    )
    self.assertEqual(response.status_code, 201)
    self.assertEqual(MyModel.for_team.count(), 1)
```

---

## E2E Test Structure

### File locations
- `e2e/tests/test_{feature}.py` — one file per feature area
- `e2e/pages/{feature}_page.py` — Page Object Model classes

### Page Object Model pattern
```python
# e2e/pages/accounts_page.py
class AccountsPage:
    def __init__(self, page):
        self.page = page

    def navigate(self, team_slug):
        self.page.goto(f"/a/{team_slug}/accounts/")

    def create_account(self, name, account_type):
        self.page.click("[data-testid='create-account-btn']")
        self.page.fill("[name='name']", name)
        self.page.select_option("[name='account_type']", account_type)
        self.page.click("[type='submit']")
```

### E2E test structure
```python
# e2e/tests/test_accounts.py
def test_create_account(page, team, user):
    accounts_page = AccountsPage(page)
    accounts_page.navigate(team.slug)
    accounts_page.create_account("Checking", "asset")
    assert page.locator("text=Checking").is_visible()
```

### Fixtures
- `team` — creates a Team
- `user` — creates a User with ADMIN membership in the team
- `member_user` — creates a User with MEMBER membership (read-only)
- `authenticated_page` — logs in and returns a page object

### E2E prerequisites
```bash
make start-bg   # Start Vite dev server in background
make test-e2e   # Run all E2E tests
make test-e2e-accounts  # Run specific test file
```

---

## Key Edge Cases Already Covered

### Journal / Double-entry
- Unbalanced entries rejected (`debits != credits` → ValidationError)
- Void entries cannot be edited
- JournalLine amount sign conventions (debit positive, credit negative)

### Team isolation
- Cross-team data access returns 404
- Team-scoped manager never returns data from other teams

### Budget
- Budget amounts are per-month; switching months shows correct data
- Goals with zero allocation show 0% progress (not divide-by-zero error)

### Bank Feed
- Duplicate transaction detection on Plaid sync
- CSV import with missing optional fields
- Uncategorized count badge updates after categorization

### Auth / Permissions
- Unauthenticated requests redirect to login
- MEMBER role cannot create/edit (returns 403 or 404)
- ADMIN role can perform all CRUD operations

### Accounts — filter state persistence (`AccountReturnTypeTest`)
- `return_type` param is preserved through account detail, edit (GET and POST), and delete views
- Cancel and breadcrumb links on edit/delete forms carry `return_type` back to the filtered list
- Invalid/unknown `return_type` values round-trip without error; list view ignores them
- Pattern: pass `?return_type=<value>` in test URLs and assert the redirect or link targets include the param

### Transactions — column filters and sorting (`TransactionColumnFilterAPITest`, `e2e/tests/test_transactions.py`)
- The table pages in as you scroll, so **every** filter and sort has to run server-side. A test that only checks the
  rows on screen would pass against a client-side filter that silently hides the rest of the ledger — assert against
  `response.data["count"]`, or seed more rows than one page holds
- Values on different columns AND together; several values on one column OR together
- The empty string is a real filter value: it selects rows with nothing in that column (an entry with no payee)
- An unparseable value (`?f_date=not-a-date`) is ignored rather than 400-ing or blanking the table, since a stale
  bookmark shouldn't look like an empty ledger
- `facets/` drops the queried column's *own* filter but honours every other one — without that, a column would only
  ever offer the values already ticked and nothing could be un-ticked. Test both halves
- Sorting has a `pk` tie-break; rows sharing a sort value must not shuffle between pages
- Hierarchical columns (date, both account columns) take a **branch** as one value — `2025`, `2025-03`,
  `t:income`, `g:12`, `a:34`. Test each depth separately and test that depths mix as OR; a token the parser doesn't
  recognise must be ignored, so an account-name string silently matching nothing would look like a passing test
- Facet trees roll counts up, so assert a branch's count against the sum of its leaves, not just its children's presence
- E2E: `tick_column_value` matches the value label **exactly**, because every row also renders its count — a substring
  match for "3" hits the year row whose count happens to be 3

### Audit trail (`apps/audit/tests.py`)
- `JournalEntry`/`JournalLine` create, update, and delete each write an `AuditLog` row with the right `action`; a no-op save writes nothing
- UPDATE diffs capture `{before, after}` per changed field only
- Frozen FK snapshots: changing a line's account then renaming the old account keeps the original name in the audit record
- The request user reaches signals via thread-local storage — tests call `set_current_user(None)` in `setUp`/`tearDown` to avoid cross-test leakage (the thread-local persists across `TestCase` methods since middleware doesn't run for direct ORM writes)
- Audit API is team-scoped: `event_type` filter works, cross-team events are excluded, non-members are denied
- Per-entry history endpoint `GET …/journal-entries/{id}/audit/` returns CREATE + UPDATE rows

### YNAB import (`apps/ynab_import/tests/`, `e2e/tests/test_ynab_import.py`)
- **The sample export is the fixture.** `docs/reference/*.csv` is a real five-year budget (7,572 register rows, 58
  months), and every figure `docs/ynab-import-plan.md` asserts was measured on it. The unit tests restate those
  figures — 839 transfer pairs, 83 splits, 6 liabilities, 22 on-budget accounts, 6,644 entries — so a change that
  quietly loses a transaction moves a number instead of passing
- `analyse` and `build` are **pure**, so most of the suite is `SimpleTestCase` with no database at all. Parsing the
  whole sample takes about a quarter of a second, so `fixtures.sample_analysis()` caches it per run rather than
  mocking it
- The reconciliation is itself the strongest test: `reconcile()` compares the planned journal lines against the
  Plan's own `Activity` and `Available` columns for every category in every month, plus each account's closing
  balance. An integration test asserts it passes after a real apply
- `BudgetService.available()` recurses a month at a time with a query each, so the exhaustive Available comparison is
  the pure replay; only a couple of categories are checked through the service itself
- A regression test pins `JournalLine.objects.bulk_create_for_import` to populate `budget_id`. **`bulk_create` skips
  `save()` and every signal**, which is the point — 13,000 field-diff `AuditLog` rows for one import would be noise,
  and the importer writes a single `AuditEvent` instead — but it means the budget link has to be made by hand, and a
  NULL there is invisible until something reads it
- Tests must not need a broker: progress reporting goes through the Celery result backend, and the task swallows a
  failure to report it. `CELERY_TASK_ALWAYS_EAGER` in `settings_test`/`settings_e2e` is what makes the apply path
  testable without a worker
- E2E: an account's name lives in an `<input>`'s value, which no text locator can see — the rows carry
  `data-account` / `data-payee` / `data-category` for that reason. The walk clicks Continue until the review screen
  appears rather than counting steps, so adding a screen does not break the suite
- **Progress is a contract, and it has its own tests.** The import runs in one
  transaction, so a progress row written inside it is invisible until the whole
  thing commits — a `TransactionTestCase` asserts the figure written through
  `ProgressChannel` is readable from another connection *while* that transaction is
  still open, with a control asserting the import's own write is not. Two more pin
  the safeguards: a channel that cannot open a connection, and one whose row is
  locked, both give up rather than stalling the import
- `celery_progress` reports **100% for any finished task, successful or failed**, so
  `api_status` must never hand that number to a running bar; there are tests for the
  clamp, for a dead worker being reported rather than waited for, and for the
  ordinary race (task returned, row about to be written) *not* being called a death
- **Coming back to an import is its own contract.** The work outlives the browser, so
  `YnabImportQuerySet.resumable()` decides what the page opens on, and the tests cover each
  case separately: one still running, one queued but not yet started (`uploaded` *with* a
  task id), one finished or failed inside the 24-hour window, one older than it, and an
  upload that was never applied — which must *not* resume, since nothing is running and
  nothing was written. Note the dashboard tests need an `OnboardingState` marked finished,
  or `team_home` redirects into the takeover and there is no page to read
- The full-export E2E test is marked `slow` (`-m "not slow"` to skip it); everything else uses the small synthetic
  export in `apps/ynab_import/tests/fixtures.py`

### Split transactions (`apps/bank_feed/tests/test_splits.py`)

- **Six of these were written against the unfixed code first and confirmed failing
  there**, which is the only way to know a regression test has teeth. The corruption
  one matters most: re-saving an existing split used to return HTTP 200 and leave the
  entry with debits at double its credits, so the test asserts `total_debits ==
  total_credits` rather than a status code
- `SplitTestCase.make_split()` builds the canonical shape — one bank line carrying the
  total, one counter line per leg. Reuse it rather than hand-rolling lines; getting the
  sign convention wrong in a fixture produces a test that passes against broken code
- `SplitArithmeticTest` walks the four worked examples in
  `docs/split-transactions-plan.md` §3.3 line by line, including the two mixed-sign
  cases (a refund leg inside an outflow, a gross paycheque with deductions). Those are
  where a sign convention breaks, and a two-leg same-sign test would not catch it
- A split's bank line keeps its `id` across every edit — asserted explicitly, because
  the obvious implementation (delete all lines, recreate) silently unreconciles a
  transaction the user confirmed against a statement
- `test_plain_entry_is_unchanged` in `apps/journal/tests.py` is the regression guard for
  the two-line branch of `TransactionRowSerializer._sides()`, including the $0.00 entry
  whose split falls back to line order

- `e2e/tests/test_splits.py` is **written but has not been run** — see the note under
  Known Coverage Gaps. Its selectors were verified against the running app by hand, but
  the suite itself needs an environment with a working Playwright browser
---

### Statement reconciliation (`apps/reconciliation/tests/`, `e2e/tests/test_reconcile.py`)

- `test_guards.py` — the reconciled-line guards, including the three defects that returned 200 before (transfer counterpart unreconciled by an edit, reconciled row moved/re-dated, reconciled entry voided).
- `test_session.py` — the plan's §6.1 worked examples as fixtures (chequing with a duplicate coffee; a credit card entered as "balance owed"), candidates' exclusions, adjustments' sign for assets and liabilities, undo of any statement, intact/drift.
- `test_diagnose.py` — one test per hint rule (pure, `SimpleTestCase`).
- `test_views.py` — API happy path as a plain member, statement-sign payloads, 400/409 on finish, cross-team 404s, a foreign line id refused, pages render.
- `apps/portability/tests/test_apply.py::StatementRoundTripTests` — statements survive export → import intact; `test_read_errors.py` covers a v1 archive and a dangling `reconciliation_id`.
- E2E (7): balance → finish → hub Intact; duplicate hint fixed in one click; card balance typed as printed; finish with adjustment; draft resumes after reload; feed selection arrives ticked; unreconcile in the feed marks the statement Changed and the next session shows the drift banner.

## Known Coverage Gaps

- `reports/` app has minimal test coverage — complex aggregation logic is untested
- `plaid/` sync logic is tested via mocks only — no integration test against Plaid sandbox
- `subscriptions/` webhook handling has no automated tests
- `chat/` and `ai/` apps have no unit tests for agent logic
- Frontend React components have no unit tests (no Jest/Vitest setup)

### Running E2E where the pinned browser is missing

Playwright pins a browser build the environment may not have — the failure reads
`Executable doesn't exist at .../chromium_headless_shell-<n>/...` and tells you to run
`playwright install`. Don't: point it at the browser that is already there instead, by
overriding the launch args locally (a `conftest.py` addition you keep out of the commit):

```python
@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    return {**browser_type_launch_args, "executable_path": "/opt/pw-browsers/chromium"}
```

### Driving `Combobox` and `DateField` in Playwright

Neither is a native control, so neither responds to `fill()` or `select_option()` alone.
`e2e/pages/transactions.py` has the two recipes every modal test now reuses:

- **`Combobox`**: click the input, `fill()` the text, then click the first `[role='option']`
  matching it. The option list is **portaled out of the modal** — a `<dialog>` paints in the
  browser's top layer, so a body portal would render behind it — which is why the option is
  addressed globally rather than scoped to the modal.
- **`DateField`**: click `button[data-testid='<id>']` to open it, then click the day inside
  `[data-testid='<id>-grid']` by its accessible name. It is a hand-drawn day grid, not an
  `<input type="date">`, so there is no value to type into

---

## Test Commands Reference

```bash
make test                                           # All backend tests
make test ARGS='apps.journal'                       # Single app
make test ARGS='apps.journal.tests.JournalTests'    # Single class
make test-e2e                                       # All E2E tests
make test-e2e-accounts                              # Specific E2E file
pytest e2e -m "not slow"                            # Skip the full YNAB export walk
```
