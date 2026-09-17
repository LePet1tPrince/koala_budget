from django.db import transaction

from apps.accounts.models import Account, AccountGroup, Payee


@transaction.atomic
def apply_template(team, template):
    """
    Apply a bootstrap template to a team.

    Creates the team's *structure* only -- account groups, accounts and payees.
    Deliberately creates no transactions: a new team starts with an empty ledger
    so the first numbers a user sees are their own.

    Safe to run multiple times (idempotent).
    """

    group_map = {}

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
                "is_system": g.get("is_system", False),
            },
        )
        group_map[g["name"]] = group

    # -------------------------
    # Accounts
    # -------------------------
    for a in template["accounts"]:
        Account.objects.get_or_create(
            team=team,
            name=a["name"],
            defaults={
                "has_feed": a.get("has_feed", False),
                "account_group": group_map[a["group"]],
                "is_system": a.get("is_system", False),
            },
        )

    # -------------------------
    # Payees
    # -------------------------
    for name in template.get("payees", []):
        Payee.objects.get_or_create(
            team=team,
            name=name,
        )
