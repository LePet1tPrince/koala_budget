"""
The books API: the team's sets of books (`/a/{team}/books/api/books/`, team level)
and one book's own settings (`/a/{team}/{book}/settings/api/`, book level).

The same rules as the pages in `views.py`, from the same places: who may act is the
team role (members list and open, admins create, archive, restore, delete and change
settings), what is allowed is `services.py` (never the team's last open book) and
`validation.py` (names, addresses, the closed period, the type-the-name confirmation).
"""

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.api.permissions import IsAuthenticatedOrHasUserAPIKey
from apps.teams.permissions import TeamAdminWritePermissions

from . import services
from .models import Book
from .permissions import BookAdminPermissions
from .serializers import BookConfirmSerializer, BookCreateSerializer, BookSerializer, BookSettingsSerializer


def _refuse(error: services.LastOpenBookError):
    raise ValidationError({"non_field_errors": [str(error)]})


@extend_schema(tags=["books"])
@extend_schema_view(
    list=extend_schema(
        operation_id="books_list",
        description="Every set of books in the team, archived ones included (so they can be restored).",
    ),
    retrieve=extend_schema(operation_id="books_retrieve"),
)
class BookViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = Book.objects.none()  # for the schema; `get_queryset` is the team's
    serializer_class = BookSerializer
    permission_classes = (IsAuthenticatedOrHasUserAPIKey, TeamAdminWritePermissions)
    # Not `book_slug`: `BooksMiddleware` would read that as a page *in* the book.
    lookup_field = "slug"
    lookup_url_kwarg = "slug"
    pagination_class = None

    def get_queryset(self):
        return (
            Book.objects.filter(team=self.request.team)
            .select_related("team")
            .order_by("is_archived", "sort_order", "name")
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        team = getattr(self.request, "team", None)
        if team:
            context["open_count"] = services.open_books(team).count()
            default_book = team.default_book
            context["default_book_id"] = default_book.id if default_book else None
        return context

    def _book_response(self, book, status_code=status.HTTP_200_OK):
        book.refresh_from_db()
        return Response(self.get_serializer(book).data, status=status_code)

    @extend_schema(
        operation_id="books_create",
        request=BookCreateSerializer,
        responses={201: BookSerializer},
        description=(
            "Create a set of books (admins). `start` says how the client starts it next: the onboarding "
            "questionnaire, the YNAB importer or loading an export, each in the new book."
        ),
    )
    def create(self, request, team_slug):
        serializer = BookCreateSerializer(data=request.data, context={"team": request.team})
        serializer.is_valid(raise_exception=True)
        book = services.create_team_book(
            request, request.team, serializer.validated_data["name"], serializer.validated_data["start"]
        )
        return self._book_response(book, status.HTTP_201_CREATED)

    @extend_schema(
        operation_id="books_archive",
        request=BookConfirmSerializer,
        responses={200: BookSerializer},
        description="Archive the book (admins). Refused for the team's last open book; a no-op if already archived.",
    )
    @action(detail=True, methods=["post"])
    def archive(self, request, team_slug, slug):
        book = self.get_object()
        if book.is_archived:
            return self._book_response(book)
        try:
            services.ensure_can_archive(book)
        except services.LastOpenBookError as error:
            _refuse(error)
        BookConfirmSerializer(data=request.data, context={"book": book}).is_valid(raise_exception=True)
        services.archive_book(request, book)
        return self._book_response(book)

    @extend_schema(operation_id="books_restore", request=None, responses={200: BookSerializer})
    @action(detail=True, methods=["post"])
    def restore(self, request, team_slug, slug):
        book = self.get_object()
        services.restore_book(request, book)
        return self._book_response(book)

    @extend_schema(
        operation_id="books_delete",
        request=BookConfirmSerializer,
        responses={204: None},
        description=(
            "Delete the book and every row in it (admins). Refused for the team's last open book. "
            "A POST rather than a DELETE: the confirmation is a body, which a DELETE may not carry."
        ),
    )
    @action(detail=True, methods=["post"], url_path="delete", url_name="delete")
    def delete_book(self, request, team_slug, slug):
        book = self.get_object()
        try:
            services.ensure_can_delete(book)
        except services.LastOpenBookError as error:
            _refuse(error)
        BookConfirmSerializer(data=request.data, context={"book": book}).is_valid(raise_exception=True)
        services.delete_book(request, book)
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["books"])
class BookSettingsView(mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """
    This book's name, address, future-income setting, household size, report
    timeframe and closed period. A changed `slug` moves every URL of the book:
    the response's `base_url` is the new one.
    """

    serializer_class = BookSettingsSerializer
    permission_classes = (IsAuthenticatedOrHasUserAPIKey, BookAdminPermissions)

    def get_object(self):
        # The URL's book (the permission has checked it exists), as a plain instance to save.
        return Book.objects.select_related("team").get(pk=self.request.book.pk)

    @extend_schema(operation_id="book_settings_retrieve")
    def retrieve(self, request, team_slug, book_slug):
        return super().retrieve(request)

    @extend_schema(operation_id="book_settings_partial_update")
    def partial_update(self, request, team_slug, book_slug):
        book = self.get_object()
        before = services.settings_snapshot(book)
        serializer = self.get_serializer(book, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        book = serializer.save()
        services.record_settings_change(request, book, before)
        return Response(self.get_serializer(book).data)
