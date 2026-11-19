from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _

from ..api_url_helpers import get_team_api_url_templates
from ..decorators import login_and_team_required


@login_required
def manage_teams(request, path=""):
    # The page loads the user, the teams and the invitations from the API.
    return render(
        request,
        "teams/teams.html",
        {
            "api_urls": get_team_api_url_templates(),
            "page_title": _("Manage Teams"),
        },
    )


@login_and_team_required
def manage_team(request, team_slug):
    # The page loads the team (members, invitations) and the user from the API;
    # the page carries only the team's id, to ask for it by.
    return render(
        request,
        "teams/manage_team_react.html",
        {
            "team": request.team,
            "active_tab": "settings",
            "settings_section": "team",
            "settings_page_title": _("Team"),
            "api_urls": get_team_api_url_templates(),
        },
    )
