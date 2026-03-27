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

    team = factory.SubFactory(TeamFactory)
    name = factory.Sequence(lambda n: f"Account Group {n}")
    account_type = ACCOUNT_TYPE_EXPENSE


class AccountFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Account

    team = factory.SubFactory(TeamFactory)
    account_group = factory.SubFactory(AccountGroupFactory, team=factory.SelfAttribute("..team"))
    name = factory.Sequence(lambda n: f"Account {n}")
    account_number = factory.Sequence(lambda n: str(5000 + n))


class AssetAccountGroupFactory(AccountGroupFactory):
    name = factory.Sequence(lambda n: f"Asset Group {n}")
    account_type = ACCOUNT_TYPE_ASSET


class AssetAccountFactory(AccountFactory):
    account_group = factory.SubFactory(AssetAccountGroupFactory, team=factory.SelfAttribute("..team"))
    account_number = factory.Sequence(lambda n: str(1000 + n))


class IncomeAccountGroupFactory(AccountGroupFactory):
    name = factory.Sequence(lambda n: f"Income Group {n}")
    account_type = ACCOUNT_TYPE_INCOME


class IncomeAccountFactory(AccountFactory):
    account_group = factory.SubFactory(IncomeAccountGroupFactory, team=factory.SelfAttribute("..team"))
    account_number = factory.Sequence(lambda n: str(4000 + n))


class PayeeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Payee

    team = factory.SubFactory(TeamFactory)
    name = factory.Sequence(lambda n: f"Payee {n}")


class JournalEntryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = JournalEntry

    team = factory.SubFactory(TeamFactory)
    entry_date = factory.Faker("date_this_year")
    description = factory.Sequence(lambda n: f"Test Entry {n}")
    status = "posted"


class JournalLineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = JournalLine

    team = factory.SubFactory(TeamFactory)
    journal_entry = factory.SubFactory(JournalEntryFactory, team=factory.SelfAttribute("..team"))
    account = factory.SubFactory(AccountFactory, team=factory.SelfAttribute("..team"))
    dr_amount = Decimal("0.00")
    cr_amount = Decimal("0.00")
