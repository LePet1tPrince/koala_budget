"""
Opening balances: the starting position a user's books need to be true.

Net worth here is `sum(dr - cr)` over asset and liability lines, so a ledger that
only contains imported activity reports the *change* over the imported window, not
what the user actually has. An opening balance closes that gap with one balanced
entry per account, offsetting to the system equity account that already exists for
reconciliation.

Deliberately late in the walkthrough. Asked during the questionnaire, "what is the
balance of each of these accounts" is a wall of numbers before the user has seen
anything work. Asked after they have imported and categorized, it is the obvious
answer to "why does this say I'm worth $42?" -- which is why the endpoint refuses
to run before there is any categorized activity at all.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils.translation import gettext as _

from apps.accounts.models import ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_EQUITY, ACCOUNT_TYPE_LIABILITY, Account
from apps.journal.models import JournalEntry, JournalLine

OPENING_DESCRIPTION = _("Opening balance")

# The account every opening-balance entry posts against. Created by the generated
# chart of accounts (and by the stock template), flagged `is_system` so review
# cannot remove it.
OFFSET_ACCOUNT_NAME = "Reconciliation Adjustments"


class OpeningBalanceError(ValueError):
    """Something the user needs told about. The message is user-facing."""


@dataclass(frozen=True)
class OpeningRow:
    account: Account
    amount: Decimal


def balance_accounts(team) -> list[Account]:
    """
    The accounts worth asking about: the things a user owns or owes.

    Income and expense accounts have no opening balance -- they measure flow over a
    period, not a position -- and equity is the system's own bookkeeping.
    """
    return list(
        Account.objects.filter(
            team=team,
            account_group__account_type__in=(ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY),
            is_system=False,
        )
        .select_related("account_group")
        .order_by("account_group__account_type", "account_group__sort_order", "sort_order", "name")
    )


def _offset_account(team) -> Account:
    account = Account.objects.filter(
        team=team,
        is_system=True,
        account_group__account_type=ACCOUNT_TYPE_EQUITY,
    ).first()
    if account is None:
        raise OpeningBalanceError(_("This team has no equity account to balance opening entries against."))
    return account


def parse_rows(team, raw) -> list[OpeningRow]:
    """
    Read the submitted rows, keeping only the ones that say something.

    A blank or zero amount is how the user skips an account, so it yields no row
    rather than an entry for nothing. Accounts outside the team, or of a type that
    cannot hold an opening balance, are rejected rather than ignored -- silently
    dropping them would leave the user believing they had set a balance.
    """
    if not isinstance(raw, list):
        return []

    allowed = {a.id: a for a in balance_accounts(team)}
    rows: list[OpeningRow] = []

    for item in raw:
        if not isinstance(item, dict):
            continue

        account = allowed.get(item.get("account_id"))
        if account is None:
            if item.get("account_id") is not None and str(item.get("amount") or "").strip():
                raise OpeningBalanceError(_("One of those accounts cannot hold an opening balance."))
            continue

        raw_amount = str(item.get("amount") or "").strip()
        if not raw_amount:
            continue

        try:
            amount = Decimal(raw_amount).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            raise OpeningBalanceError(_("'%(value)s' is not an amount.") % {"value": raw_amount[:20]}) from None

        if amount < 0:
            # A liability is entered as what is owed, not as a negative asset, so a
            # negative number here is nearly always a misunderstanding rather than
            # an intent to record a contra balance.
            raise OpeningBalanceError(_("Enter what you have or owe as a positive number."))

        if amount:
            rows.append(OpeningRow(account=account, amount=amount))

    return rows


@transaction.atomic
def create_opening_balances(team, rows: list[OpeningRow], as_of: date) -> list[JournalEntry]:
    """
    One balanced entry per account.

    An asset is debited and a liability credited, each against the equity offset, so
    `sum(dr - cr)` moves by exactly what the user said they have or owe.
    """
    if not rows:
        return []

    offset = _offset_account(team)
    entries = []

    for row in rows:
        is_asset = row.account.account_group.account_type == ACCOUNT_TYPE_ASSET

        entry = JournalEntry.objects.create(
            team=team,
            entry_date=as_of,
            description=f"{OPENING_DESCRIPTION} — {row.account.name}",
            source=JournalEntry.SOURCE_MANUAL,
            status=JournalEntry.STATUS_POSTED,
        )

        JournalLine.objects.create(
            team=team,
            journal_entry=entry,
            account=row.account,
            dr_amount=row.amount if is_asset else Decimal("0"),
            cr_amount=Decimal("0") if is_asset else row.amount,
        )
        JournalLine.objects.create(
            team=team,
            journal_entry=entry,
            account=offset,
            dr_amount=Decimal("0") if is_asset else row.amount,
            cr_amount=row.amount if is_asset else Decimal("0"),
        )

        entries.append(entry)

    return entries


def existing_opening_balances(team) -> set[int]:
    """
    Account ids that already carry an opening-balance entry.

    The step can be revisited, and setting a second opening balance on the same
    account would silently double it.
    """
    return set(
        JournalLine.objects.filter(
            team=team,
            journal_entry__description__startswith=str(OPENING_DESCRIPTION),
            # The equity offset carries a line on every one of these entries. Without
            # this filter it would report as "already has an opening balance", which
            # is meaningless for an account nobody is ever asked about.
            account__account_group__account_type__in=(ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY),
            account__is_system=False,
        )
        .exclude(journal_entry__status=JournalEntry.STATUS_VOID)
        .values_list("account_id", flat=True)
    )
