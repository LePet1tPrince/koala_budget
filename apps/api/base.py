"""
Building blocks for the book-scoped DRF endpoints of the API-first migration.

How a work package uses them
----------------------------

A book endpoint lives in its app's `urls.py` under `api/` (so its URL is
`/a/{team}/{book}/{app}/api/...`) and is one of:

* a `ModelViewSet`/`GenericViewSet` over a `BaseBookModel`, with
  `permission_classes = [BookModelAccessPermissions]` and a `get_queryset` that
  filters on `self.request.book` (see `apps/rules/views.py`); or
* an `APIView` that is not about one row -- a page's figures, a computed state --
  built on `BookAPIView` below::

      class MonthFiguresView(BookAPIView):
          @extend_schema(parameters=[month_parameter()], responses=MonthFiguresSerializer)
          def get(self, request, team_slug, book_slug):
              month = month_query_param(request)
              return Response(MonthFiguresSerializer(figures(self.book, month)).data)

  Writes on such a view that only an admin may make use
  `permission_classes = [BookAdminWritePermissions]` (members read, admins write).

Months
------

The API's month is a `YYYY-MM` string (decisions table, `docs/api-first-migration-plan.md`).
Read one from the query string with `month_query_param`, from a path kwarg or a
body value with `parse_month_param`, and put one in a serializer with
`MonthField` (it reads `YYYY-MM` and writes the first of the month back out as
`YYYY-MM`). An API never falls back to `session["budget_month"]`: the month is in
the request or it is the default the endpoint documents.

Errors
------

Validation failures are DRF's own shape, `{"<field>": ["message", ...]}` with a
400, raised as `rest_framework.exceptions.ValidationError` -- what a serializer's
`is_valid(raise_exception=True)` produces, so a parameter error and a body error
look the same to the client. Errors not about one field use
`{"non_field_errors": [...]}` (or `{"detail": "..."}` for DRF's own 401/403/404).

The older feed, transactions and rules endpoints answer `{"error": "..."}`
instead: `error_response`, `get_or_404`, or a raised `apps.utils.errors.Refused`.
"""

from collections.abc import Callable
from datetime import date

from django.utils.translation import gettext_lazy as _
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema_field
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.books.permissions import BookAccessPermissions
from apps.utils.months import format_month, parse_month

INVALID_MONTH = _("Enter a month as YYYY-MM.")

MONTH_SCHEMA = {"type": "string", "pattern": r"^[0-9]{4}-[0-9]{2}$", "example": "2026-03"}


def error_response(message, code: int = status.HTTP_400_BAD_REQUEST) -> Response:
    """The `{"error": message}` answer the book apps' own endpoints give (see `apps.utils.errors`)."""
    return Response({"error": message}, status=code)


def get_or_404(queryset, message, **lookup):
    """The row of `queryset` matching `lookup`, or a 404 answering `{"error": message}`."""
    found = queryset.filter(**lookup).first()
    if found is None:
        raise NotFound({"error": message})
    return found


def parse_month_param(value, *, field: str = "month") -> date:
    """The first of the month `value` (`YYYY-MM`) names; a 400 `{field: [...]}` otherwise."""
    month = parse_month(value if isinstance(value, str) else None)
    if month is None:
        raise ValidationError({field: [INVALID_MONTH]})
    return month


def month_query_param(
    request,
    name: str = "month",
    *,
    default: date | Callable[[], date] | None = None,
) -> date | None:
    """
    The `?{name}=YYYY-MM` query parameter as the first of that month.

    Absent (or empty), it is `default` -- a date, a callable returning one (for
    "this month", evaluated per request), or None, which makes the parameter
    required. Present but malformed, it is always a 400, never the default: a
    client that sent a month meant that month.
    """
    value = request.query_params.get(name)
    if value:
        return parse_month_param(value, field=name)
    if default is None:
        raise ValidationError({name: [_("This parameter is required.")]})
    return default() if callable(default) else default


def month_parameter(name: str = "month", *, required: bool = False, description: str = "") -> OpenApiParameter:
    """The OpenAPI description of a `YYYY-MM` query parameter, for `@extend_schema(parameters=[...])`."""
    return OpenApiParameter(
        name,
        OpenApiTypes.STR,
        OpenApiParameter.QUERY,
        required=required,
        description=description or "A month, as YYYY-MM.",
        pattern=MONTH_SCHEMA["pattern"],
    )


@extend_schema_field(MONTH_SCHEMA)
class MonthField(serializers.Field):
    """A month as `YYYY-MM` on the wire, the first of that month (`date`) in Python."""

    default_error_messages = {"invalid": INVALID_MONTH}

    def to_internal_value(self, data):
        month = parse_month(data if isinstance(data, str) else None)
        if month is None:
            self.fail("invalid")
        return month

    def to_representation(self, value):
        return format_month(value)


@extend_schema_field(OpenApiTypes.BINARY)
class UploadField(serializers.FileField):
    """
    An uploaded file in a `multipart/form-data` request body.

    DRF's `FileField` is documented as a URI (what it renders on a model); this
    one is `format: binary`, so the generated client takes a `Blob` and sends it
    as a file part. Pair it with `parser_classes = [MultiPartParser, ...]`.
    """


class BookAPIView(APIView):
    """
    An `APIView` inside one set of books (`/a/{team}/{book}/...`).

    Members of the URL's team may call it, on a URL naming one of its books (else
    403 / 404, as `BookAccessPermissions` answers). `self.book` is that book; every
    query the view makes is filtered on it. Handlers take `(request, team_slug,
    book_slug, ...)` like every book view.
    """

    permission_classes = [BookAccessPermissions]

    @property
    def book(self):
        return self.request.book
