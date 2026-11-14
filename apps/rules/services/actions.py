"""
What a rule does on a match, and whether it still can.

`problem` says why a saved rule cannot act (its category was deleted, or is no
longer allowed); the engine skips such a rule and the rules page shows it as
"Needs attention". `legs_for` turns a rule's action into the (category, signed
amount) legs for one transaction; `post` writes them through the feed's own
write paths (`apps.bank_feed.services.edit`) -- never journal lines directly.
"""

from decimal import ROUND_HALF_UP, Decimal

from django.utils.translation import gettext as _

from apps.accounts.guards import assert_category_allowed
from apps.accounts.models import Account
from apps.bank_feed.services import edit

from ..models import Rule

CENT = Decimal("0.01")
HUNDRED = Decimal("100")


def split_categories(rule):
    """Category ids a split rule names, in order."""
    return [leg.get("category") for leg in (rule.splits or []) if isinstance(leg, dict)]


def problem(rule, accounts_by_id):
    """
    Why `rule` cannot act, or None. `accounts_by_id` holds the book's accounts
    (with `account_group`) so a page of rules costs one query.
    """
    if rule.action == Rule.ACTION_CATEGORY:
        if rule.category_id is None or rule.category_id not in accounts_by_id:
            return _("Its category was deleted. Pick a new one.")
        try:
            assert_category_allowed(accounts_by_id[rule.category_id])
        except ValueError as e:
            return str(e)
    elif rule.action == Rule.ACTION_SPLIT:
        ids = split_categories(rule)
        if len(ids) < 2:
            return _("A split needs at least two categories.")
        for category_id in ids:
            account = accounts_by_id.get(category_id)
            if account is None:
                return _("One of its split categories was deleted.")
            try:
                assert_category_allowed(account)
            except ValueError as e:
                return str(e)
    elif not (rule.payee_name or rule.description):
        return _("It has nothing to do: set a category, a split or a new name.")
    return None


def book_accounts(book):
    return {a.pk: a for a in Account.objects.filter(book=book).select_related("account_group")}


def legs_for(rule, amount, accounts_by_id):
    """
    `[(account, signed amount)]` for a rule's category or split, or [] for a rename-only rule.

    Split percentages are rounded to the cent and the last leg takes the
    remainder, so the legs always sum to `amount` exactly.
    """
    if rule.action == Rule.ACTION_CATEGORY:
        return [(accounts_by_id[rule.category_id], amount)]
    if rule.action != Rule.ACTION_SPLIT:
        return []
    legs, remaining = [], amount
    entries = [leg for leg in rule.splits if isinstance(leg, dict)]
    for index, leg in enumerate(entries):
        account = accounts_by_id[leg["category"]]
        if index == len(entries) - 1:
            share = remaining
        else:
            share = (amount * Decimal(str(leg["percent"])) / HUNDRED).quantize(CENT, rounding=ROUND_HALF_UP)
        remaining -= share
        legs.append((account, share))
    # A zero leg (a tiny amount split many ways) is no leg at all.
    return [(account, share) for account, share in legs if share]


def serialize_legs(legs):
    return [{"category": account.pk, "amount": str(share)} for account, share in legs]


def deserialize_legs(raw, accounts_by_id):
    """Stored legs back into (account, amount); KeyError when a category is gone."""
    return [(accounts_by_id[int(leg["category"])], Decimal(leg["amount"])) for leg in raw or []]


def post(tx, legs, *, payee_name="", description=""):
    """
    Categorize uncategorized row `tx` with `legs`, applying the rule's renames to
    its entry too. One leg goes through the single-category path, several through
    the split writer. Raises the guards' errors (period lock, void, reconciled).
    """
    if len(legs) == 1:
        edit.apply_fields(
            tx,
            category=legs[0][0],
            payee_name=payee_name or None,
            description=description or None,
        )
    else:
        if description:
            tx.description = description
        if payee_name:
            tx.merchant_name = payee_name
        edit.create_split_entry(tx, legs, payee=edit.payee_for(tx.book, payee_name))
