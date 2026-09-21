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
from apps.budget.models import Budget, Goal
from apps.budget.services import NetWorthService
from apps.journal.models import JournalEntry
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
    assert request.team.slug == team_slug
    team = request.team

    # A team that has not been through the guided walkthrough is sent to it. The
    # state row is created here rather than by a signal on team creation, so the
    # signal stays cheap; teams that predate the feature were marked complete by
    # onboarding migration 0002 and never land here.
    onboarding = get_or_create_state(team) if settings.ONBOARDING_ENABLED else None
    if onboarding and not onboarding.is_finished:
        return HttpResponseRedirect(reverse("onboarding:home", args=[team.slug]))

    today = timezone.now().date()
    month = today.replace(day=1)

    # The old three-step checklist here was superseded by the walkthrough's task
    # rail, which covers the same ground with real gates. What survives is a
    # nudge for someone who skipped or dismissed the guide and still has gaps.
    show_resume = settings.ONBOARDING_ENABLED and not onboarding.shows_tasks and not _is_set_up(team)
    # The YNAB wizard needs an empty ledger, so it is only offered while the team
    # still has one -- a link that leads to "this team already has transactions" is
    # worse than no link.
    ynab_url = (
        reverse("ynab_import:home", args=[team.slug])
        if getattr(settings, "YNAB_IMPORT_ENABLED", False)
        and not JournalEntry.objects.filter(team=team).exclude(status=JournalEntry.STATUS_VOID).exists()
        else ""
    )
    # An import runs in a worker, so a user who closed the tab comes back *here*,
    # not to the import page. Without this, an import that was still going or that
    # failed while they were away leaves no trace on the page they land on.
    ynab_state = _ynab_state(team) if ynab_url else ""

    report_service = ReportService(team)
    income_ytd = report_service.get_income_statement_data(month.replace(month=1, day=1), today)

    goals_qs = Goal.objects.filter(team=team).active().with_progress(month)
    amount_to_reach_goals = sum((max(goal.remaining, Decimal("0")) for goal in goals_qs), Decimal("0"))

    first_entry_date = (
        JournalEntry.objects.filter(team=team)
        .exclude(status=JournalEntry.STATUS_VOID)
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
        and not MonthlyReviewState.objects.filter(team=team, month=last_reviewable_month)
        .filter(Q(completed_at__isnull=False) | Q(dismissed_at__isnull=False))
        .exists()
    )

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
            "team": team,
            "active_tab": "dashboard",
            "page_title": _("{team} Home").format(team=team),
            "greeting": _greeting_for(request.user, today),
            "month": month,
            "net_worth_card": NetWorthService(team).get_net_worth_card_data(month),
            "income_ytd": income_ytd,
            "amount_to_reach_goals": amount_to_reach_goals,
            "goals": goals_qs[:4],
            "net_worth_chart_data": net_worth_chart_data,
            "show_resume": show_resume,
            "resume_url": reverse("onboarding:api_task", args=[team.slug]),
            "ynab_url": ynab_url,
            "ynab_state": ynab_state,
            "show_monthly_review_nudge": show_monthly_review_nudge,
            "monthly_review_month": last_reviewable_month,
            "monthly_review_url": (
                reverse("monthly_review:home", args=[team.slug]) + f"?month={last_reviewable_month.isoformat()}"
            ),
            "monthly_review_dismiss_url": reverse("monthly_review:api_dismiss", args=[team.slug]),
        },
    )


def _ynab_state(team) -> str:
    """
    Whether this team has a YNAB import worth mentioning on the dashboard.

    Only the two states the user cannot otherwise find out about: one still going,
    and one that failed. A successful import needs no mention -- the numbers all
    over this page are the mention.
    """
    from apps.ynab_import.models import YnabImport

    record = YnabImport.objects.resumable(team)
    if record is None or record.status == YnabImport.STATUS_DONE:
        return ""
    return "failed" if record.status == YnabImport.STATUS_FAILED else "running"


def _is_set_up(team) -> bool:
    """
    Whether the team has the three things the walkthrough exists to produce.

    Used only to decide whether to offer picking the guide back up -- a team that
    has accounts, transactions and a budget has no use for it, however they got there.
    """
    return (
        Account.objects.filter(team=team).exists()
        and (JournalEntry.objects.filter(team=team).exists() or BankTransaction.objects.filter(team=team).exists())
        and Budget.objects.filter(team=team).exists()
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
