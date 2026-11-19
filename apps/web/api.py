"""
`GET /a/{team}/{book}/api/home/` -- the book's dashboard as data.

Mounted with the other book endpoints that belong to no one app (`apps/api/urls.py`,
beside `nav-state/`): the dashboard is the book's root page, so it has no app
prefix of its own.
"""

from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from apps.api.base import BookAPIView

from .serializers import BookHomeSerializer
from .services import home


class BookHomeView(BookAPIView):
    """
    The dashboard of this book: net worth, income − expenses year to date, what
    the open goals still need and the first few of them, the month-end net-worth
    trend, and which nudges to show (finish setup, a YNAB import, last month's
    review). The same figures the server-rendered dashboard shows, from the same
    builder. A book whose walkthrough is unfinished still answers, with
    `onboarding_finished: false`.
    """

    @extend_schema(operation_id="book_home_retrieve", tags=["dashboard"], responses=BookHomeSerializer)
    def get(self, request, team_slug, book_slug):
        summary = home.book_home_summary(self.book, request.user)
        month = summary["monthly_review_month"]
        summary["monthly_review_nudge"] = {"month": month} if month else None
        return Response(BookHomeSerializer(summary).data)
