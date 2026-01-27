# Data Model Guide

This document provides detailed documentation for each model in Koala Budget, including field descriptions, relationships, and usage patterns.

## Base Classes

### BaseModel (`apps/utils/models.py`)

Abstract base class providing common fields:

```python
class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)

    def archive(self)    # Set is_archived=True, archived_at=now
    def restore(self)    # Set is_archived=False, archived_at=None

    @property
    def is_active(self)  # Returns not is_archived
```

### BaseTeamModel (`apps/teams/models.py`)

Extends BaseModel with team scoping:

```python
class BaseTeamModel(BaseModel):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)

    objects = models.Manager()
    for_team = TeamScopedManager()  # Auto-filters by current team context
```

**Usage:**
```python
# Manual team filtering
Budget.objects.filter(team=team)

# Automatic team filtering (uses context)
Budget.for_team.all()
```

---

## User & Team Models

### CustomUser (`apps/users/models.py`)

Extended Django user model.

| Field | Type | Description |
|-------|------|-------------|
| `email` | EmailField | Primary identifier (username) |
| `avatar` | FileField | Profile picture |
| `language` | CharField | User's preferred language |
| `timezone` | CharField | User's timezone |

**Properties:**
- `avatar_url` - URL to avatar or default
- `gravatar_id` - MD5 hash for Gravatar
- `has_verified_email` - Whether email is verified

### Team (`apps/teams/models.py`)

Multi-tenant container for all financial data.

| Field | Type | Description |
|-------|------|-------------|
| `name` | CharField | Display name |
| `slug` | SlugField | URL-safe identifier (unique) |
| `members` | M2M(CustomUser) | Team members via Membership |
| `subscription` | FK(djstripe.Subscription) | Stripe subscription (nullable) |
| `customer` | FK(djstripe.Customer) | Stripe customer (nullable) |

### Membership (`apps/teams/models.py`)

Links users to teams with roles.

| Field | Type | Description |
|-------|------|-------------|
| `team` | FK(Team) | The team |
| `user` | FK(CustomUser) | The member |
| `role` | CharField | "admin" or "member" |

**Unique constraint:** (team, user)

**Role permissions:**
- `member` - Read access to team data
- `admin` - Full read/write access

---

## Chart of Accounts

### AccountGroup (`apps/accounts/models.py`)

Categories for organizing accounts.

| Field | Type | Description |
|-------|------|-------------|
| `name` | CharField | Group name (e.g., "Bank Accounts") |
| `account_type` | CharField | One of: asset, liability, equity, income, expense |
| `description` | TextField | Optional description |

**Unique constraint:** (team, name)

**Account types:**
```python
ACCOUNT_TYPE_ASSET = "asset"      # Things you own
ACCOUNT_TYPE_LIABILITY = "liability"  # Things you owe
ACCOUNT_TYPE_EQUITY = "equity"    # Net worth / goals
ACCOUNT_TYPE_INCOME = "income"    # Money coming in
ACCOUNT_TYPE_EXPENSE = "expense"  # Money going out
```

### Account (`apps/accounts/models.py`)

Individual accounts in the chart of accounts.

| Field | Type | Description |
|-------|------|-------------|
| `name` | CharField | Account name (e.g., "Checking") |
| `account_number` | CharField | Accounting number (e.g., "1000") |
| `account_group` | FK(AccountGroup) | Parent group |
| `has_feed` | BooleanField | Whether this account has bank feed |

**Unique constraint:** (team, account_number)

**Account number conventions:**
| Range | Type | Example |
|-------|------|---------|
| 1000-1999 | Asset | 1000 = Checking, 1001 = Savings |
| 2000-2999 | Liability | 2000 = Credit Card |
| 3000-3999 | Equity | 3000+ = Goal accounts |
| 4000-4999 | Income | 4000 = Salary |
| 5000-5999 | Expense | 5000 = Rent, 5001 = Groceries |

**Properties:**
- `balance` - Calculated from sum of journal lines (debits - credits)

### Payee (`apps/accounts/models.py`)

Merchants/vendors for transaction categorization.

| Field | Type | Description |
|-------|------|-------------|
| `name` | CharField | Payee name |

**Unique constraint:** (team, name)

---

## Journal (Double-Entry Ledger)

### JournalEntry (`apps/journal/models.py`)

A complete financial transaction with balanced debits and credits.

