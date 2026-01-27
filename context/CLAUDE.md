# Koala Budget - LLM Context Guide

This document provides comprehensive context for LLMs working on the Koala Budget codebase.

## Project Overview

Koala Budget is a **personal finance application for freelancers** built on the Pegasus SaaS framework. It features:

- **Double-entry bookkeeping** with a full chart of accounts
- **Bank feed integration** via Plaid API and CSV import
- **Monthly budgeting** with category tracking
- **Savings goals** with monthly allocation tracking
- **Multi-tenancy** via Teams (virtual workspaces)
- **AI/Chat features** for smart categorization

## Technology Stack

### Backend
- **Framework**: Django 6.0+ on Python 3.12
- **Package Manager**: uv (modern Python dependency manager)
- **Database**: PostgreSQL 17
- **REST API**: Django REST Framework with drf-spectacular (OpenAPI)
- **Authentication**: django-allauth (supports social auth, 2FA)
- **Task Queue**: Celery with Redis
- **Payments**: dj-stripe (Stripe integration)

### Frontend
- **Build Tool**: Vite 7.x
- **UI Frameworks**: React 19.x (primary), Alpine.js 3.x (simple interactions)
- **Styling**: Tailwind CSS 4.x with DaisyUI 5.x components
- **Data Tables**: Material UI React Table
- **Type System**: TypeScript 5.x
- **API Client**: Auto-generated from OpenAPI schema (`/api-client/`)

### Infrastructure
- **Containers**: Docker Compose for local development
- **Cache/Broker**: Redis
- **Deployment**: Digital Ocean App Platform

## Project Structure

```
koala_budget_pegasus/
├── koala_budget/              # Django project settings
│   ├── settings.py            # Main configuration
│   ├── urls.py                # Root URL routing
│   └── celery.py              # Celery configuration
│
├── apps/                      # Django applications
│   ├── accounts/              # Chart of accounts (Account, AccountGroup, Payee)
│   ├── journal/               # Double-entry ledger (JournalEntry, JournalLine)
│   ├── budget/                # Budgeting (Budget, Goal, GoalAllocation)
│   ├── bank_feed/             # Transaction imports (BankTransaction)
│   ├── plaid/                 # Plaid integration
│   ├── reports/               # Financial reporting
│   ├── chat/                  # AI chat interface
│   ├── api/                   # API auth and permissions
│   ├── teams/                 # Multi-tenancy
│   ├── users/                 # User management
│   └── subscriptions/         # Stripe billing
│
├── assets/javascript/         # React/Alpine components (bundled by Vite)
│   ├── bank_feed/             # Bank feed React components
│   ├── budget/                # Budget components
│   └── ...
│
├── frontend/                  # Standalone React SPA (auth flows only)
├── api-client/                # Generated TypeScript API client
├── templates/                 # Django templates
└── docs/                      # Documentation
```

## Key Documentation

- **[Architecture Overview](../docs/architecture.md)** - High-level system design
- **[Entity Relationship Diagram](../docs/erd.md)** - Complete database schema
- **[Data Model Guide](../docs/data-model.md)** - Detailed model documentation
- **[API Guide](../docs/api-guide.md)** - REST API reference
- **[Frontend Guide](../docs/frontend-guide.md)** - Frontend architecture
- **[Getting Started](../docs/getting-started.md)** - Developer onboarding

## Commands Reference

```bash
make                    # List all commands
make init               # First-time setup
make start              # Start all services
make stop               # Stop services
make ssh                # SSH into web container
make shell              # Django Python shell
make dbshell            # PostgreSQL shell
make migrations         # Create new migrations
make migrate            # Apply migrations
make test               # Run all tests
make test ARGS='path'   # Run specific tests
make ruff               # Format + lint Python
make npm-install        # Install JS packages
make npm-dev            # Run Vite dev server
make npm-build          # Build for production
make npm-type-check     # TypeScript check
```

## Core Domain Concepts

### Double-Entry Bookkeeping

Every financial transaction creates a balanced journal entry with equal debits and credits.

**Account Types** (by account_number range):
| Range | Type | Example |
|-------|------|---------|
| 1000s | Asset | Checking, Savings |
| 2000s | Liability | Credit Card |
| 3000s | Equity | Goals, Retained Earnings |
| 4000s | Income | Salary, Freelance |
| 5000s | Expense | Rent, Groceries |

**Journal Entry Structure:**
```python
JournalEntry (entry_date, description, payee, status, source)
    └── JournalLine (account, dr_amount OR cr_amount)
    └── JournalLine (account, dr_amount OR cr_amount)
    # sum(dr_amount) must equal sum(cr_amount)
```

### Bank Feed Workflow

```
External Source → BankTransaction (staging) → JournalEntry (ledger)
                  (journal_entry=null)        (created on categorize)
```

1. **Import**: Transactions from Plaid/CSV become BankTransaction records
2. **Categorize**: User assigns expense/income category
3. **Create Entry**: System creates balanced JournalEntry
4. **Link**: BankTransaction.journal_entry points to JournalEntry
5. **Reconcile**: User marks JournalLine as reconciled

**Amount convention**: Positive = outflow, Negative = inflow (Plaid standard)

### Multi-Tenancy

All financial data belongs to a **Team** (virtual workspace).

- Models extend `BaseTeamModel` which has `team` FK
- URLs follow pattern: `/a/{team_slug}/{app}/{path}/`
- Queries use `Model.for_team.all()` for automatic team filtering
- Views must include `team_slug` parameter

### Budget System

Monthly budgets link accounts to planned amounts:

