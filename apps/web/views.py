from django.conf import settings
from django.contrib import messages
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from health_check.views import MainView

from apps.accounts.models import Account
from apps.bank_feed.models import BankTransaction
from apps.budget.models import Budget, Goal
from apps.budget.services import NetWorthService
from apps.journal.models import JournalEntry
from apps.teams.decorators import login_and_team_required
from apps.teams.helpers import get_open_invitations_for_user


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
    month = timezone.now().date().replace(day=1)

    accounts_count = Account.objects.filter(team=team).count()
    has_transactions = (
        JournalEntry.objects.filter(team=team).exists() or BankTransaction.objects.filter(team=team).exists()
    )
    has_budget = Budget.objects.filter(team=team).exists()

    recent_entries = (
        JournalEntry.objects.filter(team=team)
        .exclude(status=JournalEntry.STATUS_VOID)
        .select_related("payee")
        .order_by("-entry_date", "-created_at")[:5]
    )

    return render(
        request,
        "web/app_home.html",
        context={
            "team": team,
            "active_tab": "dashboard",
            "page_title": _("{team} Home").format(team=team),
            "month": month,
            "net_worth_card": NetWorthService(team).get_net_worth_card_data(month),
            "goals": Goal.objects.filter(team=team).active().with_progress(month)[:4],
            "recent_entries": recent_entries,
            "show_onboarding": not (accounts_count and has_transactions and has_budget),
            "has_accounts": accounts_count > 0,
            "has_transactions": has_transactions,
            "has_budget": has_budget,
        },
    )


def simulate_error(request):
    raise Exception("This is a simulated error.")


class HealthCheck(MainView):
    def get(self, request, *args, **kwargs):
        tokens = settings.HEALTH_CHECK_TOKENS
        if tokens and request.GET.get("token") not in tokens:
            raise Http404
        return super().get(request, *args, **kwargs)
