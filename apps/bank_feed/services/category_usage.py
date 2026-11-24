"""
How often each category has been chosen for money going out and for money coming in.

Categorize mode orders its category list by this (`bank_feed/categoryOrder.js`):
within each tier (expenses, transfers, ...), the categories you use most for this
direction come first. A category is the other side of a categorized feed row --
every line of its journal entry that isn't on the feed row's own account -- so a
split counts once for each of its categories, and a transfer counts for the
account at the other end.
"""

from datetime import date, timedelta

from django.db.models import Count, F, Q

from apps.journal.models import JournalLine

# A year: long enough to see an annual bill, short enough that a category you
# stopped using drifts down.
USAGE_WINDOW_DAYS = 365


def category_usage(book, today=None) -> list[dict]:
    """
    `[{"account_id", "outflow", "inflow"}]`: how many feed rows posted in the last
    `USAGE_WINDOW_DAYS` were categorized to each account, split by the row's
    direction (positive amount = money out). Accounts never used are left out.
    """
    since = (today or date.today()) - timedelta(days=USAGE_WINDOW_DAYS)
    rows = "journal_entry__bank_feed_transactions"
    lines = (
        JournalLine.objects.filter(
            book=book,
            **{f"{rows}__is_void": False, f"{rows}__posted_date__gte": since},
        )
        # The feed account's own line is the row itself, not its category.
        .exclude(account=F(f"{rows}__account"))
        .values("account")
        .annotate(
            outflow=Count(f"{rows}", filter=Q(**{f"{rows}__amount__gt": 0}), distinct=True),
            inflow=Count(f"{rows}", filter=Q(**{f"{rows}__amount__lt": 0}), distinct=True),
        )
        .order_by("account")
    )
    return [{"account_id": row["account"], "outflow": row["outflow"], "inflow": row["inflow"]} for row in lines]
