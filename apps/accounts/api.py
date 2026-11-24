"""
The accounts app's API, under `/a/{team}/{book}/accounts/api/`.

* `board/` -- the drag-and-drop chart-of-accounts board: its payload and its
  reorder / inline-create / hide writes. Like the old JSON endpoints it replaces,
  every member may use it (list-shaped actions: `BookModelAccessPermissions`
  checks membership only, docs/security-log.md SEC-001).
* `accounts/`, `groups/`, `payees/`, `institutions/` -- ModelViewSets over the
  book's rows. Members read and create; editing or deleting an existing row is
  for admins (`BookModelAccessPermissions`' object check), as on every other
  book-scoped ViewSet. Validation is the Django forms' own (`validators`), and a
  delete the row's references forbid is a 400 with the same reason the pages give.
* `accounts/{id}/activity/` and `accounts/{id}/charts/` -- the account page's
  activity table and charts for a date range.
"""

from datetime import date

from django.db.models import Count
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.api.base import BookAPIView
from apps.audit.models import AuditEvent
from apps.audit.utils import log_event
from apps.books.permissions import BookModelAccessPermissions

from . import board
from .models import ACCOUNT_TYPE_BUDGET, ACCOUNT_TYPE_CHOICES, Account, AccountGroup, Institution, Payee
from .serializers import (
    AccountActivitySerializer,
    AccountChartsSerializer,
    BoardAccountSerializer,
    BoardCreateAccountSerializer,
    BoardCreateGroupSerializer,
    BoardGroupSerializer,
    BoardSerializer,
    DateRangeQuerySerializer,
    InstitutionAccountsSerializer,
    InstitutionAccountsUpdateSerializer,
    ManagedAccountDetailSerializer,
    ManagedAccountGroupSerializer,
    ManagedAccountSerializer,
    ManagedInstitutionSerializer,
    ManagedPayeeSerializer,
    ReorderAccountsSerializer,
    ReorderGroupsSerializer,
    SetHiddenSerializer,
)
from .services import (
    delete_account,
    group_delete_blocked_reason,
    institution_account_sections,
    payee_delete_blocked_reason,
    payee_usage,
    set_institution_accounts,
)

TAGS = ["accounts"]

DATE_RANGE_PARAMETERS = [
    OpenApiParameter("start_date", str, description="First day, YYYY-MM-DD (with end_date)"),
    OpenApiParameter("end_date", str, description="Last day, YYYY-MM-DD (with start_date)"),
]


def _refuse(reason):
    """A delete the row's references forbid: a 400, not the database's PROTECT as a 500."""
    raise ValidationError({"non_field_errors": [str(reason)]})


def _crud_schema(prefix, singular):
    """Readable operation ids (`accounts_groups_list`, ...) for one ModelViewSet."""
    return extend_schema_view(
        list=extend_schema(operation_id=f"{prefix}_list", tags=TAGS),
        retrieve=extend_schema(operation_id=f"{prefix}_retrieve", tags=TAGS),
        create=extend_schema(operation_id=f"{prefix}_create", tags=TAGS),
        update=extend_schema(operation_id=f"{prefix}_update", tags=TAGS),
        partial_update=extend_schema(operation_id=f"{prefix}_partial_update", tags=TAGS),
        destroy=extend_schema(
            operation_id=f"{prefix}_destroy",
            tags=TAGS,
            description=f"Delete the {singular}; refused with a 400 when its references forbid it.",
        ),
    )


# =============================================================================
# Board
# =============================================================================


class BoardView(BookAPIView):
    """The chart-of-accounts board: type sections -> groups -> account rows, in board order."""

    @extend_schema(operation_id="accounts_board_retrieve", tags=TAGS, responses=BoardSerializer)
    def get(self, request, team_slug, book_slug):
        return Response(BoardSerializer({"sections": board.board_sections(self.book)}).data)


