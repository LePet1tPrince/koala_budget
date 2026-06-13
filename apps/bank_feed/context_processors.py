from .models import BankTransaction


def inbox_count(request):
    """
    Number of uncategorized bank transactions for the current team.

    Powers the badge on the "Inbox" navigation item so users can see at a
    glance how many transactions are waiting for review.
    """
    # request.team is a SimpleLazyObject that may wrap None; truthiness unwraps it
    team = getattr(request, "team", None)
    if not team or not request.user.is_authenticated:
        return {}
    return {
        "inbox_count": BankTransaction.objects.filter(
            team=team,
            journal_entry__isnull=True,
            is_archived=False,
        ).count()
    }
