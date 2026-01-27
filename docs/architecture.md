# Koala Budget Architecture

This document provides a high-level overview of the Koala Budget application architecture.

## Overview

Koala Budget is a personal finance application for freelancers built on the **Pegasus SaaS framework**. It implements double-entry bookkeeping with bank feed integration, budgeting, and savings goals.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CLIENT LAYER                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │   Django     │  │    React     │  │   Alpine.js  │  │  Standalone  │    │
│  │  Templates   │  │  Components  │  │  Interactiv. │  │  React App   │    │
│  │  (Server)    │  │ (assets/js/) │  │              │  │ (/frontend/) │    │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘    │
│                              │                                               │
│                              ▼                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Generated TypeScript API Client                   │   │
│  │                         (/api-client/)                               │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              API LAYER                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │              Django REST Framework (ViewSets + Routers)              │   │
│  │                   /a/{team_slug}/*/api/                              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                      │
│  │ Serializers  │  │ Permissions  │  │   OpenAPI    │                      │
│  │              │  │ (Team-based) │  │   Schema     │                      │
│  └──────────────┘  └──────────────┘  └──────────────┘                      │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            SERVICE LAYER                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │  CSV Upload  │  │    Plaid     │  │   Reports    │  │   Budget     │    │
│  │   Service    │  │   Service    │  │   Service    │  │   Service    │    │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                             MODEL LAYER                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        Django ORM Models                             │   │
│  │         (All team-scoped via BaseTeamModel inheritance)              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          INFRASTRUCTURE                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │  PostgreSQL  │  │    Redis     │  │    Celery    │  │    Plaid     │    │
│  │   Database   │  │ Cache/Broker │  │    Worker    │  │     API      │    │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Technology Stack

### Backend
| Component | Technology | Version |
|-----------|------------|---------|
| Framework | Django | 6.0+ |
| Python | - | 3.12 |
| Package Manager | uv | latest |
| REST API | Django REST Framework | - |
| API Documentation | drf-spectacular (OpenAPI) | - |
| Authentication | django-allauth | - |
| Task Queue | Celery + Redis | - |
| Database | PostgreSQL | 17 |
| Payments | dj-stripe (Stripe) | - |

### Frontend
| Component | Technology | Version |
|-----------|------------|---------|
| Build Tool | Vite | 7.x |
| Primary Framework | React | 19.x |
| Secondary | Alpine.js | 3.x |
| Styling | Tailwind CSS + DaisyUI | 4.x / 5.x |
| Data Tables | Material Tables from Material UI |
| Type System | TypeScript | 5.x |

## Project Structure

```
koala_budget_pegasus/
├── koala_budget/              # Django project configuration
│   ├── settings.py            # Main settings
│   ├── urls.py                # Root URL routing
│   └── celery.py              # Celery configuration
│
├── apps/                      # Django applications
│   ├── accounts/              # Chart of accounts (Account, AccountGroup, Payee)
│   ├── journal/               # Double-entry bookkeeping (JournalEntry, JournalLine)
│   ├── budget/                # Budgeting system (Budget, Goal, GoalAllocation)
│   ├── bank_feed/             # Transaction imports (BankTransaction)
│   ├── plaid/                 # Plaid integration (PlaidItem, PlaidAccount, PlaidTransaction)
│   ├── reports/               # Financial reporting
│   ├── chat/                  # AI chat interface
│   ├── ai/                    # AI rules and agents
│   ├── api/                   # API authentication and permissions
│   ├── teams/                 # Multi-tenancy (Team, Membership)
│   ├── users/                 # User management (CustomUser)
│   ├── subscriptions/         # Stripe subscriptions
│   └── ...                    # Other Pegasus apps
│
├── assets/                    # Frontend source (bundled by Vite)
│   ├── javascript/            # React/Alpine components
│   │   ├── bank_feed/         # Bank feed React components
│   │   ├── budget/            # Budget module JS
│   │   └── ...
│   └── styles/                # Tailwind CSS
│
├── frontend/                  # Standalone React SPA (auth flows)
│   └── src/
│       ├── pages/             # Auth pages (Login, Signup, etc.)
│       └── allauth_auth/      # Auth context and hooks
│
├── api-client/                # Auto-generated TypeScript API client
│   ├── apis/                  # API classes
│   └── models/                # Type definitions
│
├── templates/                 # Django templates
├── static/                    # Built frontend assets
└── docs/                      # Documentation
```

## Core Domain Concepts

### Double-Entry Bookkeeping

The application uses standard double-entry accounting principles:

1. **Chart of Accounts**: Organized by type (Asset, Liability, Income, Expense, Equity)
2. **Journal Entries**: Every transaction has balanced debits and credits
3. **Account Balance**: Calculated from sum of journal lines (debits - credits)

```
Account Types (AccountGroup.account_type):
├── asset      # Bank accounts, receivables (1000s)
├── liability  # Credit cards, loans (2000s)
├── equity     # Goals, retained earnings (3000s)
├── income     # Revenue categories (4000s)
└── expense    # Expense categories (5000s)
```

### Bank Feed Workflow

Transactions flow from external sources to the ledger:

```
External Source          Staging              Ledger
┌──────────┐        ┌──────────────┐     ┌──────────────┐
│  Plaid   │───────▶│              │     │              │
└──────────┘        │              │     │              │
┌──────────┐        │    Bank      │────▶│   Journal    │
│   CSV    │───────▶│ Transaction  │     │    Entry     │
└──────────┘        │              │     │              │
┌──────────┐        │              │     │              │
│  Manual  │───────▶│              │     │              │
└──────────┘        └──────────────┘     └──────────────┘
                    (Uncategorized)       (Categorized)
```

1. **Import**: Transactions enter as `BankTransaction` records
2. **Categorize**: User assigns expense/income category
3. **Create Entry**: System creates `JournalEntry` with balanced lines
4. **Reconcile**: User marks transactions as reconciled

### Multi-Tenancy Model

All data is scoped to a **Team** (virtual tenant):

```python
# Every team-owned model extends BaseTeamModel
class Budget(BaseTeamModel):
    team = models.ForeignKey(Team, ...)  # Inherited from BaseTeamModel
    # ...

# Queries automatically filter by team context
Budget.for_team.all()  # Uses TeamScopedManager
```

**URL Pattern**: `/a/{team_slug}/{app}/{path}/`

### Budget System

Monthly budgets link accounts to planned amounts:

```
Budget(month, category) ←── JournalLine (auto-linked by account + month)
         │
         ▼
    Actual = Sum of linked JournalLines
```

### Goals System

Savings goals with monthly allocations:

```
Goal ←──────────── GoalAllocation (monthly contributions)
  │
  └── Account (auto-created equity account, 3000s range)
```

## Key Architectural Patterns

### Team-Based Authorization

```python
# apps/teams/permissions.py
class TeamModelAccessPermissions(BasePermission):
    # SAFE_METHODS: check is_member(user, team)
    # Write methods: check is_admin(user, team)
```

### Service Layer

Complex business logic is encapsulated in service modules:

```python
# apps/bank_feed/services/csv_upload.py
def parse_file(file) -> ParseResult
def preview_transactions(file, mapping) -> PreviewResult
def create_transactions(file, mapping, account) -> List[BankTransaction]
```

### Serializer Adapters

Transform models for different presentation needs:

```python
# apps/bank_feed/serializers.py
def bank_transaction_to_feed_row(bt: BankTransaction) -> dict
def journal_line_to_feed_row(jl: JournalLine) -> dict
```

### Generated API Client

TypeScript client auto-generated from OpenAPI schema:

```typescript
// Frontend usage
import { BankFeedApi } from 'api-client';

const client = new BankFeedApi(getApiConfiguration());
await client.feedCategorize({ id, categoryId });
```

## Data Flow Example: Categorizing a Transaction

```
1. User clicks "Categorize" on BankTransaction #123
                    │
                    ▼
2. POST /a/acme/bankfeed/api/feed/categorize/
   Body: { id: 123, category_id: 5001 }
                    │
                    ▼
3. BankFeedViewSet.categorize()
   - Validate request
   - Get BankTransaction (team-scoped)
                    │
                    ▼
4. _create_journal_from_bank_transaction()
   - Create JournalEntry
   - Create JournalLine (debit expense account)
   - Create JournalLine (credit bank account)
   - Link BankTransaction.journal_entry = JournalEntry
                    │
                    ▼
5. Return Response(status=204)
```

## External Integrations

### Plaid

- **Link Widget**: React component for account linking
- **Sync**: Celery task fetches new transactions
- **Models**: PlaidItem → PlaidAccount → PlaidTransaction → BankTransaction

### Stripe

- **Subscriptions**: Team-level billing via dj-stripe
- **Webhooks**: Handle subscription events
- **Models**: Team.subscription, Team.customer

### AI/Chat

- **Framework**: pydantic-ai with LiteLLM
- **Models**: Chat, ChatMessage
- **Integration**: Claude/GPT for smart categorization suggestions

## Development Workflow

```bash
# Start all services
make start

# Access the app
http://localhost:8000

# SSH into container for Django commands
make ssh

# Run tests
make test

# Format and lint
make ruff
```

## Related Documentation

- [Entity Relationship Diagram](./erd.md) - Database schema visualization
- [Data Model Guide](./data-model.md) - Detailed model documentation
- [API Guide](./api-guide.md) - REST API architecture
- [Frontend Guide](./frontend-guide.md) - Frontend architecture
- [Getting Started](./getting-started.md) - Developer onboarding
