# Entity Relationship Diagram

This document contains the complete database schema for Koala Budget.

## Overview

The data model is organized around these core concepts:

1. **Multi-tenancy**: Team owns all financial data
2. **Chart of Accounts**: AccountGroup → Account hierarchy
3. **Double-Entry Ledger**: JournalEntry → JournalLine
4. **Bank Integration**: PlaidItem → PlaidAccount → BankTransaction
5. **Budgeting**: Budget (monthly) and Goal (savings targets)

## Complete ERD

```mermaid
erDiagram
    %% ============================================
    %% MULTI-TENANCY
    %% ============================================
    Team ||--o{ Membership : "has members"
    Team ||--o{ Invitation : "has invitations"
    CustomUser ||--o{ Membership : "belongs to teams"

    Team {
        int id PK
        string name
        string slug UK
        datetime created_at
        datetime updated_at
        int subscription FK "djstripe.subscription nullable"
        int customer FK "djstripe.Customer nullable"
    }

    Membership {
        int id PK
        int team_id FK
        int user_id FK
        string role "admin, member"
        datetime created_at
    }

    CustomUser {
        int id PK
        string email UK
        string avatar
        string language
        string timezone
    }

    Invitation {
        uuid id PK
        int team_id FK
        string email
        string role
        int invited_by_id FK
        bool is_accepted
        int accepted_by_id FK "nullable"
    }

    %% ============================================
    %% CHART OF ACCOUNTS
    %% ============================================
    Team ||--o{ AccountGroup : "owns"
    Team ||--o{ Account : "owns"
    Team ||--o{ Payee : "owns"
    AccountGroup ||--o{ Account : "contains"

    AccountGroup {
        int id PK
        int team_id FK
        string name
        string account_type "asset, liability, equity, income, expense"
        string description
    }

    Account {
        int id PK
        int team_id FK
        string name
        string account_number "1000s asset, 2000s liability, etc"
        int account_group_id FK
        bool has_feed "bank account with feed"
        prop balance "calculated from journal lines"
    }

    Payee {
        int id PK
        int team_id FK
        string name UK "unique per team"
    }

    %% ============================================
    %% DOUBLE-ENTRY LEDGER
    %% ============================================
    Team ||--o{ JournalEntry : "owns"
    Payee ||--o{ JournalEntry : "optional payee"
    JournalEntry ||--|{ JournalLine : "contains lines"
    Account ||--o{ JournalLine : "account movements"
    Budget ||--o{ JournalLine : "auto-linked"

    JournalEntry {
        int id PK
        int team_id FK
        date entry_date
        int payee_id FK "nullable"
        string description
        string source "manual, import, bank_match, recurring"
        string status "draft, posted, void"
        datetime created_at
        datetime updated_at
        prop total_debits "calculated"
        prop total_credits "calculated"
        prop is_balanced "debits == credits"
    }

    JournalLine {
        int id PK
        int team_id FK
        int journal_entry_id FK
        int account_id FK
        decimal dr_amount "debit amount"
        decimal cr_amount "credit amount"
        bool is_cleared "bank cleared"
        bool is_reconciled "user reconciled"
        bool is_archived
        int budget_id FK "auto-linked by account + month"
        prop amount "non-zero of dr/cr"
    }

    %% ============================================
    %% BUDGETING
    %% ============================================
    Team ||--o{ Budget : "owns"
    Account ||--o{ Budget : "category budgets"

    Budget {
        int id PK
        int team_id FK
        date month "first day of month"
        int category_id FK "Account (income/expense)"
        decimal budget_amount
        prop actual "sum of linked journal lines"
        prop available "budget - actual"
    }

    %% ============================================
    %% GOALS (Savings Targets)
    %% ============================================
    Team ||--o{ Goal : "owns"
    Goal ||--|| Account : "backing equity account"
    Goal ||--o{ GoalAllocation : "monthly allocations"

    Goal {
        int id PK
        int team_id FK
        string name UK "unique per team"
        string description
        decimal target_amount
        date target_date "nullable"
        int account_id FK "auto-created equity account"
        bool is_complete
        bool is_archived
        int order "display order"
        prop progress_percentage "calculated"
    }

    GoalAllocation {
        int id PK
        int team_id FK
        int goal_id FK
        date month "first day of month"
        decimal amount
        string notes
    }

    %% ============================================
    %% BANK FEED (Transaction Import)
    %% ============================================
    Team ||--o{ BankTransaction : "owns"
    Account ||--o{ BankTransaction : "bank account"
    BankTransaction }o--|| JournalEntry : "linked when categorized"

    BankTransaction {
        int id PK
        int team_id FK
        int account_id FK "bank account"
        int journal_entry_id FK "nullable until categorized"
        decimal amount "positive=outflow, negative=inflow"
        date posted_date
        string description
        string merchant_name "nullable"
        string source "plaid, csv, manual, system"
        json raw "original source data"
        prop is_categorized "journal_entry not null"
    }

    %% ============================================
    %% PLAID INTEGRATION
    %% ============================================
    Team ||--o{ PlaidItem : "owns"
    PlaidItem ||--o{ PlaidAccount : "contains accounts"
    PlaidAccount }o--|| Account : "maps to ledger account"
    PlaidAccount ||--o{ PlaidTransaction : "contains transactions"
    PlaidTransaction ||--|| BankTransaction : "extends"

    PlaidItem {
        int id PK
        int team_id FK
        string plaid_item_id UK "Plaid identifier"
        string access_token "API token"
        string institution_name
        string cursor "for incremental sync"
    }

    PlaidAccount {
        int id PK
        int team_id FK
        string plaid_account_id UK
        int item_id FK "PlaidItem"
        int account_id FK "nullable - mapped ledger account"
        string name
        string mask "last 4 digits"
        string subtype
        string type
        prop is_mapped "account not null"
    }

    PlaidTransaction {
        int id PK
        int team_id FK
        string plaid_transaction_id UK
        int bank_transaction_id FK "OneToOne"
        int plaid_account_id FK
        string iso_currency_code
        date authorized_date "nullable"
        bool pending
        string pending_transaction_id "nullable"
        string personal_finance_category
        string category_confidence
        string payment_channel
        string transaction_type
        json location
        json merchant_metadata
    }

    %% ============================================
    %% AI/CHAT
    %% ============================================
    CustomUser ||--o{ Chat : "owns"
    Chat ||--o{ ChatMessage : "contains"

    Chat {
        int id PK
        int user_id FK "nullable"
        string chat_type "chat, agent"
        string agent_type
        string name
        datetime created_at
    }

    ChatMessage {
        int id PK
        int chat_id FK
        string message_type "HUMAN, AI, SYSTEM"
        text content
        datetime created_at
    }
```

