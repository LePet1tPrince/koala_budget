"""
Views for bank_feed app.
Provides API endpoints for imported transactions.
"""

from datetime import datetime
from decimal import Decimal

from django.db import transaction
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.models import Account, Payee
from apps.accounts.serializers import AccountSerializer, PayeeSerializer
from apps.journal.models import JournalEntry, JournalLine
from apps.teams.decorators import login_and_team_required
from apps.teams.permissions import TeamModelAccessPermissions

from .models import BankTransaction
from .serializers import BankTransactionSerializer, CategorizeTransactionsRequestSerializer


@extend_schema_view(
    list=extend_schema(
        operation_id="bank_feed_transactions_list",
        tags=["bank-feed"],
        parameters=[
            OpenApiParameter(
                name="source",
                type=str,
                location=OpenApiParameter.QUERY,
                description="Filter by source (plaid, csv, manual)",
                required=False,
            ),
            OpenApiParameter(
                name="account",
                type=int,
                location=OpenApiParameter.QUERY,
                description="Filter by ledger account ID",
                required=False,
            ),
            OpenApiParameter(
                name="date_from",
                type=str,
                location=OpenApiParameter.QUERY,
                description="Filter by date (from), format: YYYY-MM-DD",
                required=False,
            ),
            OpenApiParameter(
                name="date_to",
                type=str,
                location=OpenApiParameter.QUERY,
                description="Filter by date (to), format: YYYY-MM-DD",
                required=False,
            ),
            OpenApiParameter(
                name="is_categorized",
                type=bool,
                location=OpenApiParameter.QUERY,
                description="Filter by categorization status",
                required=False,
            ),
            OpenApiParameter(
                name="pending",
                type=bool,
                location=OpenApiParameter.QUERY,
                description="Filter by pending status",
                required=False,
            ),
        ],
    ),
    retrieve=extend_schema(
        operation_id="bank_feed_transactions_retrieve",
        tags=["bank-feed"],
    ),
)
class BankTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for BankTransaction model.
    Provides read-only access to imported transactions from all sources (Plaid, CSV, manual).
    """

    serializer_class = BankTransactionSerializer
    permission_classes = [TeamModelAccessPermissions]

    def get_queryset(self):
        queryset = BankTransaction.objects.filter(team=self.request.team).select_related(
            "plaid_account",
            "plaid_account__account",
            "journal_entry",
            "account",
        )

        # Apply filters from query params
        params = self.request.query_params

        # Filter by source
        source = params.get("source")
        if source:
            queryset = queryset.filter(source=source)

        # Filter by account (plaid_account__account_id)
        account = params.get("account")
        if account:
            if source == BankTransaction.SOURCE_PLAID:
                queryset = queryset.filter(plaid_account__account_id=account)
            else:
                queryset = queryset.filter(account_id=account)

        # Filter by date range
        date_from = params.get("date_from")
        if date_from:
            try:
                date_from = datetime.strptime(date_from, "%Y-%m-%d").date()
                queryset = queryset.filter(date__gte=date_from)
            except ValueError:
                pass  # Ignore invalid date format

        date_to = params.get("date_to")
        if date_to:
            try:
                date_to = datetime.strptime(date_to, "%Y-%m-%d").date()
                queryset = queryset.filter(date__lte=date_to)
            except ValueError:
                pass  # Ignore invalid date format

        # Filter by categorization status
        is_categorized = params.get("is_categorized")
        if is_categorized is not None:
            if is_categorized.lower() == "true":
                queryset = queryset.filter(journal_entry__isnull=False)
            elif is_categorized.lower() == "false":
                queryset = queryset.filter(journal_entry__isnull=True)

        # Filter by pending status
        pending = params.get("pending")
        if pending is not None:
            if pending.lower() == "true":
                queryset = queryset.filter(pending=True)
            elif pending.lower() == "false":
                queryset = queryset.filter(pending=False)

        return queryset

    @extend_schema(
        operation_id="bank_feed_transactions_categorize",
        tags=["bank-feed"],
        request=CategorizeTransactionsRequestSerializer,
        responses={204: None},
    )
    @action(detail=False, methods=["post"])
    def categorize(self, request, team_slug=None):
        """
        Categorize one or more bank transactions.
        Creates journal entries linking the bank account to the category account.

        Body:
        - rows: List of transaction objects with 'id' field
        - category_account_id: ID of the category account
        """
        rows = request.data.get("rows", [])
        category_account_id = request.data.get("category_account_id")

        if not rows or not category_account_id:
            return Response(
                {"error": "rows and category_account_id are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Verify category account exists and belongs to team
        try:
            category_account = Account.for_team.get(account_id=category_account_id)
        except Account.DoesNotExist:
            return Response(
                {"error": "Category account not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Process each row
        try:
            for row in rows:
                tx_id = row.get("id")
                if tx_id:
                    self._create_journal_from_bank_transaction(
                        transaction_id=tx_id,
                        category_account=category_account,
                        team=request.team,
                    )
        except ValueError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(status=status.HTTP_204_NO_CONTENT)

    @transaction.atomic
    def _create_journal_from_bank_transaction(self, transaction_id: int, category_account: Account, team):
        """
        Create a JournalEntry from a BankTransaction.
        Links the transaction to the journal entry.

        Raises:
            ValueError: If the transaction doesn't have a linked account
        """
        # Get the bank transaction
        bank_tx = BankTransaction.objects.select_related(
            "plaid_account",
            "plaid_account__account",
        ).get(id=transaction_id, team=team)

        # Get the bank account (either from plaid_account mapping or direct account field)
        if bank_tx.source == BankTransaction.SOURCE_PLAID:
            if not bank_tx.plaid_account or not bank_tx.plaid_account.account:
                raise ValueError(
                    f"Cannot categorize transaction: Plaid account is not mapped to a ledger account."
                )
            bank_account = bank_tx.plaid_account.account
        else:
            # For non-Plaid sources, we need an account field on BankTransaction
            # Check if there's a direct account link
            if hasattr(bank_tx, "account") and bank_tx.account:
                bank_account = bank_tx.account
            elif bank_tx.plaid_account and bank_tx.plaid_account.account:
                bank_account = bank_tx.plaid_account.account
            else:
                raise ValueError("Cannot categorize transaction: No bank account linked.")

        # Create journal entry
        journal_entry = JournalEntry.objects.create(
            team=team,
            entry_date=bank_tx.date,
            description=bank_tx.description,
            source=JournalEntry.SOURCE_IMPORT,
            status=JournalEntry.STATUS_DRAFT,
        )

        # Calculate amounts (Plaid convention: positive = outflow, negative = inflow)
        amount = abs(bank_tx.amount)
        is_inflow = bank_tx.amount < 0

        # Create journal lines
        if is_inflow:
            # Money coming in: debit bank account, credit category
            JournalLine.objects.create(
                journal_entry=journal_entry,
                team=team,
                account=bank_account,
                dr_amount=amount,
                cr_amount=Decimal("0"),
            )
            JournalLine.objects.create(
                journal_entry=journal_entry,
                team=team,
                account=category_account,
                dr_amount=Decimal("0"),
                cr_amount=amount,
            )
        else:
            # Money going out: credit bank account, debit category
            JournalLine.objects.create(
                journal_entry=journal_entry,
                team=team,
                account=bank_account,
                dr_amount=Decimal("0"),
                cr_amount=amount,
            )
            JournalLine.objects.create(
                journal_entry=journal_entry,
                team=team,
                account=category_account,
                dr_amount=amount,
                cr_amount=Decimal("0"),
            )

        # Link the bank transaction to the journal entry
        bank_tx.journal_entry = journal_entry
        bank_tx.save()

        return journal_entry


# Template Views


@login_and_team_required
def bank_feed_home(request, team_slug):
    """
    Main bank feed page view.
    Displays accounts with bank feeds and bank transactions table.
    """
    # Get accounts with bank feeds
    accounts_with_feeds = Account.for_team.filter(has_feed=True).select_related("account_group").order_by("name")

    # Serialize accounts for React
    accounts_data = AccountSerializer(accounts_with_feeds, many=True).data

    # Get all accounts and payees for dropdowns
    all_accounts = Account.for_team.all().order_by("account_number")
    all_payees = Payee.for_team.all().order_by("name")

    all_accounts_data = AccountSerializer(all_accounts, many=True).data
    all_payees_data = PayeeSerializer(all_payees, many=True).data

    # API URLs
    api_urls = {
        "transactions_list": f"/a/{team_slug}/bank-feed/api/transactions/",
        "transactions_detail": f"/a/{team_slug}/bank-feed/api/transactions/{{id}}/",
    }

    return render(
        request,
        "bank_feed/bank_feed_home.html",
        {
            "active_tab": "bank-feed",
            "page_title": _("Bank Feed | {team}").format(team=request.team),
            "accounts": accounts_data,
            "all_accounts": all_accounts_data,
            "all_payees": all_payees_data,
            "api_urls": api_urls,
            "team_slug": team_slug,
        },
    )