| Field | Type | Description |
|-------|------|-------------|
| `entry_date` | DateField | Transaction date |
| `payee` | FK(Payee) | Optional payee |
| `description` | TextField | Transaction description |
| `source` | CharField | How entry was created |
| `status` | CharField | Entry status |

**Source choices:**
```python
SOURCE_MANUAL = "manual"       # User created
SOURCE_IMPORT = "import"       # CSV import
SOURCE_BANK_MATCH = "bank_match"  # From bank feed
SOURCE_RECURRING = "recurring"  # Auto-generated
```

**Status choices:**
```python
STATUS_DRAFT = "draft"    # Not finalized
STATUS_POSTED = "posted"  # Finalized
STATUS_VOID = "void"      # Cancelled
```

**Properties:**
- `total_debits` - Sum of all line dr_amounts
- `total_credits` - Sum of all line cr_amounts
- `is_balanced` - total_debits == total_credits

**Validation:**
- Entry must balance (debits = credits)

### JournalLine (`apps/journal/models.py`)

Individual debit or credit line within an entry.

| Field | Type | Description |
|-------|------|-------------|
| `journal_entry` | FK(JournalEntry) | Parent entry |
| `account` | FK(Account) | Affected account |
| `dr_amount` | DecimalField | Debit amount (default 0) |
| `cr_amount` | DecimalField | Credit amount (default 0) |
| `is_cleared` | BooleanField | Bank cleared |
| `is_reconciled` | BooleanField | User reconciled |
| `is_archived` | BooleanField | Archived from view |
| `budget` | FK(Budget) | Auto-linked budget (editable=False) |

**Properties:**
- `amount` - The non-zero amount (dr or cr)

**Validation:**
- Exactly one of dr_amount or cr_amount must be non-zero
- Neither can be negative

**Auto-linking to Budget:**
On save, the `budget` field is automatically calculated based on:
- `account` matches `Budget.category`
- `journal_entry.entry_date` month matches `Budget.month`

---

## Budgeting

### Budget (`apps/budget/models.py`)

Monthly budget for an income or expense category.

| Field | Type | Description |
|-------|------|-------------|
| `month` | DateField | First day of month |
| `category` | FK(Account) | Income/expense account |
| `budget_amount` | DecimalField | Planned amount |

**Unique constraint:** (team, month, category)

**Calculated values (via queries):**
- `actual` - Sum of linked JournalLine amounts
- `available` - budget_amount - actual

### Goal (`apps/budget/models.py`)

Savings goal with target amount and date.

| Field | Type | Description |
|-------|------|-------------|
| `name` | CharField | Goal name |
| `description` | TextField | Optional description |
| `target_amount` | DecimalField | Target savings |
| `target_date` | DateField | Target date (nullable) |
| `account` | OneToOne(Account) | Auto-created equity account |
| `is_complete` | BooleanField | Goal achieved |
| `is_archived` | BooleanField | Hidden from view |
| `order` | IntegerField | Display order |

**Unique constraint:** (team, name)

**Auto-created account:**
On first save, creates an Account:
- Name: "Goal: {goal.name}"
- Account number: Next available in 3000s
- Account group: "Goals" (equity type)

**Properties:**
- `progress_percentage` - (total_saved / target_amount) * 100

**QuerySet methods:**
```python
Goal.objects.active()  # Non-archived, non-complete
Goal.objects.with_progress(month)  # Annotates saved_previous, saved_this_month, total_saved, remaining
```

### GoalAllocation (`apps/budget/models.py`)

Monthly contribution toward a goal.

| Field | Type | Description |
|-------|------|-------------|
| `goal` | FK(Goal) | Parent goal |
| `month` | DateField | Month of allocation |
| `amount` | DecimalField | Amount allocated |
| `notes` | TextField | Optional notes |

**Unique constraint:** (team, goal, month)

**Auto-normalization:**
On save, `month` is normalized to first day of month.

---

## Bank Feed

### BankTransaction (`apps/bank_feed/models.py`)

Staging table for imported transactions.

| Field | Type | Description |
|-------|------|-------------|
| `account` | FK(Account) | Bank account |
| `journal_entry` | FK(JournalEntry) | Linked entry (nullable) |
| `amount` | DecimalField | Transaction amount |
| `posted_date` | DateField | Transaction date |
| `description` | CharField | Description |
| `merchant_name` | CharField | Merchant (nullable) |
| `source` | CharField | Import source |
| `raw` | JSONField | Original source data |

