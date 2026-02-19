from datetime import date, datetime
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _

from apps.teams.decorators import login_and_team_required

# Forms are no longer needed as we use React components with URL parameters
from .exports import (
    export_account_activity_csv,
    export_balance_sheet_csv,
    export_income_statement_csv,
    export_transactions_csv,
)
from .services import ReportService


@login_and_team_required
def reports_home(request, team_slug):
    """
    Reports home page with navigation to different reports.
    """
    return render(
        request,
        "reports/reports_home.html",
        {
            "active_tab": "reports",
            "page_title": _("Reports"),
        },
    )


@login_and_team_required
def income_statement(request, team_slug):
    """
    Income Statement (Profit & Loss) report view.
    """
    service = ReportService(request.team)

    report_data = None
    start_date = None
    end_date = None

    # Check for direct start_date and end_date parameters
    start_date_param = request.GET.get('start_date')
    end_date_param = request.GET.get('end_date')

    if start_date_param and end_date_param:
        # Parse dates directly from URL parameters
        try:
            start_date = datetime.strptime(start_date_param, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_param, '%Y-%m-%d').date()
        except ValueError:
            # Invalid date format, fall back to defaults
            today = date.today()
            start_date = today.replace(day=1)
            end_date = today
    else:
        # No parameters provided, set defaults for current month
        today = date.today()
        start_date = today.replace(day=1)
        end_date = today

    report_data = service.get_income_statement_data(start_date, end_date)

    sankey_data = None
    if report_data:
        sankey_data = {
            'income': [{'name': item['account'].name, 'amount': float(item['amount'])} for item in report_data['income']],
            'expenses': [{'name': item['account'].name, 'amount': float(item['amount'])} for item in report_data['expenses']],
            'net_profit': float(report_data['net_profit']),
        }

    return render(
        request,
        "reports/income_statement.html",
        {
            "active_tab": "reports",
            "page_title": _("Income Statement"),
            "report_data": report_data,
            "sankey_data": sankey_data,
            "start_date": start_date,
            "end_date": end_date,
        },
    )


@login_and_team_required
def balance_sheet(request, team_slug):
    """
    Balance Sheet report view.
    """
    service = ReportService(request.team)

    report_data = None
    as_of_date = None

    # Check for direct as_of_date parameter
    as_of_date_param = request.GET.get('as_of_date')

    if as_of_date_param:
        # Parse date directly from URL parameter
        try:
            as_of_date = datetime.strptime(as_of_date_param, '%Y-%m-%d').date()
            report_data = service.get_balance_sheet_data(as_of_date)
        except ValueError:
            # Invalid date format, fall back to today
            as_of_date = date.today()
            report_data = service.get_balance_sheet_data(as_of_date)
    else:
        # No parameter provided, set default to today
        as_of_date = date.today()
        report_data = service.get_balance_sheet_data(as_of_date)

    return render(
        request,
        "reports/balance_sheet.html",
        {
            "active_tab": "reports",
            "page_title": _("Balance Sheet"),
            "report_data": report_data,
            "as_of_date": as_of_date,
        },
    )


@login_and_team_required
def account_activity(request, team_slug, account_id):
    """
    Account activity drill-down view showing detailed transactions for a specific account.
    """
    from apps.accounts.models import Account

    service = ReportService(request.team)

    account = None
    report_data = None
    start_date = None
    end_date = None

    try:
        account = Account.objects.get(team=request.team, pk=account_id)
    except Account.DoesNotExist:
        # Handle account not found
        pass

    if account:
        # Check for direct start_date and end_date parameters
        start_date_param = request.GET.get('start_date')
        end_date_param = request.GET.get('end_date')

        if start_date_param and end_date_param:
            # Parse dates directly from URL parameters
            try:
                start_date = datetime.strptime(start_date_param, '%Y-%m-%d').date()
                end_date = datetime.strptime(end_date_param, '%Y-%m-%d').date()
            except ValueError:
                # Invalid date format, fall back to defaults
                today = date.today()
                start_date = today.replace(day=1)
                end_date = today
        else:
            # No parameters provided, set defaults for current month
            today = date.today()
            start_date = today.replace(day=1)
            end_date = today

        report_data = service.get_account_activity(account, start_date, end_date)

    # Determine back navigation based on source parameter
    source = request.GET.get('source')
    if source == 'budget':
        from django.urls import reverse
        back_url = reverse('budget:budget_home', args=[team_slug])
        if start_date:
            back_url += f'?month={start_date.isoformat()}'
        back_label = _("Back to Budget")
    else:
        from django.urls import reverse
        back_url = reverse('reports:income_statement', args=[team_slug])
        # Forward date params to income statement
        query_params = request.GET.copy()
        query_params.pop('source', None)
        if query_params:
            back_url += f'?{query_params.urlencode()}'
        back_label = _("Back to Summary")

    return render(
        request,
        "reports/account_activity.html",
        {
            "active_tab": "reports",
            "page_title": _("Account Activity"),
            "account": account,
            "report_data": report_data,
            "start_date": start_date,
            "end_date": end_date,
            "back_url": back_url,
            "back_label": back_label,
        },
    )