class AccountsBoardViewSet(viewsets.GenericViewSet):
    """The board's writes (`board/...`): reorder, inline create, hide. Any member, as before."""

    permission_classes = [BookModelAccessPermissions]
    serializer_class = BoardSerializer
    pagination_class = None
    queryset = Account.objects.none()  # for drf-spectacular schema generation

    @extend_schema(
        operation_id="accounts_board_reorder_accounts",
        tags=TAGS,
        request=ReorderAccountsSerializer,
        responses={204: None},
    )
    @action(detail=False, methods=["post"], url_path="reorder-accounts", serializer_class=ReorderAccountsSerializer)
    def reorder_accounts(self, request, team_slug=None, book_slug=None):
        """Persist account ordering (and moves between groups of the same type)."""
        serializer = ReorderAccountsSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        placements = serializer.validated_data["placements"]
        moved = board.apply_account_order(list(placements), placements)
        if moved:
            log_event(
                AuditEvent.BULK_EDIT,
                request=request,
                metadata={"scope": "accounts_board", "action": "move_account", "moved": moved},
            )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        operation_id="accounts_board_reorder_groups",
        tags=TAGS,
        request=ReorderGroupsSerializer,
        responses={204: None},
    )
    @action(detail=False, methods=["post"], url_path="reorder-groups", serializer_class=ReorderGroupsSerializer)
    def reorder_groups(self, request, team_slug=None, book_slug=None):
        """Persist the group order within one account type."""
        serializer = ReorderGroupsSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        board.apply_group_order(serializer.validated_data["groups"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        operation_id="accounts_board_create_account",
        tags=TAGS,
        request=BoardCreateAccountSerializer,
        responses={201: BoardAccountSerializer},
    )
    @action(detail=False, methods=["post"], url_path="create-account", serializer_class=BoardCreateAccountSerializer)
    def create_account(self, request, team_slug=None, book_slug=None):
        """An account at the bottom of a group; assets and liabilities get a feed."""
        serializer = BoardCreateAccountSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        account = board.create_account(request.book, data["name"], data["group_id"])
        return Response(BoardAccountSerializer(board.account_row(account)).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        operation_id="accounts_board_create_group",
        tags=TAGS,
        request=BoardCreateGroupSerializer,
        responses={201: BoardGroupSerializer},
    )
    @action(detail=False, methods=["post"], url_path="create-group", serializer_class=BoardCreateGroupSerializer)
    def create_group(self, request, team_slug=None, book_slug=None):
        """A group at the bottom of its type's section."""
        serializer = BoardCreateGroupSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        group = board.create_group(request.book, data["name"], data["account_type"])
        return Response(BoardGroupSerializer(board.group_row(group)).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        operation_id="accounts_board_set_hidden",
        tags=TAGS,
        request=SetHiddenSerializer,
        responses={200: SetHiddenSerializer},
    )
    @action(detail=False, methods=["post"], url_path="set-hidden", serializer_class=SetHiddenSerializer)
    def set_hidden(self, request, team_slug=None, book_slug=None):
        """Hide or show an account (the board's eye toggle). Nothing about its transactions changes."""
        serializer = SetHiddenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        account = Account.objects.filter(book=request.book, pk=data["account_id"]).exclude_budget_buckets().first()
        if account is None:
            raise ValidationError({"account_id": [_("Unknown account.")]})
        if account.is_hidden != data["is_hidden"]:
            account.is_hidden = data["is_hidden"]
            account.save(update_fields=["is_hidden", "updated_at"])
        return Response(SetHiddenSerializer({"account_id": account.pk, "is_hidden": account.is_hidden}).data)


# =============================================================================
# Accounts
# =============================================================================


def _date_range(request, book):
    """The range from `?start_date&end_date`, else this year."""
    query = DateRangeQuerySerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    if query.validated_data:
        return query.validated_data["start_date"], query.validated_data["end_date"]
    today = date.today()
    return today.replace(month=1, day=1), today


@_crud_schema("accounts_accounts", "account")
class AccountViewSet(viewsets.ModelViewSet):
    """
    The book's accounts (never budget buckets: they belong to the app). The type is
    the group's; an account's name is unique within its type.
    """

    permission_classes = [BookModelAccessPermissions]
    serializer_class = ManagedAccountSerializer
    pagination_class = None
    queryset = Account.objects.none()  # for drf-spectacular schema generation

    def get_queryset(self):
        queryset = (
            Account.objects.filter(book=self.request.book)
            .exclude_budget_buckets()
            .select_related("account_group", "institution")
            .with_balance()
        )
        if self.action == "list":
            account_type = self.request.query_params.get("account_type")
            if account_type:
                queryset = queryset.filter(account_group__account_type=account_type)
            group = self.request.query_params.get("account_group")
            if group:
                queryset = queryset.filter(account_group_id=group if group.isdigit() else None)
        return queryset

    def get_serializer_class(self):
        return ManagedAccountDetailSerializer if self.action == "retrieve" else ManagedAccountSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if getattr(self.request, "book", None) is not None and self.action in ("list", "retrieve"):
            from apps.budget.services import goal_left_by_account

            context["goal_left"] = goal_left_by_account(self.request.book)
        return context

    @extend_schema(
        operation_id="accounts_accounts_list",
        tags=TAGS,
        parameters=[
            OpenApiParameter("account_type", str, enum=[value for value, _label in ACCOUNT_TYPE_CHOICES]),
            OpenApiParameter("account_group", int),
        ],
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def perform_create(self, serializer):
        group = serializer.validated_data["account_group"]
        serializer.save(book=self.request.book, sort_order=board.next_account_sort_order(self.request.book, group))

    def perform_destroy(self, instance):
        reason = delete_account(instance)
        if reason:
            _refuse(reason)

    @extend_schema(
        operation_id="accounts_accounts_activity",
        tags=TAGS,
        parameters=DATE_RANGE_PARAMETERS,
        responses=AccountActivitySerializer,
    )
    @action(detail=True, methods=["get"], serializer_class=AccountActivitySerializer)
    def activity(self, request, team_slug=None, book_slug=None, pk=None):
        """
        The account's transactions over a range, signed so positive means its
        balance (or total) grew, with a running balance for balance accounts.
        """
        from apps.reports.services import ReportService

        account = self.get_object()
        start_date, end_date = _date_range(request, request.book)
        data = ReportService(request.book).get_account_activity(account, start_date, end_date)
        data.update(start_date=start_date, end_date=end_date)
        return Response(AccountActivitySerializer(data).data)

    @extend_schema(
        operation_id="accounts_accounts_charts",
        tags=TAGS,
        parameters=DATE_RANGE_PARAMETERS,
        responses=AccountChartsSerializer,
    )
    @action(detail=True, methods=["get"], serializer_class=AccountChartsSerializer)
    def charts(self, request, team_slug=None, book_slug=None, pk=None):
        """The balance-over-time chart (balance accounts) and the budget chart (budgeted categories, goals)."""
        from apps.reports.services import ReportService

        account = self.get_object()
        start_date, end_date = _date_range(request, request.book)
        service = ReportService(request.book)
        activity = service.get_account_activity(account, start_date, end_date)
        return Response(account_charts_payload(service, account, activity, start_date, end_date))


def account_charts_payload(service, account, activity, start_date, end_date):
    """
    The `GET …/accounts/api/accounts/{id}/charts/` body, from the account's
    `get_account_activity` over the range. The account page builds that activity for
    its own table and embeds this body, so its charts don't fetch it again.
    """
    from apps.reports.services import ReportService

    balance = ReportService.build_balance_chart_data(activity, start_date, end_date)
    budget_chart = service.get_budget_vs_actual_chart_data(account, start_date, end_date)
    return AccountChartsSerializer({"balance": balance, "budget": budget_chart}).data


# =============================================================================
# Groups, payees, institutions
# =============================================================================


@_crud_schema("accounts_groups", "group")
class AccountGroupViewSet(viewsets.ModelViewSet):
    """
    The book's account groups (never the budget group). A group's type is fixed
    while it holds accounts; a system group or one holding accounts can't be deleted.
    """

    permission_classes = [BookModelAccessPermissions]
    serializer_class = ManagedAccountGroupSerializer
    pagination_class = None
    queryset = AccountGroup.objects.none()  # for drf-spectacular schema generation

    def get_queryset(self):
        return (
            AccountGroup.objects.filter(book=self.request.book)
            .exclude(account_type=ACCOUNT_TYPE_BUDGET)
            .annotate(account_count=Count("accounts"))
            .order_by("sort_order", "name")
        )

    def perform_create(self, serializer):
        account_type = serializer.validated_data["account_type"]
        serializer.save(book=self.request.book, sort_order=board.next_group_sort_order(self.request.book, account_type))

    def perform_destroy(self, instance):
        reason = group_delete_blocked_reason(instance)
        if reason:
            _refuse(reason)
        instance.delete()


@_crud_schema("accounts_payees", "payee")
class PayeeViewSet(viewsets.ModelViewSet):
    """The book's payees, with how often their transactions count. One on a transaction can't be deleted."""

    permission_classes = [BookModelAccessPermissions]
    serializer_class = ManagedPayeeSerializer
    pagination_class = None
    queryset = Payee.objects.none()  # for drf-spectacular schema generation

    def get_queryset(self):
        return payee_usage(Payee.objects.filter(book=self.request.book)).order_by("name")

    def perform_create(self, serializer):
        serializer.save(book=self.request.book)

    def perform_destroy(self, instance):
        reason = payee_delete_blocked_reason(instance)
        if reason:
            _refuse(reason)
        instance.delete()


@_crud_schema("accounts_institutions", "institution")
class InstitutionViewSet(viewsets.ModelViewSet):
    """The book's institutions. Deleting one keeps its accounts, unlinked."""

    permission_classes = [BookModelAccessPermissions]
    serializer_class = ManagedInstitutionSerializer
    pagination_class = None
    queryset = Institution.objects.none()  # for drf-spectacular schema generation

    def get_queryset(self):
        return (
            Institution.objects.filter(book=self.request.book)
            .annotate(account_count=Count("accounts"))
            .order_by("name")
        )

    def perform_create(self, serializer):
        serializer.save(book=self.request.book)

    @extend_schema(operation_id="accounts_institutions_accounts_retrieve", tags=TAGS, methods=["GET"])
    @extend_schema(
        operation_id="accounts_institutions_accounts_update",
        tags=TAGS,
        methods=["POST"],
        request=InstitutionAccountsUpdateSerializer,
        responses=InstitutionAccountsSerializer,
    )
    @action(detail=True, methods=["get", "post"], serializer_class=InstitutionAccountsSerializer)
    def accounts(self, request, team_slug=None, book_slug=None, pk=None):
        """
        The checklist of accounts an institution can hold (this book's assets and
        liabilities). POST names every account that should be held here: a listed
        account is linked (moving it from any other institution), an unlisted one
        linked here is unlinked. Accounts the checklist doesn't offer are never touched.
        """
        institution = self.get_object()
        if request.method == "POST":
            update = InstitutionAccountsUpdateSerializer(data=request.data)
            update.is_valid(raise_exception=True)
            set_institution_accounts(institution, update.validated_data["account_ids"])
        sections = institution_account_sections(institution)
        return Response(InstitutionAccountsSerializer({"sections": sections}).data)
