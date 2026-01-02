from decimal import Decimal

PERSONAL_BUDGET_TEMPLATE = {
    "account_groups": [
        # Assets
        {"name": "Bank Accounts", "type": "asset", "description": "Cash and bank-held funds"},
        {"name": "Investment Accounts", "type": "asset", "description": "Long-term investments"},

        # Liabilities
        {"name": "Credit Cards", "type": "liability", "description": "Credit card balances"},
        {"name": "Loans & Mortgages", "type": "liability", "description": "Loans and mortgages"},
        {"name": "Other Debt", "type": "liability", "description": "Other outstanding debt"},

        # Income
        {"name": "Income", "type": "income", "description": "All income sources"},

        # Expenses
        {"name": "Living Expenses", "type": "expense", "description": "Fixed living costs"},
        {"name": "Regular Expenses", "type": "expense", "description": "Recurring monthly expenses"},
        {"name": "Variable Expenses", "type": "expense", "description": "Flexible spending"},
        {"name": "Other Expenses", "type": "expense", "description": "Miscellaneous expenses"},
    ],

    "accounts": [
        # Assets (1000s)
        {"number": 1000, "name": "Chequing Account", "group": "Bank Accounts", "has_feed": True},
        {"number": 1100, "name": "Savings Account", "group": "Bank Accounts", "has_feed": True},
        {"number": 1200, "name": "Investment Account", "group": "Investment Accounts"},

        # Liabilities (2000s)
        {"number": 2000, "name": "Credit Card", "group": "Credit Cards", "has_feed": True},
        {"number": 2100, "name": "Line of Credit", "group": "Other Debt"},
        {"number": 2200, "name": "Mortgage", "group": "Loans & Mortgages"},

        # Income (4000s)
        {"number": 4000, "name": "Salary Income", "group": "Income"},
        {"number": 4100, "name": "Other Income", "group": "Income"},

        # Expenses (5000s)
        {"number": 5000, "name": "Rent / Mortgage", "group": "Living Expenses"},
        {"number": 5100, "name": "Utilities", "group": "Regular Expenses"},
        {"number": 5200, "name": "Groceries", "group": "Regular Expenses"},
        {"number": 5300, "name": "Transportation", "group": "Regular Expenses"},
        {"number": 5400, "name": "Dining Out", "group": "Variable Expenses"},
        {"number": 5500, "name": "Entertainment", "group": "Variable Expenses"},
        {"number": 5900, "name": "Miscellaneous", "group": "Other Expenses"},
    ],

    "payees": [
        "Employer",
        "Grocery Store",
        "Rent / Mortgage",
        "Utility Company",
        "Credit Card Company",
        "Investment Provider",
    ],

    "sample_entries": [
        {
            "description": "Paycheque",
            "payee": "Employer",
            "lines": [
                {"account": 1000, "dr": Decimal("3000.00")},
                {"account": 4000, "cr": Decimal("3000.00")},
            ],
        },
        {
            "description": "Monthly Rent",
            "payee": "Rent / Mortgage",
            "lines": [
                {"account": 5000, "dr": Decimal("1500.00")},
                {"account": 1000, "cr": Decimal("1500.00")},
            ],
        },
        {
            "description": "Groceries",
            "payee": "Grocery Store",
            "lines": [
                {"account": 5200, "dr": Decimal("250.00")},
                {"account": 2000, "cr": Decimal("250.00")},
            ],
        },
    ],
}
