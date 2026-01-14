from django.shortcuts import render
from django.utils.translation import gettext_lazy as _

from apps.teams.decorators import login_and_team_required

from .forms import BalanceSheetForm, IncomeStatementForm, NetWorthTrendForm
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
    form = IncomeStatementForm(request.GET or None)

    report_data = None
    start_date = None
    end_date = None

    if form.is_valid():
        start_date, end_date = form.get_date_range()
        report_data = service.get_income_statement_data(start_date, end_date)

    return render(
        request,
        "reports/income_statement.html",
        {
            "active_tab": "reports",
            "page_title": _("Income Statement"),
            "form": form,
            "report_data": report_data,
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
    form = BalanceSheetForm(request.GET or None)

    report_data = None
    as_of_date = None

    if form.is_valid():
        as_of_date = form.cleaned_data['as_of_date']
        report_data = service.get_balance_sheet_data(as_of_date)

    return render(
        request,
        "reports/balance_sheet.html",
        {
            "active_tab": "reports",
            "page_title": _("Balance Sheet"),
            "form": form,
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
    form = IncomeStatementForm(request.GET or None)

    account = None
    report_data = None
    start_date = None
    end_date = None

    try:
        account = Account.objects.get(team=request.team, account_id=account_id)
    except Account.DoesNotExist:
        # Handle account not found
        pass

    if account and form.is_valid():
        start_date, end_date = form.get_date_range()
        report_data = service.get_account_activity(account, start_date, end_date)

    return render(
        request,
        "reports/account_activity.html",
        {
            "active_tab": "reports",
            "page_title": _("Account Activity"),
            "form": form,
            "account": account,
            "report_data": report_data,
            "start_date": start_date,
            "end_date": end_date,
        },
    )


@login_and_team_required
def net_worth_trend(request, team_slug):
    """
    Net Worth Trend report view.
    """
    service = ReportService(request.team)

    # Only bind form with GET data if there are query parameters (form submitted)
    # This prevents validation errors from showing on initial page load
    form_data = request.GET if request.GET else None
    form = NetWorthTrendForm(form_data)

    report_data = None
    start_date = None
    end_date = None

    # Only process form if it has been submitted (has GET data) and is valid
    if form_data and form.is_valid():
        start_date = form.cleaned_data['start_date']
        end_date = form.cleaned_data['end_date']
        report_data = service.get_net_worth_trend_data_by_date_range(start_date, end_date)

    return render(
        request,
        "reports/net_worth_trend.html",
        {
            "active_tab": "reports",
            "page_title": _("Net Worth Trend"),
            "form": form,
            "report_data": report_data,
            "start_date": start_date,
            "end_date": end_date,
        },
    )
