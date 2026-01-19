``` mermaid
erDiagram
    Account ||--o{ JournalLine : "journal_lines"
    Account ||--o{ BankTransaction : "bank_transactions"
    Account }o--o{ Budget : "category"
    AccountGroup ||--o{ Account : "is part of group"
    Payee ||--o{ JournalEntry : "journal_entries"

    JournalEntry ||--|{ JournalLine : "multiple lines in an entry"
    JournalEntry ||--o{ BankTransaction : "bank_feed_transactions"

    Budget ||--o{ JournalLine : "calculate budget from account and month"

    PlaidItem ||--o{ PlaidAccount : "belong to account"

    PlaidAccount ||--o{ PlaidTransaction : "transactions"
    PlaidAccount }o--|| Account : "account"

    BankTransaction }o--|| Account : "Account this transaction belongs to"
    BankTransaction }o--|| JournalEntry : "create when categorized"

    Goal ||--o{ GoalProgress : "progress"

    %% Entities
    Account {
        int account_id PK
        string name
        int account_number
        int account_group FK
        bool has_feed
        decimal account_balance "calculated"
    }

    AccountGroup {
        int account_group_id PK
        string name
        string account_type
        stringg description
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
    }
    JournalLine {
        int id PK
        int journal_entry FK
        int account FK
        decimal dr_amount
        decimal cr_amount
        int budget FK
    }
    Budget {
        int id PK
        int category(Account) FK
        date month
    }
    PlaidItem {
        int id PK
        string plaid_item_id
        string institution_name
    }
    PlaidAccount {
        int id PK
        string plaid_account_id
        int item(PlaidItem) FK
        int account(Account) FK
    }
    PlaidTransaction {
        int id PK
        int plaid_account FK
    }
    BankTransaction {
        int id PK
        int account FK
        int journal_entry FK
        decimal amount
        date date
        string source
    }
    Goal {
        int id PK
        string name
    }
    GoalProgress {
        int id PK
        int goal FK
        decimal amount
        date date
    }
```