@login_and_team_required
def net_worth_trend(request, team_slug):
    """
    Net Worth Trend report view.
    """
    from datetime import timedelta

    service = ReportService(request.team)

    report_data = None
    start_date = None
    end_date = None

    # Check for direct start_month and end_month parameters (YYYY-MM format)
    start_month_param = request.GET.get('start_month')
    end_month_param = request.GET.get('end_month')

    if start_month_param and end_month_param:
        try:
            # Parse YYYY-MM format
            start_year, start_month_num = map(int, start_month_param.split('-'))
            end_year, end_month_num = map(int, end_month_param.split('-'))

            # Create start_date as first day of start month
            start_date = date(start_year, start_month_num, 1)

            # Create end_date as last day of end month
            if end_month_num == 12:
                end_date = date(end_year + 1, 1, 1) - timedelta(days=1)
            else:
                end_date = date(end_year, end_month_num + 1, 1) - timedelta(days=1)

            report_data = service.get_net_worth_trend_data_by_date_range(start_date, end_date)
        except (ValueError, IndexError):
            # Invalid format, fall back to defaults
            today = date.today()
            start_date = date(today.year - 1, today.month, 1)
            end_date = today
            report_data = service.get_net_worth_trend_data_by_date_range(start_date, end_date)
    else:
        # No parameters provided, set defaults for last 12 months
        today = date.today()
        start_date = date(today.year - 1, today.month, 1)
        end_date = today
        report_data = service.get_net_worth_trend_data_by_date_range(start_date, end_date)

    return render(
        request,
        "reports/net_worth_trend.html",
        {
            "active_tab": "reports",
            "page_title": _("Net Worth Trend"),
            "report_data": report_data,
            "start_date": start_date,
            "end_date": end_date,
        },
    )


# --- Export Views ---


def _parse_date_range(request):
    """Parse start_date and end_date from GET params, with defaults to current month."""
    today = date.today()
    start_date_param = request.GET.get("start_date")
    end_date_param = request.GET.get("end_date")
    try:
        start_date = datetime.strptime(start_date_param, "%Y-%m-%d").date() if start_date_param else today.replace(day=1)
        end_date = datetime.strptime(end_date_param, "%Y-%m-%d").date() if end_date_param else today
    except ValueError:
        start_date = today.replace(day=1)
        end_date = today
    return start_date, end_date


@login_and_team_required
def export_income_statement(request, team_slug):
    """Export income statement as CSV."""
    start_date, end_date = _parse_date_range(request)
    return export_income_statement_csv(request.team, start_date, end_date)


@login_and_team_required
def export_balance_sheet(request, team_slug):
    """Export balance sheet as CSV."""
    as_of_date_param = request.GET.get("as_of_date")
    try:
        as_of_date = datetime.strptime(as_of_date_param, "%Y-%m-%d").date() if as_of_date_param else date.today()
    except ValueError:
        as_of_date = date.today()
    return export_balance_sheet_csv(request.team, as_of_date)


@login_and_team_required
def export_account_activity_view(request, team_slug, account_id):
    """Export account activity as CSV."""
    from apps.accounts.models import Account

    try:
        account = Account.objects.get(team=request.team, pk=account_id)
    except Account.DoesNotExist:
        from django.http import Http404
        raise Http404("Account not found")

    start_date, end_date = _parse_date_range(request)
    return export_account_activity_csv(request.team, account, start_date, end_date)


@login_and_team_required
def export_transactions(request, team_slug):
    """Export all transactions as CSV."""
    start_date, end_date = _parse_date_range(request)
    return export_transactions_csv(request.team, start_date, end_date)
