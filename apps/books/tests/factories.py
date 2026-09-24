"""
A full set of data in one set of books, for the cross-book tests.

Every name carries the book's `marker`, so "does anything of book B show up on
book A's page?" is a substring search over the response.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db.models import Model

from apps.accounts.models import Account, AccountGroup, Institution, Payee
from apps.audit.models import AuditEvent
from apps.bank_feed.models import BankTransaction, TransferMatchDismissal
from apps.books.helpers import create_book
from apps.books.migration_utils import BOOK_MODELS
from apps.budget.models import Budget, Goal, GoalAllocation
from apps.journal.models import JournalEntry, JournalLine
from apps.monthly_review.models import MonthlyReviewState
from apps.onboarding.models import OnboardingState
from apps.plaid.models import PlaidAccount, PlaidItem, PlaidTransaction
from apps.portability.models import DataImport
from apps.reconciliation.models import Reconciliation
from apps.ynab_import.models import YnabImport

MONTH = date(2026, 3, 1)


@dataclass
class BookData:
    book: object
    marker: str
    asset_group: AccountGroup
    expense_group: AccountGroup
    income_group: AccountGroup
    institution: Institution
    chequing: Account
    savings: Account
    groceries: Account
    salary: Account
    payee: Payee
    entry: JournalEntry
    bank_line: JournalLine
    categorized_tx: BankTransaction
    uncategorized_tx: BankTransaction
    other_tx: BankTransaction
    budget: Budget
    goal: Goal
    allocation: GoalAllocation
    reconciliation: Reconciliation
    plaid_item: PlaidItem
    plaid_account: PlaidAccount
    plaid_transaction: PlaidTransaction
    event: AuditEvent
    ynab_import: YnabImport
    data_import: DataImport

    def object_for(self, kind: str) -> Model:
        return {
            "group": self.expense_group,
            "account": self.groceries,
            "asset_account": self.chequing,
            "payee": self.payee,
            "institution": self.institution,
            "entry": self.entry,
            "line": self.bank_line,
            "bank_transaction": self.categorized_tx,
            "goal": self.goal,
            "reconciliation": self.reconciliation,
            "plaid_item": self.plaid_item,
            "plaid_account": self.plaid_account,
            "plaid_transaction": self.plaid_transaction,
            "event": self.event,
        }[kind]


def build_book_data(book, marker: str, user=None) -> BookData:
    """Accounts, a categorized entry, feed rows, a budget, a goal, a statement and a Plaid connection."""
    asset_group = AccountGroup.objects.create(book=book, name=f"Banks {marker}", account_type="asset")
    expense_group = AccountGroup.objects.create(book=book, name=f"Living {marker}", account_type="expense")
    income_group = AccountGroup.objects.create(book=book, name=f"Work {marker}", account_type="income")
    institution = Institution.objects.create(book=book, name=f"Bank of {marker}")
    chequing = Account.objects.create(
        book=book, name=f"Chequing {marker}", account_group=asset_group, has_feed=True, institution=institution
    )
    savings = Account.objects.create(book=book, name=f"Savings {marker}", account_group=asset_group, has_feed=True)
    groceries = Account.objects.create(book=book, name=f"Groceries {marker}", account_group=expense_group)
    salary = Account.objects.create(book=book, name=f"Salary {marker}", account_group=income_group)
    payee = Payee.objects.create(book=book, name=f"Grocer {marker}")

    entry = JournalEntry.objects.create(
        book=book,
        entry_date=MONTH.replace(day=5),
        description=f"Groceries run {marker}",
        payee=payee,
        status=JournalEntry.STATUS_POSTED,
    )
    bank_line = JournalLine.objects.create(
        book=book, journal_entry=entry, account=chequing, dr_amount=Decimal("0"), cr_amount=Decimal("42.00")
    )
    JournalLine.objects.create(
        book=book, journal_entry=entry, account=groceries, dr_amount=Decimal("42.00"), cr_amount=Decimal("0")
    )
    categorized_tx = BankTransaction.objects.create(
        book=book,
        account=chequing,
        posted_date=MONTH.replace(day=5),
        description=f"Groceries run {marker}",
        amount=Decimal("42.00"),
        source=BankTransaction.SOURCE_CSV,
        journal_entry=entry,
    )
    uncategorized_tx = BankTransaction.objects.create(
        book=book,
        account=chequing,
        posted_date=MONTH.replace(day=9),
        description=f"Mystery charge {marker}",
        amount=Decimal("13.37"),
        source=BankTransaction.SOURCE_CSV,
    )
    other_tx = BankTransaction.objects.create(
        book=book,
        account=savings,
        posted_date=MONTH.replace(day=9),
        description=f"Transfer in {marker}",
        amount=Decimal("-13.37"),
        source=BankTransaction.SOURCE_CSV,
    )
    TransferMatchDismissal.record(book, uncategorized_tx.id, other_tx.id)

    budget = Budget.objects.create(book=book, month=MONTH, category=groceries, budget_amount=Decimal("300.00"))
    goal = Goal.objects.create(book=book, name=f"Trip {marker}", target_amount=Decimal("1000"))
    allocation = GoalAllocation.objects.create(book=book, goal=goal, month=MONTH, amount=Decimal("50"))
    reconciliation = Reconciliation.objects.create(
        book=book, account=savings, statement_date=MONTH.replace(day=28), statement_balance=Decimal("0")
    )

    plaid_item = PlaidItem.objects.create(
        book=book, plaid_item_id=f"item-{marker}", access_token="secret", institution_name=f"Plaid {marker}"
    )
    plaid_account = PlaidAccount.objects.create(
        book=book,
        plaid_account_id=f"acct-{marker}",
        item=plaid_item,
        account=chequing,
        name=f"Plaid chequing {marker}",
        subtype="checking",
        type="depository",
    )
    plaid_transaction = PlaidTransaction.objects.create(
        book=book,
        plaid_transaction_id=f"tx-{marker}",
        plaid_account=plaid_account,
        bank_transaction=uncategorized_tx,
    )

    MonthlyReviewState.objects.create(book=book, month=MONTH, notes=f"Review {marker}")
    state, _ = OnboardingState.objects.get_or_create(book=book)
    state.complete()
    state.finish_tasks()
    state.save()

    event = AuditEvent.objects.create(
        team=book.team, book=book, user=user, event_type=AuditEvent.BULK_EDIT, metadata={"note": marker}
    )
    ynab_import = YnabImport.objects.create(book=book, register_csv=f"reg {marker}", plan_csv=f"plan {marker}")
    data_import = DataImport.objects.create(book=book, created_by=user, archive=b"not a real archive")

    return BookData(
        book=book,
        marker=marker,
        asset_group=asset_group,
        expense_group=expense_group,
        income_group=income_group,
        institution=institution,
        chequing=chequing,
        savings=savings,
        groceries=groceries,
        salary=salary,
        payee=payee,
        entry=entry,
        bank_line=bank_line,
        categorized_tx=categorized_tx,
        uncategorized_tx=uncategorized_tx,
        other_tx=other_tx,
        budget=budget,
        goal=goal,
        allocation=allocation,
        reconciliation=reconciliation,
        plaid_item=plaid_item,
        plaid_account=plaid_account,
        plaid_transaction=plaid_transaction,
        event=event,
        ynab_import=ynab_import,
        data_import=data_import,
    )


def second_book(team, name="Business"):
    return create_book(team, name)


def snapshot(book) -> dict:
    """
    Every row of every book-scoped model in `book`, minus `updated_at`.

    Compared before and after a request made under another book: the two must
    be identical, row for row.
    """
    from django.apps import apps

    rows = {}
    for app_label, model_name in BOOK_MODELS:
        model = apps.get_model(app_label, model_name)
        values = model.objects.filter(book=book).order_by("pk").values()
        rows[f"{app_label}.{model_name}"] = [{k: v for k, v in row.items() if k != "updated_at"} for row in values]
    return rows
