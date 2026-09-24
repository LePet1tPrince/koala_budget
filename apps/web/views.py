from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.db.models import Q
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _
from health_check.views import MainView

from apps.accounts.models import Account
from apps.bank_feed.models import BankTransaction
from apps.books.decorators import login_and_book_required
from apps.books.helpers import book_display_name, last_book_for_team, team_has_several_books
from apps.budget.models import Budget, Goal
from apps.budget.services import NetWorthService
from apps.budget.unassigned import allocation_bar, compute_unassigned
from apps.journal.models import JournalEntry, counted_entries
from apps.monthly_review.models import MonthlyReviewState
from apps.monthly_review.services.budget import _prev_month
from apps.onboarding.views import get_or_create_state
from apps.reports.services import ReportService
from apps.teams.decorators import login_and_team_required
from apps.teams.helpers import get_open_invitations_for_user

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


def _greeting_for(user, today):
    name = user.first_name or user.email
    template = gettext(GREETINGS[today.toordinal() % len(GREETINGS)])
    return template.format(name=name)


def home(request):
    if request.user.is_authenticated:
        team = request.default_team
        if team:
            return HttpResponseRedirect(reverse("web_team:home", args=[team.slug]))
        else:
            if (open_invitations := get_open_invitations_for_user(request.user)) and len(open_invitations) > 1:
                invitation = open_invitations[0]
                return HttpResponseRedirect(reverse("teams:accept_invitation", args=[invitation["id"]]))

            messages.info(
                request,
                _("Teams are enabled but you have no teams. Create a team below to access the rest of the dashboard."),
            )
            return HttpResponseRedirect(reverse("teams:manage_teams"))
    else:
        return render(request, "web/landing_page.html")


@login_and_team_required
def team_home(request, team_slug):
    """`/a/{team}/` has no page of its own: it opens the book last used in the team."""
    book = last_book_for_team(request, request.team)
    if book is None:
        raise Http404
    return HttpResponseRedirect(reverse("web_book:home", args=book.url_args))


@login_and_book_required
def book_home(request, team_slug, book_slug):
    book = request.book

    # A book that has not been through the guided walkthrough is sent to it. The
    # state row is created here rather than by a signal on book creation, so the
    # signal stays cheap; books that predate the feature were marked complete by
    # onboarding migration 0002 and never land here.
    onboarding = get_or_create_state(book) if settings.ONBOARDING_ENABLED else None
    if onboarding and not onboarding.is_finished:
        return HttpResponseRedirect(reverse("onboarding:home", args=book.url_args))

    today = timezone.now().date()
    month = today.replace(day=1)

    # The old three-step checklist here was superseded by the walkthrough's task
    # rail, which covers the same ground with real gates. What survives is a
    # nudge for someone who skipped or dismissed the guide and still has gaps.
    show_resume = settings.ONBOARDING_ENABLED and not onboarding.shows_tasks and not _is_set_up(book)
    # The YNAB wizard needs an empty ledger, so it is only offered while the book
    # still has one -- a link that leads to "this book already has transactions" is
    # worse than no link.
    ynab_url = (
        reverse("ynab_import:home", args=book.url_args)
        if getattr(settings, "YNAB_IMPORT_ENABLED", False)
        and not JournalEntry.objects.filter(book=book).exclude(status=JournalEntry.STATUS_VOID).exists()
        else ""
    )
    # An import runs in a worker, so a user who closed the tab comes back *here*,
    # not to the import page. Without this, an import that was still going or that
    # failed while they were away leaves no trace on the page they land on.
    ynab_state = _ynab_state(book) if ynab_url else ""

    report_service = ReportService(book)
    income_ytd = report_service.get_income_statement_data(month.replace(month=1, day=1), today)

    goals_qs = Goal.objects.filter(book=book).active().with_progress(month)
    amount_to_reach_goals = sum((max(goal.remaining, Decimal("0")) for goal in goals_qs), Decimal("0"))

    first_entry_date = (
        JournalEntry.objects.filter(book=book)
        .filter(counted_entries())
        .order_by("entry_date")
        .values_list("entry_date", flat=True)
        .first()
    )
    # A nudge to review last month, shown once there's a completed month worth
    # reviewing and it hasn't been reviewed or dismissed yet.
    last_reviewable_month = _prev_month(month)
    show_monthly_review_nudge = (
        settings.MONTHLY_REVIEW_ENABLED
        and first_entry_date is not None
        and last_reviewable_month >= first_entry_date.replace(day=1)
        and not MonthlyReviewState.objects.filter(book=book, month=last_reviewable_month)
        .filter(Q(completed_at__isnull=False) | Q(dismissed_at__isnull=False))
        .exists()
    )

    unassigned = compute_unassigned(book, month, today=today, detail=True)

    chart_start = first_entry_date.replace(day=1) if first_entry_date else month
    trend_data = report_service.get_net_worth_trend_data_by_date_range(chart_start, today)
    net_worth_chart_data = None
    if trend_data:
        net_worth_chart_data = {
            "labels": [item["date"].isoformat() for item in trend_data],
            "net_worth": [float(item["net_worth"]) for item in trend_data],
        }

    return render(
        request,
        "web/app_home.html",
        context={
            "team": request.team,
            "active_tab": "dashboard",
            "page_title": _("{name} Home").format(name=book_display_name(book)),
            "greeting": _greeting_for(request.user, today),
            "book_label": book.name if team_has_several_books(request.team) else "",
            "month": month,
            "net_worth_card": NetWorthService.card_data(unassigned),
            "unassigned": unassigned,
            "unassigned_bar": allocation_bar(unassigned),
            "income_ytd": income_ytd,
            "amount_to_reach_goals": amount_to_reach_goals,
            "goals": goals_qs[:4],
            "net_worth_chart_data": net_worth_chart_data,
            "show_resume": show_resume,
            "resume_url": reverse("onboarding:api_task", args=book.url_args),
            "ynab_url": ynab_url,
            "ynab_state": ynab_state,
            "show_monthly_review_nudge": show_monthly_review_nudge,
            "monthly_review_month": last_reviewable_month,
            "monthly_review_url": (
                reverse("monthly_review:home", args=book.url_args) + f"?month={last_reviewable_month.isoformat()}"
            ),
            "monthly_review_dismiss_url": reverse("monthly_review:api_dismiss", args=book.url_args),
        },
    )


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
    return "failed" if record.status == YnabImport.STATUS_FAILED else "running"


def _is_set_up(book) -> bool:
    """
    Whether the book has the three things the walkthrough exists to produce.

    Used only to decide whether to offer picking the guide back up -- a book that
    has accounts, transactions and a budget has no use for it, however they got there.
    """
    return (
        Account.objects.filter(book=book).exists()
        and (JournalEntry.objects.filter(book=book).exists() or BankTransaction.objects.filter(book=book).exists())
        and Budget.objects.filter(book=book).exists()
    )


def simulate_error(request):
    raise Exception("This is a simulated error.")


class HealthCheck(MainView):
    def get(self, request, *args, **kwargs):
        tokens = settings.HEALTH_CHECK_TOKENS
        if tokens and request.GET.get("token") not in tokens:
            raise Http404
        return super().get(request, *args, **kwargs)


@login_and_team_required
def settings_home(request, team_slug):
    """
    The Settings hub: one card per section, and the target of the sidebar's
    Settings link. The sections themselves come from `settings_sections.py`, so
    this view holds no list of its own.
    """
    return render(
        request,
        "web/settings/settings_home.html",
        {
            "active_tab": "settings",
            "page_title": gettext("Settings"),
        },
    )