**Source choices:**
```python
SOURCE_PLAID = "plaid"    # Plaid API
SOURCE_CSV = "csv"        # CSV upload
SOURCE_MANUAL = "manual"  # User entered
SOURCE_SYSTEM = "system"  # System generated
```

**Amount convention:**
- Positive = outflow (expense)
- Negative = inflow (income)
- This follows Plaid's convention

**Properties:**
- `is_categorized` - journal_entry is not None

**Workflow:**
1. Transaction imported (journal_entry = null)
2. User categorizes → creates JournalEntry
3. journal_entry linked to BankTransaction
4. User reconciles → is_reconciled = True on JournalLine

---

## Plaid Integration

### PlaidItem (`apps/plaid/models.py`)

Connection to a financial institution via Plaid.

| Field | Type | Description |
|-------|------|-------------|
| `plaid_item_id` | CharField | Plaid's identifier (unique) |
| `access_token` | CharField | API access token |
| `institution_name` | CharField | Bank name |
| `cursor` | CharField | Sync cursor for incremental updates |

### PlaidAccount (`apps/plaid/models.py`)

Individual account at a Plaid-connected institution.

| Field | Type | Description |
|-------|------|-------------|
| `plaid_account_id` | CharField | Plaid's identifier (unique) |
| `item` | FK(PlaidItem) | Parent item |
| `account` | FK(Account) | Mapped ledger account (nullable) |
| `name` | CharField | Account name from Plaid |
| `mask` | CharField | Last 4 digits |
| `subtype` | CharField | Account subtype |
| `type` | CharField | Account type |

**Properties:**
- `is_mapped` - account is not None

**Methods:**
- `can_sync_transactions()` - Returns is_mapped

### PlaidTransaction (`apps/plaid/models.py`)

Extended transaction data from Plaid.

| Field | Type | Description |
|-------|------|-------------|
| `plaid_transaction_id` | CharField | Plaid's identifier (unique) |
| `bank_transaction` | OneToOne(BankTransaction) | Base transaction |
| `plaid_account` | FK(PlaidAccount) | Source account |
| `iso_currency_code` | CharField | Currency code |
| `authorized_date` | DateField | Authorization date |
| `pending` | BooleanField | Pending status |
| `pending_transaction_id` | CharField | If pending replaces another |
| `personal_finance_category` | CharField | Plaid's category |
| `category_confidence` | CharField | Category confidence |
| `payment_channel` | CharField | Payment method |
| `transaction_type` | CharField | Transaction type |
| `location` | JSONField | Location data |
| `merchant_metadata` | JSONField | Merchant details |

---

## Chat / AI

### Chat (`apps/chat/models.py`)

A conversation session.

| Field | Type | Description |
|-------|------|-------------|
| `user` | FK(CustomUser) | Owner (nullable) |
| `chat_type` | CharField | "chat" or "agent" |
| `agent_type` | CharField | Agent type if applicable |
| `name` | CharField | Chat name |

### ChatMessage (`apps/chat/models.py`)

Individual message in a chat.

| Field | Type | Description |
|-------|------|-------------|
| `chat` | FK(Chat) | Parent chat |
| `message_type` | CharField | HUMAN, AI, or SYSTEM |
| `content` | TextField | Message content |

**Properties:**
- `is_ai_message`
- `is_human_message`

**Methods:**
- `to_openai_dict()` - Convert to OpenAI format
- `get_openai_role()` - Get role for API

---

## Common Query Patterns

### Get account balance
```python
account = Account.objects.get(pk=1)
balance = account.balance  # Calculated property
```

### Get budget actuals
```python
budget = Budget.objects.get(month=date(2024, 1, 1), category=account)
actual = budget.journal_lines.aggregate(
    total=Sum(F('dr_amount') - F('cr_amount'))
)['total']
```

### Get uncategorized bank transactions
```python
BankTransaction.objects.filter(
    team=team,
    journal_entry__isnull=True
)
```

### Get goal progress
```python
goals = Goal.objects.filter(team=team).with_progress(month=date(2024, 1, 1))
for goal in goals:
    print(f"{goal.name}: {goal.total_saved} / {goal.target_amount}")
```

### Get transactions for reconciliation
```python
JournalLine.objects.filter(
    team=team,
    account=bank_account,
    is_reconciled=False,
    is_cleared=True
)
```
