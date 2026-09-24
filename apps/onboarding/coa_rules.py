"""
The chart of accounts the onboarding questionnaire generates.

The rules are *data*, not branching code, and each rule hangs off the answer
option that triggers it (see ``questions.py``) rather than living in a lookup
keyed by question id. That is what makes the question set safe to edit: delete a
question and its options go with it, taking their rules along -- there is no
separate table left holding a rule for a question that no longer exists.

Account numbers follow the project convention (1000s assets, 2000s liabilities,
4000s income, 5000s expenses) and are used as ``sort_order``, so the numbering
also decides the order accounts appear in on the accounts board and in reports.
"""

from dataclasses import dataclass, field

from apps.accounts.models import (
    ACCOUNT_TYPE_ASSET,
    ACCOUNT_TYPE_EQUITY,
    ACCOUNT_TYPE_EXPENSE,
    ACCOUNT_TYPE_INCOME,
    ACCOUNT_TYPE_LIABILITY,
)


@dataclass(frozen=True)
class GroupSpec:
    name: str
    account_type: str
    description: str = ""
    is_system: bool = False
    sort_order: int = 0


@dataclass(frozen=True)
class AccountSpec:
    number: int | None
    name: str
    group: str
    has_feed: bool = False
    is_system: bool = False

    @property
    def sort_order(self) -> int:
        """Account numbers double as display order within their group."""
        return self.number or 0


@dataclass(frozen=True)
class Grant:
    """What one selected answer option contributes to the chart of accounts."""

    groups: tuple[GroupSpec, ...] = ()
    accounts: tuple[AccountSpec, ...] = ()
    # Tokens of the form "question_id:option_value" that must ALSO be selected for
    # this grant to apply -- e.g. a partner's salary account only makes sense when
    # employment income was chosen. Validated against the catalog by
    # `questions.validate_catalog()`, so a dangling dependency fails a test rather
    # than silently never firing.
    requires: tuple[str, ...] = field(default=())


NOTHING = Grant()


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------
# Declared once and referenced by name from the account specs below. A grant that
# needs a group carries it, so the group is created only when something lands in it.

BANK_ACCOUNTS = GroupSpec("Bank Accounts", ACCOUNT_TYPE_ASSET, "Cash and bank-held funds", sort_order=10)
INVESTMENT_ACCOUNTS = GroupSpec("Investment Accounts", ACCOUNT_TYPE_ASSET, "Long-term investments", sort_order=20)
PROPERTY = GroupSpec("Property & Vehicles", ACCOUNT_TYPE_ASSET, "Things you own outright", sort_order=30)

CREDIT_CARDS = GroupSpec("Credit Cards", ACCOUNT_TYPE_LIABILITY, "Credit card balances", sort_order=10)
LOANS = GroupSpec("Loans & Mortgages", ACCOUNT_TYPE_LIABILITY, "Loans and mortgages", sort_order=20)
OTHER_DEBT = GroupSpec("Other Debt", ACCOUNT_TYPE_LIABILITY, "Other outstanding debt", sort_order=30)

INCOME = GroupSpec("Income", ACCOUNT_TYPE_INCOME, "All income sources", sort_order=10)

LIVING = GroupSpec("Living Expenses", ACCOUNT_TYPE_EXPENSE, "Fixed living costs", sort_order=10)
REGULAR = GroupSpec("Regular Expenses", ACCOUNT_TYPE_EXPENSE, "Recurring monthly expenses", sort_order=20)
VARIABLE = GroupSpec("Variable Expenses", ACCOUNT_TYPE_EXPENSE, "Flexible spending", sort_order=30)
FAMILY = GroupSpec("Family", ACCOUNT_TYPE_EXPENSE, "Costs of raising a family", sort_order=40)
BUSINESS = GroupSpec("Business Expenses", ACCOUNT_TYPE_EXPENSE, "Self-employment costs", sort_order=50)
OTHER_EXPENSES = GroupSpec("Other Expenses", ACCOUNT_TYPE_EXPENSE, "Miscellaneous expenses", sort_order=60)

EQUITY_ADJUSTMENTS = GroupSpec(
    "Equity Adjustments",
    ACCOUNT_TYPE_EQUITY,
    "System equity accounts for reconciliation and opening balances",
    is_system=True,
    sort_order=10,
)


# ---------------------------------------------------------------------------
# The base set -- every book gets these regardless of how they answer
# ---------------------------------------------------------------------------

BASE_GRANT = Grant(
    groups=(
        BANK_ACCOUNTS,
        CREDIT_CARDS,
        INCOME,
        REGULAR,
        VARIABLE,
        OTHER_EXPENSES,
        EQUITY_ADJUSTMENTS,
    ),
    accounts=(
        AccountSpec(1000, "Chequing Account", BANK_ACCOUNTS.name, has_feed=True),
        AccountSpec(1100, "Savings Account", BANK_ACCOUNTS.name, has_feed=True),
        AccountSpec(2000, "Credit Card", CREDIT_CARDS.name, has_feed=True),
        AccountSpec(5100, "Utilities", REGULAR.name),
        AccountSpec(5200, "Groceries", REGULAR.name),
        AccountSpec(5300, "Transportation", REGULAR.name),
        AccountSpec(5400, "Dining Out", VARIABLE.name),
        AccountSpec(5500, "Entertainment", VARIABLE.name),
        AccountSpec(5900, "Miscellaneous", OTHER_EXPENSES.name),
        # The offset account for reconciliation and opening-balance entries.
        AccountSpec(None, "Reconciliation Adjustments", EQUITY_ADJUSTMENTS.name, is_system=True),
    ),
)


# ---------------------------------------------------------------------------
# Payees -- a starting vocabulary so the payee autocomplete is not empty
# ---------------------------------------------------------------------------

BASE_PAYEES = ("Employer", "Grocery Store", "Utility Company", "Credit Card Company")
