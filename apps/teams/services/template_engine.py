from dateutil.relativedelta import relativedelta

from django.db import transaction
from django.utils.timezone import now

from apps.accounts.models import AccountGroup, Account, Payee
from apps.journal.models import JournalEntry, JournalLine


@transaction.atomic
def apply_template(team, template, month_start):
    """
    Apply a bootstrap template to a team.
    Safe to run multiple times (idempotent).
    """

    group_map = {}
    account_map = {}
    payee_map = {}

    # -------------------------
    # Account Groups
    # -------------------------
    for g in template["account_groups"]:
        group, _ = AccountGroup.objects.get_or_create(
            team=team,
            name=g["name"],
            defaults={
                "account_type": g["type"],
                "description": g.get("description", ""),
            },
        )
        group_map[g["name"]] = group

    # -------------------------
    # Accounts
    # -------------------------
    for a in template["accounts"]:
        account, _ = Account.objects.get_or_create(
            team=team,
            account_number=a["number"],
            has_feed=a.get("has_feed", False),
            defaults={
                "name": a["name"],
                "account_group": group_map[a["group"]],
            },
        )
        account_map[a["number"]] = account

    # -------------------------
    # Payees
    # -------------------------
    for name in template.get("payees", []):
        payee, _ = Payee.objects.get_or_create(
            team=team,
            name=name,
        )
        payee_map[name] = payee

    # -------------------------
    # Sample Journal Entries
    # -------------------------
    for _ in range(18): # do the same transactions every month for the last 12 months
        month_start = month_start - relativedelta(months=1)
        for entry in template.get("sample_entries", []):
            je, created = JournalEntry.objects.get_or_create(
                team=team,
                entry_date=month_start,
                description=entry["description"],
                defaults={
                    "payee": payee_map.get(entry.get("payee")),
                    "status": JournalEntry.STATUS_POSTED,
                    "source": JournalEntry.SOURCE_MANUAL,
                },
            )

            if not created:
                continue

            for line in entry["lines"]:
                JournalLine.objects.create(
                    team=team,
                    journal_entry=je,
                    account=account_map[line["account"]],
                    dr_amount=line.get("dr", 0),
                    cr_amount=line.get("cr", 0),
                )
