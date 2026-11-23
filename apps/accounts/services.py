"""
Chart-of-accounts rules shared by the CBV pages and the API: what may be deleted,
how an account is deleted, and an institution's account checklist.
"""

from django.db import transaction
from django.db.models import Count, Max, Min, ProtectedError, Q
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext

from .models import (
    ACCOUNT_TYPE_EQUITY,
    ACCOUNT_TYPE_INCOME,
    ACCOUNT_TYPE_LIABILITY,
    Account,
)
from .validators import FEED_ACCOUNT_TYPES

# Accounts whose natural balance is a credit: shown as cr - dr, so a card's debt and
# a salary read positive, matching the balance sheet and the activity table.
CREDIT_NORMAL_TYPES = (ACCOUNT_TYPE_LIABILITY, ACCOUNT_TYPE_INCOME, ACCOUNT_TYPE_EQUITY)


def natural_amount(amount, account_type):
    """A dr - cr amount signed the way the account type is read."""
    return -amount if account_type in CREDIT_NORMAL_TYPES else amount


# ---------------------------------------------------------------------------
# Delete guards
# ---------------------------------------------------------------------------


def group_delete_blocked_reason(group):
    """Why `group` can't be deleted, or None: a system group, or one still holding accounts."""
    if group.is_system:
        return _("System account groups cannot be deleted.")
    count = group.accounts.count()
    if count:
        return ngettext(
            "“%(name)s” still has %(count)d account. Move it to another group or delete it first.",
            "“%(name)s” still has %(count)d accounts. Move them to another group or delete them first.",
            count,
        ) % {"name": group.name, "count": count}
    return None


def payee_delete_blocked_reason(payee):
    """Why `payee` can't be deleted, or None: it is on a transaction."""
    count = payee.journal_entries.count()
    if count:
        return ngettext(
            "“%(name)s” is on %(count)d transaction, so it can't be deleted. Rename it instead, "
            "or change the payee on that transaction first.",
            "“%(name)s” is on %(count)d transactions, so it can't be deleted. Rename it instead, "
            "or change the payee on those transactions first.",
            count,
        ) % {"name": payee.name, "count": count}
    return None


SYSTEM_ACCOUNT_MESSAGE = gettext_lazy("System accounts cannot be deleted.")
HAS_TRANSACTIONS_MESSAGE = gettext_lazy("Please delete all associated transactions before deleting an account.")


def _blocking_journal_entries(account):
    """
    Journal entries referencing this account, split into its own opening balance
    (deleted with it) and real activity the user needs to know about before it's gone.

    An opening balance entry is exactly the shape `create_opening_balances`
    writes: two lines, one on this account and the other on the book's system
    equity offset. Anything else -- a categorized transaction, a transfer leg,
    a split -- blocks the delete rather than being silently discarded.
    """
    from apps.journal.models import JournalEntry, JournalLine
    from apps.onboarding.services.opening import OPENING_DESCRIPTION

    entry_ids = JournalLine.objects.filter(account=account).values_list("journal_entry_id", flat=True).distinct()
    entries = JournalEntry.objects.filter(pk__in=entry_ids).prefetch_related("lines__account__account_group")

    opening_ids = []
    blocking = []
    for entry in entries:
        lines = list(entry.lines.all())
        other_lines = [line for line in lines if line.account_id != account.id]
        is_opening = (
            len(lines) == 2
            and len(other_lines) == 1
            and str(entry.description).startswith(str(OPENING_DESCRIPTION))
            and other_lines[0].account.is_system
            and other_lines[0].account.account_group.account_type == ACCOUNT_TYPE_EQUITY
        )
        if is_opening:
            opening_ids.append(entry.pk)
        else:
            blocking.append(entry)

    return opening_ids, blocking


def delete_account(account):
    """
    Delete `account` with its own opening balance, if nothing else references it.
    Returns None on success, else why it was refused (nothing is deleted).
    """
    from apps.journal.models import JournalEntry

    if account.is_system:
        return SYSTEM_ACCOUNT_MESSAGE
    opening_ids, blocking = _blocking_journal_entries(account)
    if blocking:
        return HAS_TRANSACTIONS_MESSAGE
    try:
        with transaction.atomic():
            if opening_ids:
                JournalEntry.objects.filter(pk__in=opening_ids).delete()
            account.delete()
    except ProtectedError:
        return HAS_TRANSACTIONS_MESSAGE
    return None


# ---------------------------------------------------------------------------
# Payees
# ---------------------------------------------------------------------------


def payee_usage(queryset):
    """Annotate how often (and how recently) each payee's transactions count."""
    from apps.journal.models import counted_entries

    counted = counted_entries("journal_entries__")
    return queryset.annotate(
        transaction_count=Count("journal_entries", filter=counted),
        first_used=Min("journal_entries__entry_date", filter=counted),
        last_used=Max("journal_entries__entry_date", filter=counted),
    )


# ---------------------------------------------------------------------------
# Institution account checklist
# ---------------------------------------------------------------------------


def institution_account_choices(institution):
    """
    Accounts an institution can hold: this book's assets and liabilities (the only
    types `AccountForm` offers an institution for), in board order. An archived
    account is offered only while it is linked here, so it can still be unlinked.
    """
    return list(
        Account.objects.filter(
            book=institution.book,
            account_group__account_type__in=FEED_ACCOUNT_TYPES,
            is_system=False,
        )
        .filter(Q(is_archived=False) | Q(institution=institution))
        .select_related("account_group", "institution")
    )


def institution_account_sections(institution, accounts=None):
    """The choices as type -> group -> accounts, each marked linked here or elsewhere."""
    from .board import ACCOUNT_TYPE_SECTION_LABELS

    if accounts is None:
        accounts = institution_account_choices(institution)
    sections = []
    for account in accounts:
        kind = account.account_group.account_type
        if not sections or sections[-1]["type"] != kind:
            sections.append({"type": kind, "label": ACCOUNT_TYPE_SECTION_LABELS[kind], "groups": []})
        groups = sections[-1]["groups"]
        if not groups or groups[-1]["group"].pk != account.account_group_id:
            groups.append({"group": account.account_group, "choices": []})
        linked_here = account.institution_id == institution.pk
        groups[-1]["choices"].append(
            {
                "account": account,
                "checked": linked_here,
                "elsewhere": account.institution if account.institution_id and not linked_here else None,
            }
        )
    return sections


def set_institution_accounts(institution, chosen_ids):
    """
    Link exactly the `chosen_ids` among the checklist's accounts to `institution`.

    A chosen account is linked (moving it from any other institution), an
    unchosen one linked here is unlinked. Accounts the checklist does not offer
    are never touched. Returns whether anything changed.
    """
    chosen = {str(pk) for pk in chosen_ids}
    to_link, to_unlink = [], []
    for account in institution_account_choices(institution):
        ticked = str(account.pk) in chosen
        if ticked and account.institution_id != institution.pk:
            to_link.append(account.pk)
        elif not ticked and account.institution_id == institution.pk:
            to_unlink.append(account.pk)

    now = timezone.now()
    with transaction.atomic():
        Account.objects.filter(pk__in=to_link).update(institution=institution, updated_at=now)
        Account.objects.filter(pk__in=to_unlink).update(institution=None, updated_at=now)
    return bool(to_link or to_unlink)
