import csv
from datetime import date, datetime
from decimal import Decimal
from io import StringIO

from django.http import HttpResponse

from .services import ReportService


def _decimal_str(value):
    """Format a Decimal for CSV output."""
    if value is None:
        return "0.00"
    return f"{value:.2f}"


def export_income_statement_csv(team, start_date, end_date):
    """Export income statement data as a CSV HttpResponse."""
    service = ReportService(team)
    data = service.get_income_statement_data(start_date, end_date)

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="income_statement_{start_date}_{end_date}.csv"'
    )

    writer = csv.writer(response)
    writer.writerow(["Income Statement"])
    writer.writerow([f"Period: {start_date} to {end_date}"])
    writer.writerow([])

    # Income section
    writer.writerow(["INCOME"])
    writer.writerow(["Account Number", "Account Name", "Amount"])
    for item in data["income"]:
        writer.writerow([
            item["account"].account_number,
            item["account"].name,
            _decimal_str(item["amount"]),
        ])
    writer.writerow(["", "Total Income", _decimal_str(data["total_income"])])
    writer.writerow([])

    # Expense section
    writer.writerow(["EXPENSES"])
    writer.writerow(["Account Number", "Account Name", "Amount"])
    for item in data["expenses"]:
        writer.writerow([
            item["account"].account_number,
            item["account"].name,
            _decimal_str(item["amount"]),
        ])
    writer.writerow(["", "Total Expenses", _decimal_str(data["total_expenses"])])
    writer.writerow([])

    # Net profit
    writer.writerow(["", "Net Profit", _decimal_str(data["net_profit"])])

    return response


def export_balance_sheet_csv(team, as_of_date):
    """Export balance sheet data as a CSV HttpResponse."""
    service = ReportService(team)
    data = service.get_balance_sheet_data(as_of_date)

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="balance_sheet_{as_of_date}.csv"'
    )

    writer = csv.writer(response)
    writer.writerow(["Balance Sheet"])
    writer.writerow([f"As of: {as_of_date}"])
    writer.writerow([])

    # Assets
    writer.writerow(["ASSETS"])
    writer.writerow(["Account Number", "Account Name", "Balance"])
    for item in data["assets"]:
        writer.writerow([
            item["account"].account_number,
            item["account"].name,
            _decimal_str(item["amount"]),
        ])
    writer.writerow(["", "Total Assets", _decimal_str(data["total_assets"])])
    writer.writerow([])

    # Liabilities
    writer.writerow(["LIABILITIES"])
    writer.writerow(["Account Number", "Account Name", "Balance"])
    for item in data["liabilities"]:
        writer.writerow([
            item["account"].account_number,
            item["account"].name,
            _decimal_str(item["amount"]),
        ])
    writer.writerow(["", "Total Liabilities", _decimal_str(data["total_liabilities"])])
    writer.writerow([])

    # Equity
    writer.writerow(["EQUITY"])
    writer.writerow(["Account Number", "Account Name", "Balance"])
    for item in data["equity"]:
        writer.writerow([
            item["account"].account_number,
            item["account"].name,
            _decimal_str(item["amount"]),
        ])
    writer.writerow(["", "Total Equity", _decimal_str(data["total_equity"])])
    writer.writerow([])

    # Net worth
    writer.writerow(["", "Net Worth", _decimal_str(data["net_worth"])])

    return response


def export_account_activity_csv(team, account, start_date, end_date):
    """Export account activity data as a CSV HttpResponse."""
    service = ReportService(team)
    data = service.get_account_activity(account, start_date, end_date)

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="account_activity_{account.account_number}_{start_date}_{end_date}.csv"'
    )

    writer = csv.writer(response)
    writer.writerow([f"Account Activity: {account.name} ({account.account_number})"])
    writer.writerow([f"Period: {start_date} to {end_date}"])
    writer.writerow([])

    writer.writerow(["Date", "Payee", "Description", "Amount"])
    for txn in data["transactions"]:
        writer.writerow([
            txn["date"].isoformat(),
            txn["payee"],
            txn["memo"],
            _decimal_str(txn["amount"]),
        ])
    writer.writerow([])
    writer.writerow(["", "", "Total", _decimal_str(data["total"])])

    return response


def export_transactions_csv(team, start_date=None, end_date=None):
    """Export all journal entries and lines as a CSV HttpResponse."""
    from apps.journal.models import JournalEntry

    queryset = JournalEntry.objects.filter(team=team).select_related("payee").prefetch_related(
        "lines__account", "lines__account__account_group"
    ).order_by("entry_date")

    if start_date:
        queryset = queryset.filter(entry_date__gte=start_date)
    if end_date:
        queryset = queryset.filter(entry_date__lte=end_date)

    filename_parts = ["transactions"]
    if start_date:
        filename_parts.append(str(start_date))
    if end_date:
        filename_parts.append(str(end_date))

    response = HttpResponse(content_type="text/csv")
    filename = "_".join(filename_parts) + ".csv"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    writer.writerow([
        "Entry ID", "Date", "Payee", "Description", "Source", "Status",
        "Account Number", "Account Name", "Account Type",
        "Debit", "Credit",
    ])

    for entry in queryset:
        for line in entry.lines.all():
            writer.writerow([
                entry.id,
                entry.entry_date.isoformat(),
                entry.payee.name if entry.payee else "",
                entry.description,
                entry.get_source_display(),
                entry.get_status_display(),
                line.account.account_number,
                line.account.name,
                line.account.account_group.get_account_type_display() if hasattr(line.account.account_group, "get_account_type_display") else line.account.account_group.account_type,
                _decimal_str(line.dr_amount),
                _decimal_str(line.cr_amount),
            ])

    return response
