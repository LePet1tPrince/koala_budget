"""
The book's dashboard (`/a/{team}/{book}/`): its headline figures, the first few
goals, the net-worth trend and which nudges it shows.

One builder for both readers: the server-rendered page (`apps.web.views.book_home`)
and `GET /a/{team}/{book}/api/home/` (`apps.web.api.BookHomeView`). Each turns the
plain Python values returned here into its own form -- template context and links
for the page, a typed response for the API.
"""

from decimal import Decimal

from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext

from apps.accounts.models import Account
from apps.bank_feed.models import BankTransaction
from apps.books.helpers import team_has_several_books
from apps.budget import ledger as budget_ledger
from apps.budget.models import Goal
from apps.budget.services import NetWorthService
from apps.journal.models import JournalEntry, counted_entries, transaction_entries
from apps.monthly_review.models import MonthlyReviewState
from apps.reports.services import ReportService
from apps.utils.months import add_months

# A pool of greetings that rotates day-to-day (deterministic per day, not per request)
# so a user doesn't see the same one on every visit.
GREETINGS = [
    "Hello, {name}",
    "Welcome back, {name}",
    "Good to see you, {name}",
    "Great to have you back, {name}",
    "Hey {name}, welcome back",
    "Nice to see you again, {name}",
]

# The dashboard lists the first few open goals; the Goals page has the rest.
DASHBOARD_GOALS = 4

YNAB_RUNNING = "running"
YNAB_FAILED = "failed"

_UNSET = object()


def greeting_for(user, today):
    name = user.first_name or user.email
    template = gettext(GREETINGS[today.toordinal() % len(GREETINGS)])
    return template.format(name=name)


def onboarding_state(book):
    """
    The book's walkthrough state, or None while onboarding is switched off.

    The state row is created here rather than by a signal on book creation, so the
    signal stays cheap; books that predate the feature were marked complete by
    onboarding migration 0002.
    """
    if not settings.ONBOARDING_ENABLED:
        return None
    from apps.onboarding.views import get_or_create_state

    return get_or_create_state(book)


def book_home_summary(book, user, *, today=None, onboarding=_UNSET) -> dict:
    """
    Everything the dashboard shows for `book`, as of `today` (default: now).

    Returns:
        {
          "month": date,                      # first of the current month
          "greeting": str,
          "book_label": str,                  # the book's name once the team has several, else ""
          "onboarding_finished": bool,        # False: the web app sends the user to the walkthrough
          "net_worth": Decimal,
          "income_ytd": {"start_date", "end_date", "income", "expenses", "net"},
          "amount_to_reach_goals": Decimal,   # what open goals still ask for
          "goals": [Goal, ...],               # annotated `with_progress(month)`, first DASHBOARD_GOALS
          "net_worth_trend": [{"date", "net_worth"}, ...],  # month ends, first activity -> today
          "show_resume": bool,                # offer to pick the guided setup back up
          "ynab_import": {"offered": bool, "state": "" | "running" | "failed"},
          "monthly_review_month": date | None,  # last month, when it is worth a review nudge
        }

    `onboarding` is the book's `onboarding_state` when the caller already has it.
    """
    today = today or timezone.now().date()
    month = today.replace(day=1)
    if onboarding is _UNSET:
        onboarding = onboarding_state(book)

    # The old three-step checklist here was superseded by the walkthrough's task
    # rail. What survives is a nudge for someone who skipped or dismissed the guide
    # and still has gaps.
    show_resume = onboarding is not None and not onboarding.shows_tasks and not _is_set_up(book)

    # The YNAB wizard needs an empty ledger, so it is only offered while the book
    # still has one -- a link that leads to "this book already has transactions" is
    # worse than no link.
    ynab_offered = bool(getattr(settings, "YNAB_IMPORT_ENABLED", False)) and not (
        JournalEntry.objects.filter(transaction_entries(), book=book).exclude(status=JournalEntry.STATUS_VOID).exists()
    )

    report_service = ReportService(book)
    year_start = month.replace(month=1, day=1)
    income_ytd = report_service.get_income_statement_data(year_start, today)

    goals = Goal.objects.filter(book=book).active().with_progress(month)
    # What open goals still ask for: target − allocated (a funded goal asks for nothing).
    amount_to_reach_goals = sum((goal.to_fund for goal in goals), Decimal("0"))

    first_entry_date = (
        JournalEntry.objects.filter(book=book)
        .filter(counted_entries(), transaction_entries())
        .order_by("entry_date")
        .values_list("entry_date", flat=True)
        .first()
    )
    chart_start = first_entry_date.replace(day=1) if first_entry_date else month
    trend = report_service.get_net_worth_trend_data_by_date_range(chart_start, today)

    return {
        "month": month,
        "greeting": greeting_for(user, today),
        "book_label": book.name if team_has_several_books(book.team) else "",
        "onboarding_finished": onboarding is None or onboarding.is_finished,
        # Unassigned is the sidebar pill; its breakdown is the Budget & Goals report.
        "net_worth": NetWorthService(book).get_net_worth(month),
        "income_ytd": {
            "start_date": year_start,
            "end_date": today,
            "income": income_ytd["total_income"],
            "expenses": income_ytd["total_expenses"],
            "net": income_ytd["net_profit"],
        },
        "amount_to_reach_goals": amount_to_reach_goals,
        "goals": list(goals[:DASHBOARD_GOALS]),
        "net_worth_trend": [{"date": point["date"], "net_worth": point["net_worth"]} for point in trend],
        "show_resume": show_resume,
        # An import runs in a worker, so a user who closed the tab comes back *here*,
        # not to the import page. Without this, an import that was still going or
        # that failed while they were away leaves no trace on the page they land on.
        "ynab_import": {"offered": ynab_offered, "state": _ynab_state(book) if ynab_offered else ""},
        "monthly_review_month": _monthly_review_nudge(book, month, first_entry_date),
    }


def _monthly_review_nudge(book, month, first_entry_date):
    """
    Last month, when it is worth nudging a review of it: there is a completed month
    of activity to review and it has been neither reviewed nor dismissed. Else None.
    """
    last_month = add_months(month, -1)
    if not settings.MONTHLY_REVIEW_ENABLED or first_entry_date is None:
        return None
    if last_month < first_entry_date.replace(day=1):
        return None
    finished = (
        MonthlyReviewState.objects.filter(book=book, month=last_month)
        .filter(Q(completed_at__isnull=False) | Q(dismissed_at__isnull=False))
        .exists()
    )
    return None if finished else last_month


def _ynab_state(book) -> str:
    """
    Whether this book has a YNAB import worth mentioning on the dashboard.

    Only the two states the user cannot otherwise find out about: one still going,
    and one that failed. A successful import needs no mention -- the numbers all
    over this page are the mention.
    """
    from apps.ynab_import.models import YnabImport

    record = YnabImport.objects.resumable(book)
    if record is None or record.status == YnabImport.STATUS_DONE:
        return ""
    return YNAB_FAILED if record.status == YnabImport.STATUS_FAILED else YNAB_RUNNING


def _is_set_up(book) -> bool:
    """
    Whether the book has the three things the walkthrough exists to produce.

    Used only to decide whether to offer picking the guide back up -- a book that
    has accounts, transactions and a budget has no use for it, however they got there.
    """
    return (
        Account.objects.filter(book=book).exclude_budget_buckets().exists()
        and (
            JournalEntry.objects.filter(transaction_entries(), book=book).exists()
            or BankTransaction.objects.filter(book=book).exists()
        )
        and budget_ledger.has_budget(book)
    )
