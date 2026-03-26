"""
E2E tests for the Reports section.

The reports home page is Django-template rendered. The income statement,
balance sheet, and net worth trend pages are also Django-template rendered
with small React components for date pickers (Vite dev server required for
interactive date filtering, but the page structure itself is server-rendered).

Covers: reports home navigation links, income statement with seeded data,
export CSV button presence.
"""

import pytest
from playwright.sync_api import Page

from apps.accounts.models import ACCOUNT_TYPE_EXPENSE
from e2e.factories import (
    AccountFactory,
    AccountGroupFactory,
    IncomeAccountGroupFactory,
    JournalEntryFactory,
    JournalLineFactory,
)
from e2e.pages.reports import ReportsPage


@pytest.mark.django_db(transaction=True)
def test_reports_home_shows_all_report_links(authenticated_page: Page, live_server, team):
    """The reports home page shows links to all three main reports."""
    reports = ReportsPage(authenticated_page, live_server.url)
    reports.goto_home(team.slug)

    assert reports.has_income_statement_link()
    assert reports.has_balance_sheet_link()
    assert reports.has_net_worth_trend_link()


@pytest.mark.django_db(transaction=True)
def test_income_statement_link_navigates_to_report(authenticated_page: Page, live_server, team):
    """Clicking 'View Report' on the Income Statement card navigates to the report."""
    reports = ReportsPage(authenticated_page, live_server.url)
    reports.goto_home(team.slug)
    reports.click_income_statement()

    assert f"/a/{team.slug}/reports/income-statement/" in authenticated_page.url


@pytest.mark.django_db(transaction=True)
def test_income_statement_shows_summary_with_data(authenticated_page: Page, live_server, team):
    """Income statement renders summary stats and tables when there is journal data."""
    income_group = IncomeAccountGroupFactory(team=team)
    expense_group = AccountGroupFactory(team=team, account_type=ACCOUNT_TYPE_EXPENSE)
    income_acct = AccountFactory(team=team, account_group=income_group, account_number="4001")
    expense_acct = AccountFactory(team=team, account_group=expense_group, account_number="5001")

    entry = JournalEntryFactory(team=team, description="Consulting Invoice", status="posted")
    JournalLineFactory(team=team, journal_entry=entry, account=income_acct, cr_amount="2000.00")
    JournalLineFactory(team=team, journal_entry=entry, account=expense_acct, dr_amount="2000.00")

    reports = ReportsPage(authenticated_page, live_server.url)
    reports.goto_income_statement(team.slug)

    assert reports.has_summary()
    assert reports.has_income_table()
    assert reports.has_expenses_table()


@pytest.mark.django_db(transaction=True)
def test_income_statement_export_csv_button_present(authenticated_page: Page, live_server, team):
    """The Export CSV button is always visible on the income statement page."""
    reports = ReportsPage(authenticated_page, live_server.url)
    reports.goto_income_statement(team.slug)

    assert reports.has_export_btn()


@pytest.mark.django_db(transaction=True)
def test_reports_home_navigates_to_balance_sheet(authenticated_page: Page, live_server, team):
    """The balance sheet link navigates to the balance sheet page."""
    reports = ReportsPage(authenticated_page, live_server.url)
    reports.goto_home(team.slug)
    authenticated_page.locator("[data-testid='report-link-balance-sheet']").click()

    authenticated_page.wait_for_url(f"**/a/{team.slug}/reports/balance-sheet/", timeout=10_000)
    assert f"/a/{team.slug}/reports/balance-sheet/" in authenticated_page.url
