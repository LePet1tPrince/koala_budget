"""
factory_boy factories for E2E test data.

These factories create minimal, isolated data for each test.
Use them directly in tests or as sub-factories in fixtures.
"""

from decimal import Decimal

import factory
from django.contrib.auth import get_user_model

from apps.accounts.models import (
    ACCOUNT_TYPE_ASSET,
    ACCOUNT_TYPE_EXPENSE,
    ACCOUNT_TYPE_INCOME,
    Account,
    AccountGroup,
    Payee,
)
from apps.bank_feed.models import BankTransaction
from apps.journal.models import JournalEntry, JournalLine
from apps.teams import roles
from apps.teams.models import Membership, Team

User = get_user_model()


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    username = factory.Sequence(lambda n: f"user{n}@example.com")
    email = factory.LazyAttribute(lambda o: o.username)
    password = factory.PostGenerationMethodCall("set_password", "testpass123")


class TeamFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Team

    name = factory.Sequence(lambda n: f"Test Team {n}")
    slug = factory.Sequence(lambda n: f"test-team-{n}")


class MembershipFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Membership

    team = factory.SubFactory(TeamFactory)
    user = factory.SubFactory(UserFactory)
    role = roles.ROLE_ADMIN


class AccountGroupFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AccountGroup

    class Params:
        # Callers still say `team=`; the row belongs to that team's default book.
        team = factory.SubFactory(TeamFactory)

    book = factory.LazyAttribute(lambda o: o.team.default_book)
    name = factory.Sequence(lambda n: f"Account Group {n}")
    account_type = ACCOUNT_TYPE_EXPENSE


class AccountFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Account

    class Params:
        # Callers still say `team=`; the row belongs to that team's default book.
        team = factory.SubFactory(TeamFactory)

    book = factory.LazyAttribute(lambda o: o.team.default_book)
    account_group = factory.SubFactory(AccountGroupFactory, team=factory.SelfAttribute("..team"))
    name = factory.Sequence(lambda n: f"Account {n}")


class AssetAccountGroupFactory(AccountGroupFactory):
    name = factory.Sequence(lambda n: f"Asset Group {n}")
    account_type = ACCOUNT_TYPE_ASSET


class AssetAccountFactory(AccountFactory):
    account_group = factory.SubFactory(AssetAccountGroupFactory, team=factory.SelfAttribute("..team"))


class IncomeAccountGroupFactory(AccountGroupFactory):
    name = factory.Sequence(lambda n: f"Income Group {n}")
    account_type = ACCOUNT_TYPE_INCOME


class IncomeAccountFactory(AccountFactory):
    account_group = factory.SubFactory(IncomeAccountGroupFactory, team=factory.SelfAttribute("..team"))


class PayeeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Payee

    class Params:
        # Callers still say `team=`; the row belongs to that team's default book.
        team = factory.SubFactory(TeamFactory)

    book = factory.LazyAttribute(lambda o: o.team.default_book)
    name = factory.Sequence(lambda n: f"Payee {n}")


class JournalEntryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = JournalEntry

    class Params:
        # Callers still say `team=`; the row belongs to that team's default book.
        team = factory.SubFactory(TeamFactory)

    book = factory.LazyAttribute(lambda o: o.team.default_book)
    entry_date = factory.Faker("date_this_year")
    description = factory.Sequence(lambda n: f"Test Entry {n}")
    status = "posted"


class JournalLineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = JournalLine

    class Params:
        # Callers still say `team=`; the row belongs to that team's default book.
        team = factory.SubFactory(TeamFactory)

    book = factory.LazyAttribute(lambda o: o.team.default_book)
    journal_entry = factory.SubFactory(JournalEntryFactory, team=factory.SelfAttribute("..team"))
    account = factory.SubFactory(AccountFactory, team=factory.SelfAttribute("..team"))
    dr_amount = Decimal("0.00")
    cr_amount = Decimal("0.00")


class BankTransactionFactory(factory.django.DjangoModelFactory):
    """A row in the bank feed.

    The feed table is a projection (`bank_transaction_to_feed_row`): the row's
    category and reconciled flag are read off the linked `JournalEntry`'s lines,
    not off the transaction. `feed_transaction` below builds the combinations the
    filters care about; use it rather than wiring entries up by hand.
    """

    class Meta:
        model = BankTransaction

    class Params:
        # Callers still say `team=`; the row belongs to that team's default book.
        team = factory.SubFactory(TeamFactory)

    book = factory.LazyAttribute(lambda o: o.team.default_book)
    account = factory.SubFactory(AssetAccountFactory, team=factory.SelfAttribute("..team"))
    amount = Decimal("25.00")  # positive = outflow, per the Plaid convention
    posted_date = factory.Faker("date_this_year")
    description = factory.Sequence(lambda n: f"Feed transaction {n}")
    merchant_name = factory.Sequence(lambda n: f"Merchant {n}")
    source = "csv"


def feed_transaction(team, account, *, category=None, reconciled=False, archived=False, **kwargs):
    """Create one bank feed row in a given state.

    - no `category` -> uncategorized (no journal entry at all)
    - `category` -> categorized, with the bank-account line carrying `reconciled`
    """
    entry = None
    if category is not None:
        entry = JournalEntryFactory(team=team, entry_date=kwargs.get("posted_date") or "2026-01-15")
        # The bank-account line is the one the feed reads reconciliation from; the
        # other line is what the feed reports as the row's category.
        JournalLineFactory(
            team=team,
            journal_entry=entry,
            account=account,
            cr_amount=Decimal("25.00"),
            is_reconciled=reconciled,
        )
        JournalLineFactory(
            team=team,
            journal_entry=entry,
            account=category,
            dr_amount=Decimal("25.00"),
        )

    return BankTransactionFactory(
        team=team,
        account=account,
        journal_entry=entry,
        is_archived=archived,
        **kwargs,
    )


def split_feed_transaction(team, account, *, legs, reconciled=False, **kwargs):
    """Create one categorized feed row split across several categories.

    `legs` is [(category_account, signed_amount)] in the feed's convention --
    positive is an outflow. The bank line carries their sum on the opposite
    side, which is what makes the entry balance; see
    docs/split-transactions-plan.md for the sign table.
    """
    total = sum(amount for _, amount in legs)
    entry = JournalEntryFactory(team=team, entry_date=kwargs.get("posted_date") or "2026-01-15")

    # The bank line takes the opposite side of the total, and is the one the
    # feed reads reconciliation from.
    JournalLineFactory(
        team=team,
        journal_entry=entry,
        account=account,
        dr_amount=-total if total < 0 else Decimal("0"),
        cr_amount=total if total > 0 else Decimal("0"),
        is_reconciled=reconciled,
    )
    # Each leg takes the same side as its own sign.
    for category, amount in legs:
        JournalLineFactory(
            team=team,
            journal_entry=entry,
            account=category,
            dr_amount=amount if amount > 0 else Decimal("0"),
            cr_amount=-amount if amount < 0 else Decimal("0"),
        )

    return BankTransactionFactory(
        team=team,
        account=account,
        journal_entry=entry,
        amount=total,
        **kwargs,
    )
