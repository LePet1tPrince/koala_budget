from dateutil.relativedelta import relativedelta
from django.db import transaction

from apps.accounts.models import Account, AccountGroup, Payee
from apps.bank_feed.models import BankTransaction


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
    # Sample Bank Transactions
    # -------------------------
    for _ in range(18): # do the same transactions every month for the last 18 months
        month_start = month_start - relativedelta(months=1)
        for entry in template.get("sample_entries", []):
            # Find the bank account involved in this transaction
            bank_account = None
            amount = 0

            for line in entry["lines"]:
                account = account_map[line["account"]]
                if account.has_feed:
                    bank_account = account
                    # Determine amount and sign based on transaction type
                    dr_amount = line.get("dr", 0)
                    cr_amount = line.get("cr", 0)

                    if dr_amount > 0:
                        # Debit to bank account = outflow (negative)
                        amount = -dr_amount
                    elif cr_amount > 0:
                        # Credit to bank account = inflow (positive)
                        amount = cr_amount

            if bank_account:
                BankTransaction.objects.get_or_create(
                    team=team,
                    date=month_start,
                    description=entry["description"],
                    amount=amount,
                    source=BankTransaction.SOURCE_SYSTEM,
                    defaults={
                        "merchant_name": entry.get("payee"),
                    },
                )