## Model Relationships Summary

### Core Financial Flow

```
AccountGroup (type: asset/liability/equity/income/expense)
    └── Account (account_number determines type range)
            ├── JournalLine (debit or credit movements)
            │       └── JournalEntry (balanced entry, multiple lines)
            ├── Budget (monthly planned amount, auto-linked to JournalLine)
            ├── BankTransaction (imported, links to JournalEntry when categorized)
            └── Goal (1:1, auto-created equity account)
                    └── GoalAllocation (monthly savings contribution)
```

### Bank Feed Flow

```
PlaidItem (institution connection)
    └── PlaidAccount (individual account at institution)
            └── PlaidTransaction (extends BankTransaction with Plaid metadata)
                    └── BankTransaction (staging table)
                            └── JournalEntry (when categorized)
```

### Multi-Tenancy Scope

All models with `team_id` extend `BaseTeamModel`:
- Account, AccountGroup, Payee
- JournalEntry, JournalLine
- Budget, Goal, GoalAllocation
- BankTransaction
- PlaidItem, PlaidAccount, PlaidTransaction

## Key Constraints

| Model | Unique Constraint |
|-------|------------------|
| Account | (team, account_number) |
| AccountGroup | (team, name) |
| Payee | (team, name) |
| Budget | (team, month, category) |
| Goal | (team, name) |
| GoalAllocation | (team, goal, month) |
| Membership | (team, user) |

## Account Number Ranges

| Range | Type | Example |
|-------|------|---------|
| 1000-1999 | Asset | Checking (1000), Savings (1001) |
| 2000-2999 | Liability | Credit Card (2000) |
| 3000-3999 | Equity | Goal accounts (auto-assigned) |
| 4000-4999 | Income | Salary (4000), Freelance (4001) |
| 5000-5999 | Expense | Rent (5000), Groceries (5001) |

## Validation Rules

### JournalEntry
- `total_debits` must equal `total_credits` (balanced entry)
- Status transitions: draft → posted → void

### JournalLine
- Exactly one of `dr_amount` or `cr_amount` must be non-zero
- Neither can be negative
- `budget` is auto-calculated on save based on account and entry date

### Goal
- On create, auto-generates backing Account in 3000s range
- Account type is always "equity"
- Progress calculated from sum of GoalAllocation amounts

### BankTransaction
- `is_categorized` = `journal_entry is not null`
- Amount convention: positive = outflow, negative = inflow (Plaid standard)
