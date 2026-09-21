"""
The Settings area's section list.

Every surface that shows the sections -- the rail down the side of a settings
page and the cards on the hub -- reads this one list, so adding a section is an
edit here and nowhere else. It is Python rather than template markup because
which sections a user may see depends on facts only the request knows (whether
they have a password to change, whether they administer the team), and those
rules should not be restated in two templates.

The sections keep the URLs the features already had. Consolidation here means
one place to reach them and one shell around them, not a renaming of every
route -- Stripe's return URLs, the teams API helpers and the e2e suite all name
those routes, and moving them would buy nothing a user can see.
"""

from dataclasses import dataclass

from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.teams.roles import is_admin

# Rail headings, in the order they are shown.
GROUP_ACCOUNT = _("Account")
GROUP_WORKSPACE = _("Workspace")
GROUP_DATA = _("Data")


@dataclass(frozen=True)
class SettingsSection:
    key: str
    label: str
    blurb: str
    icon: str
    url: str
    group: str


def team_for(request):
    """
    The team the settings links should point at.

    Profile and Change Password are account-level pages on non-team URLs, where
    `request.team` is None. Falling back to `default_team` keeps the rail whole
    on those two pages instead of dropping every team-scoped section from it.
    """
    return request.team or request.default_team


def sections_for(request) -> list[SettingsSection]:
    """The settings sections this user can see, in rail order."""
    user = request.user
    if not user.is_authenticated:
        return []

    team = team_for(request)
    sections = [
        SettingsSection(
            key="profile",
            label=_("Profile"),
            blurb=_("Your name, email, avatar, two-factor sign-in and API keys."),
            icon="user",
            url=reverse("users:user_profile"),
            group=GROUP_ACCOUNT,
        )
    ]

    if user.has_usable_password():
        sections.append(
            SettingsSection(
                key="password",
                label=_("Change password"),
                blurb=_("Set a new password for signing in."),
                icon="unlock-alt",
                url=reverse("account_change_password"),
                group=GROUP_ACCOUNT,
            )
        )

    if team:
        sections.append(
            SettingsSection(
                key="team",
                label=_("Team"),
                blurb=_("Rename the workspace, invite people and manage who has access."),
                icon="users",
                url=reverse("single_team:manage_team", args=[team.slug]),
                group=GROUP_WORKSPACE,
            )
        )
        if is_admin(user, team):
            sections.append(
                SettingsSection(
                    key="subscription",
                    label=_("Subscription"),
                    blurb=_("Your plan, invoices and billing details."),
                    icon="credit-card",
                    url=reverse("subscriptions_team:subscription_details", args=[team.slug]),
                    group=GROUP_WORKSPACE,
                )
            )
        sections += [
            SettingsSection(
                key="import",
                label=_("Import from YNAB"),
                blurb=_("Bring over your accounts, transactions, budgets and goals from a YNAB export."),
                icon="cloud-upload",
                url=reverse("ynab_import:home", args=[team.slug]),
                group=GROUP_DATA,
            ),
            SettingsSection(
                key="audit",
                label=_("Audit log"),
                blurb=_("Logins, imports, syncs and bulk operations for this team."),
                icon="history",
                url=reverse("audit:audit_log", args=[team.slug]),
                group=GROUP_DATA,
            ),
        ]

    return sections


def grouped_sections(request) -> list[tuple[str, list[SettingsSection]]]:
    """`sections_for` folded into (heading, sections) pairs, preserving order."""
    grouped: list[tuple[str, list[SettingsSection]]] = []
    for section in sections_for(request):
        if grouped and grouped[-1][0] == section.group:
            grouped[-1][1].append(section)
        else:
            grouped.append((section.group, [section]))
    return grouped
