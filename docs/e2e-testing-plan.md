# End-to-End Testing Plan

## Overview

This document describes the plan for implementing end-to-end (E2E) tests for Koala Budget using **Playwright for Python**. E2E tests will cover the critical user journeys through the full application stack—Django backend, PostgreSQL database, and React/Django-template frontend.

---

## 1. Framework Choice: Playwright (Python)

**Recommendation: `playwright` Python library via `pytest-playwright`**

| Criterion | Playwright (Python) | Cypress | Selenium |
|-----------|--------------------|---------|---------|
| Django integration | Native (pytest plugin) | Manual server setup | Manual setup |
| Async support | Yes (Django Channels) | No | No |
| Headless Docker | Excellent | Good | Fragile |
| React SPA support | Excellent | Excellent | Limited |
| Speed | Fast | Medium | Slow |
| Multi-browser | Yes | Limited | Yes |

Playwright Python is the best fit because it:
- Integrates naturally with the existing Django test infrastructure
- Can share factories and fixtures with unit tests (via `factory_boy`)
- Runs reliably headless in Docker
- Has auto-wait semantics that handle React's async rendering without explicit sleeps

---

## 2. Directory Structure

```
e2e/
├── conftest.py              # pytest fixtures: browser, live_server, authenticated pages
├── pages/                   # Page Object Models
│   ├── base.py              # BasePage with common helpers
│   ├── auth.py              # LoginPage, SignupPage
│   ├── dashboard.py         # DashboardPage
│   ├── accounts.py          # ChartOfAccountsPage
│   ├── transactions.py      # TransactionsPage
│   ├── bank_feed.py         # BankFeedPage
│   ├── budget.py            # BudgetPage
│   └── reports.py           # ReportsPage
├── tests/
│   ├── test_auth.py         # Authentication flows
│   ├── test_accounts.py     # Chart of accounts management
│   ├── test_transactions.py # Transaction entry and categorization
│   ├── test_bank_feed.py    # CSV import and bank feed staging
│   ├── test_budget.py       # Monthly budget setting and tracking
│   └── test_reports.py      # Report generation and display
├── factories.py             # Test data factories (shared with unit tests)
└── pytest.ini / pyproject.toml additions
```

**Pattern: Page Object Model (POM)**
Each page class wraps Playwright's `Page` object and exposes high-level actions (`page.login(email, password)`, `page.create_account(name, type)`) rather than raw locators. This keeps test code readable and centralizes selector maintenance.

---

## 3. Installation and Setup

### 3.1 Python Dependencies

Add to `pyproject.toml` under `[project.optional-dependencies]` or dev dependencies:

```toml
[dependency-groups]
e2e = [
    "pytest-playwright>=0.6",
    "pytest-django>=4.9",
    "factory-boy>=3.3",
]
```

Install via:
```bash
uv sync --group e2e
playwright install chromium  # or: playwright install --with-deps chromium
```

### 3.2 pytest Configuration

Add to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "koala_budget.settings_e2e"
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
```

### 3.3 E2E Settings File

Create `koala_budget/settings_e2e.py`:

```python
from .settings import *  # noqa: F403

# Use a separate database so E2E runs don't touch dev data
DATABASES["default"]["NAME"] = "koala_budget_e2e"

# Speed up password hashing in tests
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Capture emails in memory
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Disable Stripe webhooks / Plaid calls in tests
STRIPE_LIVE_MODE = False
PLAID_ENV = "sandbox"

# Allow the live server to accept connections from Playwright
ALLOWED_HOSTS = ["*"]
```

### 3.4 Docker Service for E2E

Add a new service to `docker-compose.yml` (or a separate `docker-compose.e2e.yml`):

```yaml
  e2e:
    build:
      context: .
      dockerfile: Dockerfile.dev
    command: >
      bash -c "playwright install --with-deps chromium &&
               pytest e2e/ -v --browser chromium"
    volumes:
      - .:/code
    environment:
      PYTHONUNBUFFERED: '1'
      DJANGO_SETTINGS_MODULE: koala_budget.settings_e2e
    env_file:
      - path: ./.env
        required: false
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
      web:
        condition: service_started
```

### 3.5 Makefile Target

Add to `Makefile`:

```makefile
test-e2e: ## Run E2E tests
	@docker compose run --rm \
		-e DJANGO_SETTINGS_MODULE=koala_budget.settings_e2e \
		web bash -c "playwright install --with-deps chromium && pytest e2e/ -v $(ARGS)"
