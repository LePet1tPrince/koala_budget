``` mermaid
erDiagram
    Account ||--o{ JournalLine : "journal_lines"
    Account ||--o{ BankTransaction : "bank_transactions"
    Account ||--o{ Budget : "category"
    AccountGroup ||--o{ Account : "is part of group"
    Payee ||--o{ JournalEntry : "journal_entries"

    JournalEntry ||--|{ JournalLine : "multiple lines in an entry"

    Budget ||--o{ JournalLine : "calculate budget from account and month"

    PlaidItem ||--o{ PlaidAccount : "belong to account"

    PlaidAccount ||--o{ PlaidTransaction : "transactions"
    PlaidAccount }o--|| Account : "account"

    BankTransaction }o--|| Account : "Account this transaction belongs to"
    BankTransaction }o--|| JournalEntry : "create when categorized"

    Goal ||--o{ GoalProgress : "progress"

    %% Entities
    Account {
        int id PK
        string name
        string account_number
        int account_group FK
        bool has_feed
        prop balance
    }

    AccountGroup {
        int id PK
        string name
        string account_type
        string description
    }
    Payee {
        int id PK
        string name
    }
    JournalEntry {
        int id PK
        date entry_date
        int payee FK
        string description
        string status
        string source
        prop total_debits
        prop total_credits
        prop is_balanced
    }
    JournalLine {
        int id PK
        int journal_entry FK
        int account FK
        decimal dr_amount
        decimal cr_amount
        bool is_reconciled
        date reconciled_date
        int budget FK
        prop amount
    }
    Budget {
        int id PK
        int category(Account) FK
        date month
        decimal budget_amount
        prop actual
        prop available
    }
    PlaidItem {
        string plaid_item_id PK
        string access_token
        string institution_name
        string cursor
        bool is_active
    }
    PlaidAccount {
        string plaid_account_id PK
        int item(PlaidItem) FK
        int account FK
        string name
        string mask
        string subtype
        string type
        prop is_mapped
    }
    PlaidTransaction {
        string plaid_transaction_id PK
        int bank_transaction FK
        int plaid_account FK
        string iso_currency_code
        string unofficial_currency_code
        date authorized_date
        bool pending
        string pending_transaction_id
        string personal_finance_category
        string category_confidence
        string payment_channel
        string transaction_type
        json location
        json merchant_metadata
    }

    BankTransaction {
        int id PK
        int account FK
        int journal_entry FK
        decimal amount
        date posted_date
        string description
        string merchant_name
        string source
        json raw
        prop is_categorized
    }
    Goal {
        int id PK
        string name
        string description
        decimal goal_amount
        date target_date
    }
    GoalProgress {
        int id PK
        int goal FK
        decimal amount
        date date
    }
```