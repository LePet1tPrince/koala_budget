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

from apps.books.helpers import get_nav_book
from apps.teams.helpers import get_nav_team
from apps.teams.roles import is_admin

# Rail headings, in the order they are shown.
GROUP_TEAM = _("My Team")
GROUP_BOOK = _("This book")
GROUP_ME = _("Me")


@dataclass(frozen=True)
class SettingsSection:
    key: str
    label: str
    blurb: str
    icon: str
    url: str
    group: str


def sections_for(request) -> list[SettingsSection]:
    """The settings sections this user can see, in rail order."""
    user = request.user
    if not user.is_authenticated:
        return []

    # Profile and Change Password are account-level pages on non-team URLs,
    # where `request.team` is None -- `get_nav_team` is the same fallback the
    # sidebar uses, so the rail stays whole on exactly those two pages. The
    # "This book" group follows the nav book the same way: on a team-level page
    # (members, subscription) it links to the book last opened.
    team = get_nav_team(request)
    book = get_nav_book(request)
    admin = bool(team) and is_admin(user, team)
    sections = []

    if team:
        sections += [
            SettingsSection(
                key="team",
                label=_("Members"),
                blurb=_("Rename the team, invite people and manage who has access."),
                icon="users",
                url=reverse("single_team:manage_team", args=[team.slug]),
                group=GROUP_TEAM,
            ),
            # Archiving and deleting a book live here rather than under "This
            # book", so a book can be put away without first opening it.
            SettingsSection(
                key="books",
                label=_("My books"),
                blurb=_("Keep a business, a rental or anything else apart, each with its own accounts and budget."),
                icon="layer-group",
                url=reverse("books_team:list", args=[team.slug]),
                group=GROUP_TEAM,
            ),
        ]
        if admin:
            sections.append(
                SettingsSection(
                    key="subscription",
                    label=_("Subscription"),
                    blurb=_("Your plan, invoices and billing details."),
                    icon="credit-card",
                    url=reverse("subscriptions_team:subscription_details", args=[team.slug]),
                    group=GROUP_TEAM,
                )
            )

    if book:
        if admin:
            sections.append(
                SettingsSection(
                    key="book",
                    label=_("General"),
                    blurb=_("What this book is called, its web address, and how it budgets income."),
                    icon="book-open",
                    url=reverse("books:settings", args=book.url_args),
                    group=GROUP_BOOK,
                )
            )
        sections += [
            SettingsSection(
                key="data_transfer",
                label=_("Export & Import"),
                blurb=_("Download this book, or replace it with a Koala Budget export."),
                icon="download",
                url=reverse("portability:home", args=book.url_args),
                group=GROUP_BOOK,
            ),
            SettingsSection(
                key="import",
                label=_("Import from YNAB"),
                blurb=_("Bring over your accounts, transactions, budgets and goals from a YNAB export."),
                icon="cloud-upload",
                url=reverse("ynab_import:home", args=book.url_args),
                group=GROUP_BOOK,
            ),
            SettingsSection(
                key="audit",
                label=_("Audit log"),
                blurb=_("Logins, imports, syncs and bulk operations for this book."),
                icon="history",
                url=reverse("audit:audit_log", args=book.url_args),
                group=GROUP_BOOK,
            ),
        ]

    sections.append(
        SettingsSection(
            key="profile",
            label=_("Profile"),
            blurb=_("Your name, email, avatar, two-factor sign-in and API keys."),
            icon="user",
            url=reverse("users:user_profile"),
            group=GROUP_ME,
        )
    )
    if user.has_usable_password():
        sections.append(
            SettingsSection(
                key="password",
                label=_("Change password"),
                blurb=_("Set a new password for signing in."),
                icon="unlock-alt",
                url=reverse("account_change_password"),
                group=GROUP_ME,
            )
        )

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
