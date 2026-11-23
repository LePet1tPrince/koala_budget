"""
User-level and chrome endpoints: who is signed in and where they work (`/api/me/`),
and the figures the app chrome shows for one book (`api/nav-state/`).
"""

from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.bank_feed.services import nav as feed_nav
from apps.books.helpers import landing_team_and_book
from apps.books.models import Book
from apps.budget.unassigned import EXPECTED_INCOME_LABEL, current_unassigned
from apps.onboarding.services.rail import shows_task_rail
from apps.teams.models import Membership

from .base import BookAPIView
from .serializers import MeSerializer, NavStateSerializer


class MeView(APIView):
    """
    The signed-in user, every team they belong to with their role and its books, and
    the team and book the web app would open -- what a client needs to build its
    team/book switcher and pick a starting book. Any authenticated user (session,
    session token or API key).
    """

    @extend_schema(operation_id="me_retrieve", responses=MeSerializer)
    def get(self, request):
        user = request.user
        memberships = list(Membership.objects.filter(user=user).select_related("team").order_by("team__name"))
        teams = [membership.team for membership in memberships]
        books_by_team = {}
        for book in Book.objects.filter(team__in=teams).order_by("sort_order", "name"):
            books_by_team.setdefault(book.team_id, []).append(book)

        landing_team, landing_book = landing_team_and_book(request)
        data = {
            "user": {
                "id": user.id,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "display_name": user.get_display_name(),
                "avatar_url": request.build_absolute_uri(user.avatar_url),
                "language": user.language or None,
                "timezone": user.timezone,
            },
            "teams": [_team_data(membership, books_by_team.get(membership.team_id, [])) for membership in memberships],
            "default": {"team": landing_team.slug, "book": landing_book.slug if landing_book else None}
            if landing_team
            else None,
        }
        return Response(MeSerializer(data).data)


def _team_data(membership, books):
    team = membership.team
    default_book = team.default_book
    return {
        "id": team.id,
        "slug": team.slug,
        "name": team.name,
        "role": membership.role,
        "books": [
            {
                "id": book.id,
                "slug": book.slug,
                "name": book.name,
                "is_archived": book.is_archived,
                "is_default": default_book is not None and book.id == default_book.id,
                # `book.team` without a query: every book here is of this team.
                "base_url": f"/a/{team.slug}/{book.slug}/",
            }
            for book in books
        ],
    }


class NavStateView(BookAPIView):
    """
    What the app chrome shows for this book: the Inbox badge, the Inbox submenu's
    feed accounts, the Unassigned pill (always this month) and whether the guided
    task rail is on. The same figures the sidebar's context processors put in every
    server-rendered page, from the same functions -- for a client that draws its
    own chrome, and for refreshing it after a write.
    """

    @extend_schema(operation_id="nav_state_retrieve", responses=NavStateSerializer)
    def get(self, request, team_slug, book_slug):
        book = self.book
        unassigned = current_unassigned(book)
        data = {
            "inbox_count": feed_nav.inbox_count(book),
            "feed_institutions": feed_nav.feed_accounts_by_institution(book),
            "unassigned": {
                "month": unassigned.month,
                "amount": unassigned.amount,
                "state": unassigned.state,
                "label": str(unassigned.label),
                "expected_income": {"label": str(EXPECTED_INCOME_LABEL), "amount": unassigned.income_due}
                if unassigned.expects_income
                else None,
            },
            "onboarding_rail": {"visible": shows_task_rail(book)},
        }
        return Response(NavStateSerializer(data).data)