```

---

## 4. Core Fixtures (`e2e/conftest.py`)

```python
import pytest
from playwright.sync_api import Page, Browser

@pytest.fixture(scope="session")
def django_db_setup():
    """Run migrations once per session against the e2e database."""
    ...

@pytest.fixture
def live_url(live_server):
    """Base URL of the Django live server."""
    return live_server.url

@pytest.fixture
def authenticated_page(page: Page, live_url, django_user_factory) -> Page:
    """Returns a Playwright Page already logged in as a regular user."""
    user = django_user_factory(email="test@example.com", password="testpass123")
    page.goto(f"{live_url}/accounts/login/")
    page.fill("[name=login]", user.email)
    page.fill("[name=password]", "testpass123")
    page.click("[type=submit]")
    page.wait_for_url("**/dashboard/**")
    return page

@pytest.fixture
def team_page(authenticated_page: Page, live_url, team_factory) -> Page:
    """Returns a Page for a user that has a fully set-up team/workspace."""
    ...
```

---

## 5. Test Scenarios (Priority Order)

### 5.1 Authentication (High Priority)

| Test | Description |
|------|-------------|
| `test_signup_and_login` | New user registers, verifies email (mocked), and logs in |
| `test_login_invalid_credentials` | Error message shown for wrong password |
| `test_logout` | User can log out and is redirected to login page |
| `test_password_reset` | Password reset email flow (check `mail.outbox`) |

### 5.2 Chart of Accounts (High Priority)

| Test | Description |
|------|-------------|
| `test_create_account` | User creates a new expense account |
| `test_edit_account` | User renames an account and changes its type |
| `test_delete_account` | User deletes an account with no transactions |
| `test_account_tree_display` | Account groups render with correct hierarchy |

### 5.3 Journal / Transactions (High Priority)

| Test | Description |
|------|-------------|
| `test_create_journal_entry` | Manual double-entry transaction is created |
| `test_transaction_list_filter` | Filter transactions by date range and account |
| `test_transaction_categorize` | Uncategorized transaction is assigned an account |
| `test_transaction_edit` | Existing transaction amount/description is updated |

### 5.4 Bank Feed Import (High Priority)

| Test | Description |
|------|-------------|
| `test_csv_upload` | User uploads a CSV file; staged transactions appear |
| `test_approve_staged_transaction` | Staged transaction is approved and moves to journal |
| `test_reject_staged_transaction` | Staged transaction is rejected and removed |
| `test_duplicate_detection` | Uploading same CSV twice does not double-import |

### 5.5 Monthly Budget (Medium Priority)

| Test | Description |
|------|-------------|
| `test_set_budget_target` | User sets a monthly target for an expense category |
| `test_budget_actuals_display` | Budget page shows correct actual vs. target amounts |
| `test_budget_month_navigation` | User navigates between months |

### 5.6 Reports (Medium Priority)

| Test | Description |
|------|-------------|
| `test_income_statement_renders` | Income statement page loads with chart |
| `test_report_date_filter` | Changing date range updates the report data |

### 5.7 Team / Multi-tenancy (Medium Priority)

| Test | Description |
|------|-------------|
| `test_team_data_isolation` | User A cannot see User B's accounts/transactions |
| `test_invite_team_member` | Admin invites a new member; invite email is sent |

---

## 6. Page Object Model Example

```python
# e2e/pages/accounts.py
from playwright.sync_api import Page

class AccountsPage:
    def __init__(self, page: Page, base_url: str):
        self.page = page
        self.url = f"{base_url}/accounting/accounts/"

    def goto(self):
        self.page.goto(self.url)
        self.page.wait_for_selector("[data-testid='accounts-table']")

    def create_account(self, name: str, account_type: str):
        self.page.click("[data-testid='create-account-btn']")
        self.page.fill("[name='name']", name)
        self.page.select_option("[name='account_type']", account_type)
        self.page.click("[type='submit']")
        self.page.wait_for_selector(f"text={name}")

    def get_account_names(self) -> list[str]:
        return self.page.locator("[data-testid='account-name']").all_text_contents()
```

```python
# e2e/tests/test_accounts.py
from e2e.pages.accounts import AccountsPage

def test_create_account(team_page, live_url):
    accounts = AccountsPage(team_page, live_url)
    accounts.goto()
    accounts.create_account("Office Supplies", "expense")
    assert "Office Supplies" in accounts.get_account_names()
