from django.db import transaction

from apps.accounts.models import Account, AccountGroup, Payee


@transaction.atomic
def apply_template(book, template):
    """
    Apply a bootstrap template to a set of books.

    Creates the book's *structure* only -- account groups, accounts and payees.
    A template may carry `sort_order` on groups and accounts to fix their display
    order; templates that omit it fall back to 0, leaving the alphabetical default.
    Deliberately creates no transactions: a new book starts with an empty ledger
    so the first numbers a user sees are their own.

    Safe to run multiple times (idempotent).
    """

    group_map = {}

    # -------------------------
    # Account Groups
    # -------------------------
    for g in template["account_groups"]:
        group, _ = AccountGroup.objects.get_or_create(
            book=book,
            name=g["name"],
            defaults={
                "account_type": g["type"],
                "description": g.get("description", ""),
                "is_system": g.get("is_system", False),
                "sort_order": g.get("sort_order", 0),
            },
        )
        group_map[g["name"]] = group

    # -------------------------
    # Accounts
    # -------------------------
    for a in template["accounts"]:
        Account.objects.get_or_create(
            book=book,
            name=a["name"],
            defaults={
                "has_feed": a.get("has_feed", False),
                "account_group": group_map[a["group"]],
                "is_system": a.get("is_system", False),
                "sort_order": a.get("sort_order", 0),
            },
        )

    # -------------------------
    # Payees
    # -------------------------
    for name in template.get("payees", []):
        Payee.objects.get_or_create(
            book=book,
            name=name,
        )
