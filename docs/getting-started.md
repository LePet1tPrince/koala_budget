# Getting Started

This guide helps new developers get up and running with Koala Budget.

## Prerequisites

- Docker and Docker Compose
- Node.js 18+ (for frontend tooling)
- Git

## Quick Start

### 1. Clone and Initialize

```bash
git clone <repository-url>
cd koala_budget_pegasus

# Initialize project (creates containers, runs migrations, installs deps)
make init
```

### 2. Start the Application

```bash
# Start all services with logs
make start

# Or start in background
make start-bg
```

### 3. Access the App

- **Application**: http://localhost:8000
- **Vite Dev Server**: http://localhost:5173 (proxied through Django)

### 4. Create a User

```bash
# SSH into container
make ssh

# Create superuser
python manage.py createsuperuser
```

## Services Architecture

When you run `make start`, these services are launched:

| Service | Port | Purpose |
|---------|------|---------|
| web | 8000 | Django application |
| db | 5432 | PostgreSQL database |
| redis | 6379 | Cache and message broker |
| vite | 5173 | Frontend dev server (HMR) |
| celery | - | Background task worker |
| celery-beat | - | Scheduled task runner |
| flower | 5555 | Celery monitoring UI |

## Common Development Commands

### Container Access

```bash
make ssh          # SSH into web container
make shell        # Django Python shell
make dbshell      # PostgreSQL shell
```

### Database

```bash
make migrations   # Create new migrations
make migrate      # Apply migrations
```

### Testing

```bash
make test                              # Run all tests
make test ARGS='apps.journal.tests'    # Run specific app tests
make test ARGS='--keepdb'              # Keep test database
```

### Code Quality

```bash
make ruff         # Format + lint Python code
make ruff-format  # Format only
make ruff-lint    # Lint only
```

### Frontend

```bash
make npm-install              # Install all packages
make npm-install package-name # Install specific package
make npm-dev                  # Run Vite dev server
make npm-build                # Build for production
make npm-type-check           # TypeScript check
```

### Django Management

```bash
make manage ARGS='command'    # Run any Django command
make manage ARGS='shell_plus' # Enhanced shell
```

## Project Structure Overview

```
koala_budget_pegasus/
├── apps/                  # Django applications
│   ├── accounts/          # Chart of accounts
│   ├── journal/           # Double-entry ledger
│   ├── budget/            # Budgeting & goals
│   ├── bank_feed/         # Bank transaction imports
│   ├── plaid/             # Plaid integration
│   ├── reports/           # Financial reports
│   ├── teams/             # Multi-tenancy
│   └── ...
│
├── assets/                # Frontend source
│   ├── javascript/        # React/Alpine components
│   └── styles/            # Tailwind CSS
│
├── templates/             # Django templates
├── api-client/            # Generated TS API client
├── koala_budget/          # Django settings
└── docs/                  # Documentation
```

## Development Workflow

### 1. Making Backend Changes

```bash
# Edit model
vim apps/journal/models.py

# Create migration
make migrations

# Apply migration
make migrate

# Run tests
make test ARGS='apps.journal.tests'
```

### 2. Making Frontend Changes

```bash
# Edit component (Vite HMR auto-reloads)
vim assets/javascript/bank_feed/BankFeedLine.tsx

# Check types
make npm-type-check
```

### 3. Making API Changes

```bash
# Edit view/serializer
vim apps/bank_feed/views.py
vim apps/bank_feed/serializers.py

# Regenerate OpenAPI schema
python manage.py spectacular --file schema.yaml

# Regenerate TypeScript client
npx openapi-generator-cli generate \
  -i schema.yaml \
  -g typescript-fetch \
  -o api-client

# Update frontend to use new API
vim assets/javascript/bank_feed/BankFeedLine.tsx
```

### 4. Creating a New Feature

1. **Design**: Plan models, API, and UI
2. **Models**: Add Django models in appropriate app
3. **Migrations**: `make migrations && make migrate`
4. **API**: Add serializers and viewset
5. **Frontend**: Create React components
6. **Template**: Add Django template with mount point
7. **Test**: Write and run tests

## Key Concepts

### Multi-Tenancy

All financial data belongs to a Team:

```python
# Models extend BaseTeamModel
class Budget(BaseTeamModel):
    # Automatically has team FK
    ...

# Views use team from URL
def budget_list(request, team_slug):
    team = get_object_or_404(Team, slug=team_slug)
    budgets = Budget.for_team.filter(team=team)
```

URL pattern: `/a/{team_slug}/{app}/{path}/`

### Double-Entry Bookkeeping

Every transaction creates a balanced journal entry:

```python
# Expense: Pay $50 for office supplies
entry = JournalEntry.objects.create(
    team=team,
    entry_date=date.today(),
    description="Office supplies"
)
# Debit expense account (increase)
JournalLine.objects.create(
    journal_entry=entry,
    account=expense_account,  # 5001 Office Supplies
    dr_amount=Decimal("50.00")
)
# Credit bank account (decrease)
JournalLine.objects.create(
    journal_entry=entry,
    account=bank_account,  # 1000 Checking
    cr_amount=Decimal("50.00")
)
```

### Bank Feed Flow

```
Import → Stage → Categorize → Create Entry → Reconcile

BankTransaction ──────────────────► JournalEntry
(journal_entry=null)               (created on categorize)
      │
      └── is_categorized = False   → is_categorized = True
```

## Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
# Required
SECRET_KEY=your-secret-key
DATABASE_URL=postgres://user:pass@db:5432/dbname

# Plaid (for bank integration)
PLAID_CLIENT_ID=...
PLAID_SECRET=...
PLAID_ENV=sandbox

# Stripe (for subscriptions)
STRIPE_SECRET_KEY=...
STRIPE_PUBLISHABLE_KEY=...
STRIPE_WEBHOOK_SECRET=...

# AI/Chat
ANTHROPIC_API_KEY=...

# Email
MAILGUN_API_KEY=...
MAILGUN_SENDER_DOMAIN=...
```

## Debugging

### Django Debug Toolbar

Enabled in development. Shows SQL queries, templates, etc.

### Viewing Logs

```bash
# All services
make start  # Shows combined logs

# Specific service
docker-compose logs -f web
docker-compose logs -f celery
```

### Database Queries

```python
# In shell
from django.db import connection
print(connection.queries)

# Or use Django Debug Toolbar in browser
```

### API Debugging

- Swagger UI: http://localhost:8000/api/schema/swagger-ui/
- ReDoc: http://localhost:8000/api/schema/redoc/

## Common Issues

### Migrations Conflict

```bash
# If migrations conflict
make ssh
python manage.py migrate --merge
```

### Frontend Not Updating

```bash
# Clear Vite cache
rm -rf node_modules/.vite
make npm-dev
```

### Database Connection Issues

```bash
# Restart database
docker-compose restart db
make migrate
```

### Permission Denied

```bash
# Reset container permissions
docker-compose down
docker-compose up -d
```

## Next Steps

1. Read the [Architecture Overview](./architecture.md)
2. Study the [ERD](./erd.md) to understand the data model
3. Review the [API Guide](./api-guide.md) for endpoint documentation
4. Check the [Frontend Guide](./frontend-guide.md) for UI development
5. Explore existing code in `apps/` to see patterns

## Getting Help

- Check existing code for patterns
- Read Django REST Framework docs
- Review React and MaterialTable documentation
- Look at the generated API client for type definitions