```

---

## 7. `data-testid` Attribute Strategy

React and Django template components should expose stable `data-testid` attributes for Playwright to target. Avoid selecting by CSS class or text content (which breaks on copy changes).

**Convention:**
- `data-testid="create-account-btn"` — action buttons
- `data-testid="accounts-table"` — containers/lists
- `data-testid="account-row-{id}"` — per-item rows
- `data-testid="budget-target-input-{account_id}"` — form inputs in dynamic lists

These should be added to React components and Django templates incrementally as each test is written.

---

## 8. Test Data Strategy

**Use `factory_boy` factories** to create consistent, minimal test data:

```python
# e2e/factories.py
import factory
from apps.users.models import CustomUser
from apps.teams.models import Team
from apps.accounts.models import Account

class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CustomUser
    email = factory.Sequence(lambda n: f"user{n}@example.com")
    password = factory.PostGenerationMethodCall("set_password", "testpass123")

class TeamFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Team
    name = factory.Sequence(lambda n: f"Test Team {n}")

class AccountFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Account
    name = factory.Sequence(lambda n: f"Account {n}")
    team = factory.SubFactory(TeamFactory)
```

Each test should create its own isolated data (not rely on shared fixtures that bleed state between tests).

---

## 9. CI/CD Integration

Add a GitHub Actions job (or extend the existing workflow):

```yaml
# .github/workflows/e2e.yml
name: E2E Tests

on: [push, pull_request]

jobs:
  e2e:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:17
        env:
          POSTGRES_DB: koala_budget_e2e
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
        options: >-
          --health-cmd pg_isready
          --health-interval 2s
          --health-retries 10
      redis:
        image: redis
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 2s
          --health-retries 10

    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install dependencies
        run: |
          pip install uv
          uv sync --group e2e
          playwright install --with-deps chromium
      - name: Run E2E tests
        env:
          DATABASE_URL: postgresql://postgres:postgres@localhost/koala_budget_e2e
          REDIS_URL: redis://localhost:6379
          DJANGO_SETTINGS_MODULE: koala_budget.settings_e2e
        run: pytest e2e/ -v --screenshot on-failure --output e2e-results/
      - uses: actions/upload-artifact@v4
        if: failure()
        with:
          name: e2e-failure-screenshots
          path: e2e-results/
```

---

## 10. Implementation Phases

### Phase 1 — Foundation (do first)
1. Add `pytest-playwright` and `factory-boy` dependencies
2. Create `koala_budget/settings_e2e.py`
3. Create `e2e/conftest.py` with `live_server`, `authenticated_page`, and `team_page` fixtures
4. Create `e2e/factories.py` with User, Team, Account, and JournalEntry factories
5. Add `test-e2e` Makefile target
6. Write and verify one smoke test (login flow)

### Phase 2 — Core Financial Flows
7. Add `data-testid` attributes to accounts, transactions, and bank feed components
8. Implement `AccountsPage`, `TransactionsPage`, and `BankFeedPage` POMs
9. Write tests for accounts CRUD, manual journal entries, and CSV import

### Phase 3 — Budget and Reports
10. Add `data-testid` to budget and report components
11. Implement `BudgetPage` and `ReportsPage` POMs
12. Write budget target and report rendering tests

### Phase 4 — CI and Polish
13. Add GitHub Actions workflow
14. Add screenshot-on-failure artifact upload
15. Add `test-e2e` to the project's main CI pipeline

---

## 11. Running Tests Locally

```bash
# Run all E2E tests (headless)
make test-e2e

# Run with visible browser (for debugging)
make test-e2e ARGS="--headed"

# Run a single test file
make test-e2e ARGS="e2e/tests/test_auth.py"

# Run tests matching a keyword
make test-e2e ARGS="-k test_csv_upload"

# Pause on failure for debugging
make test-e2e ARGS="--headed --slowmo=500"
```

---

## 12. Key Decisions and Trade-offs

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Language | Python | Shares tooling/factories with Django unit tests |
| Runner | pytest-playwright | Django live_server fixture integration |
| Browser | Chromium only (initially) | Sufficient for CI speed; add Firefox/WebKit later |
| Test isolation | Per-test DB data via factories | No shared state bleed; tests run in any order |
| Selectors | `data-testid` attributes | Stable against UI/copy changes |
| Mocking | No external services (Plaid, Stripe) | Use `PLAID_ENV=sandbox`, disable Stripe in settings |
