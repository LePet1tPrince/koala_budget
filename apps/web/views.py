from django.conf import settings
from django.contrib import messages
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _
from health_check.views import MainView

from apps.books.decorators import login_and_book_required
from apps.books.helpers import book_display_name, last_book_for_team
from apps.teams.decorators import login_and_team_required
from apps.teams.helpers import get_open_invitations_for_user
from apps.utils.months import format_month

from .services import home as home_service


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

    # A book that has not been through the guided walkthrough is sent to it.
    onboarding = home_service.onboarding_state(book)
    if onboarding and not onboarding.is_finished:
        return HttpResponseRedirect(reverse("onboarding:home", args=book.url_args))

    summary = home_service.book_home_summary(book, request.user, onboarding=onboarding)
    review_month = summary["monthly_review_month"]
    return render(
        request,
        "web/app_home.html",
        context={
            **summary,
            "team": request.team,
            "active_tab": "dashboard",
            "page_title": _("{name} Home").format(name=book_display_name(book)),
            # The chart is drawn from `GET …/api/home/`; the page only needs to know there is one.
            "has_net_worth_trend": bool(summary["net_worth_trend"]),
            "ynab_url": reverse("ynab_import:home", args=book.url_args) if summary["ynab_import"]["offered"] else "",
            "ynab_state": summary["ynab_import"]["state"],
            "show_monthly_review_nudge": review_month is not None,
            "monthly_review_month": review_month,
            "monthly_review_url": (
                reverse("monthly_review:home", args=book.url_args) + f"?month={format_month(review_month)}"
                if review_month
                else ""
            ),
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