```python
Budget(team, month, category, budget_amount)
    │
    └── JournalLine auto-links via account + month

actual = sum(linked JournalLines)
available = budget_amount - actual
```

### Goals System

Savings goals with monthly allocations:

```python
Goal(name, target_amount, target_date)
    │
    ├── Account (auto-created equity account in 3000s)
    └── GoalAllocation (monthly contributions)

progress = sum(allocations) / target_amount
```

## Code Patterns

### Django Models

```python
# Always extend BaseTeamModel for team-owned data
from apps.teams.models import BaseTeamModel

class MyModel(BaseTeamModel):
    # team FK inherited
    name = models.CharField(max_length=200)

    class Meta:
        unique_together = ["team", "name"]  # Common pattern
```

### Django Views (Team-Scoped)

```python
from apps.teams.decorators import login_and_team_required

@login_and_team_required
def my_view(request, team_slug):
    team = request.team  # Set by middleware
    items = MyModel.for_team.filter(team=team)
    return render(request, 'my_template.html', {'items': items})
```

### DRF ViewSets

```python
from rest_framework import viewsets
from apps.teams.permissions import TeamModelAccessPermissions

class MyViewSet(viewsets.ModelViewSet):
    serializer_class = MySerializer
    permission_classes = [TeamModelAccessPermissions]

    def get_queryset(self):
        return MyModel.for_team.filter(team=self.request.team)

    @action(detail=True, methods=['post'])
    def custom_action(self, request, pk=None):
        # Custom endpoint at /api/mymodel/{pk}/custom_action/
        instance = self.get_object()
        # ... do something
        return Response(status=status.HTTP_204_NO_CONTENT)
```

### React Components in Django Templates

```html
{# Template provides mount point and props #}
<div id="my-app"></div>
<script>
  window.MY_APP_PROPS = {
    apiUrl: "{% url 'myapp:api-list' team_slug=team.slug %}",
    initialData: {{ data_json|safe }}
  };
</script>
{% vite_react_refresh %}
{% vite_asset 'assets/javascript/myapp/index.tsx' %}
```

```typescript
// Component mounts itself
const container = document.getElementById('my-app');
if (container) {
  createRoot(container).render(<MyApp {...window.MY_APP_PROPS} />);
}
```

### API Client Usage

```typescript
import { MyApi } from 'api-client';
import { getApiConfiguration } from '../api/utils';

const api = new MyApi(getApiConfiguration());
const items = await api.myList();
await api.myCreate({ myRequest: { name: 'New Item' } });
```

## Coding Guidelines

### Python

- Follow PEP 8 with 120 character line limit
- Use double quotes for strings (ruff enforced)
- Use type hints in new code (not strictly enforced)
- Prefer function-based views unless using DRF
- Always validate user input server-side
- Use `gettext_lazy` for user-facing strings

### JavaScript/TypeScript

- Use ES6+ syntax
- 2 spaces for indentation
- Single quotes for strings
- Semicolons at end of statements
- Use functional components with hooks
- Use the generated OpenAPI client for API calls

### Django Templates

- 2 spaces for indentation
- Use `{% translate %}` or `{% blocktranslate trimmed %}` for text
- Load vite assets with `{% vite_asset %}`
- Use DaisyUI classes for styling
- Prefer Alpine.js for simple interactivity

### Styling

- Use DaisyUI components when available
- Fall back to Tailwind utilities
- Use semantic color names (primary, error, base-100)
- Avoid custom CSS when possible

## Important Constraints

1. **Never modify .env without confirmation**
2. **All team-owned models must extend BaseTeamModel**
3. **Journal entries must always balance (debits = credits)**
4. **URLs must include team_slug for team-scoped views**
5. **API changes require regenerating the TypeScript client**
6. **Avoid files over 200-300 lines - refactor when needed**
7. **Don't add mock data outside of tests**
8. **Keep changes minimal - only modify what's requested**

## Testing

```bash
make test                           # All tests
make test ARGS='apps.journal'       # Specific app
make test ARGS='apps.journal.tests.test_models::TestJournalEntry'  # Specific test
```

Test settings: `koala_budget.settings_test`

## Common Tasks

### Adding a New Model

1. Create model in appropriate app extending `BaseTeamModel`
2. Run `make migrations && make migrate`
3. Add serializer in `serializers.py`
4. Add viewset in `views.py`
5. Register routes in `urls.py`
6. Regenerate API client if needed

### Adding a New API Endpoint

1. Add method to existing viewset or create new viewset
2. Add serializers for request/response
3. Register in router
4. Regenerate TypeScript client
5. Update frontend to use new endpoint

### Adding Frontend Component

1. Create component in `assets/javascript/{app}/`
2. Add entry point to `vite.config.ts` if needed
3. Create/update Django template with mount point
4. Pass props via `window.{APP}_PROPS`

## Debugging Tips

- Django Debug Toolbar shows SQL queries in browser
- Use `print()` or `import pdb; pdb.set_trace()` for debugging
- Check Celery logs: `docker-compose logs -f celery`
- API docs at `/api/schema/swagger-ui/`
- Flower dashboard at http://localhost:5555

## File Locations Quick Reference

| What | Where |
|------|-------|
| Django settings | `koala_budget/settings.py` |
| URL routing | `koala_budget/urls.py`, `apps/*/urls.py` |
| Models | `apps/*/models.py` |
| Views | `apps/*/views.py` |
| Serializers | `apps/*/serializers.py` |
| Templates | `templates/*/` |
| React components | `assets/javascript/*/` |
| Styles | `assets/styles/` |
| API client | `api-client/` |
| Tests | `apps/*/tests/` |
| Migrations | `apps/*/migrations/` |
