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

---

## Known Coverage Gaps

- `reports/` app has minimal test coverage — complex aggregation logic is untested
- `plaid/` sync logic is tested via mocks only — no integration test against Plaid sandbox
- `subscriptions/` webhook handling has no automated tests
- `chat/` and `ai/` apps have no unit tests for agent logic
- Frontend React components have no unit tests (no Jest/Vitest setup)

---

## Test Commands Reference

```bash
make test                                           # All backend tests
make test ARGS='apps.journal'                       # Single app
make test ARGS='apps.journal.tests.JournalTests'    # Single class
make test-e2e                                       # All E2E tests
make test-e2e-accounts                              # Specific E2E file
```
