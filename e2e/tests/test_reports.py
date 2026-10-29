"""
E2E tests for the Reports section.

Reports are Monthly Review plus three server-rendered reports -- Income &
Spending, Net Worth, Budget & Goals -- with small React date pickers (Vite dev
server required for those, though the page structure is server-rendered).

Covers: reports home and the sidebar popout list exactly those four, Income &
Spending with seeded data, export CSV button presence.
"""

from datetime import date, timedelta

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
from e2e.pages.books import BookSettingsPage
from e2e.pages.reports import REPORT_KEYS, ReportsPage


@pytest.mark.django_db(transaction=True)
def test_reports_home_lists_the_four_reports(authenticated_page: Page, live_server, team):
    reports = ReportsPage(authenticated_page, live_server.url)
    reports.goto_home(team.default_book)

    assert reports.report_links() == list(REPORT_KEYS)


@pytest.mark.django_db(transaction=True)
def test_reports_popout_lists_the_four_reports(authenticated_page: Page, live_server, team):
    reports = ReportsPage(authenticated_page, live_server.url)
    reports.goto_home(team.default_book)

    authenticated_page.locator("aside [data-testid='nav-reports-toggle']").click()
    sidebar = authenticated_page.locator("aside")
    for testid in ("nav-monthly-review", "nav-report-spending", "nav-report-net-worth", "nav-report-budget-goals"):
        assert sidebar.locator(f"[data-testid='{testid}']").is_visible(), testid
    assert sidebar.locator("[data-testid^='nav-report-']").count() == 3


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "key, path",
    [("spending", "spending/"), ("net-worth", "net-worth/"), ("budget-goals", "budget-and-goals/")],
)
def test_reports_home_navigates_to_each_report(authenticated_page: Page, live_server, team, key, path):
    reports = ReportsPage(authenticated_page, live_server.url)
    reports.goto_home(team.default_book)
    reports.click_report(key)

    authenticated_page.wait_for_url(f"**{team.default_book.base_url}reports/{path}", timeout=10_000)


@pytest.mark.django_db(transaction=True)
def test_spending_shows_summary_with_data(authenticated_page: Page, live_server, team):
    """Income & Spending renders its stats and statement when there is journal data."""
    income_group = IncomeAccountGroupFactory(team=team)
    expense_group = AccountGroupFactory(team=team, account_type=ACCOUNT_TYPE_EXPENSE)
    income_acct = AccountFactory(team=team, account_group=income_group)
    expense_acct = AccountFactory(team=team, account_group=expense_group)

    entry = JournalEntryFactory(team=team, description="Consulting Invoice", status="posted")
    JournalLineFactory(team=team, journal_entry=entry, account=income_acct, cr_amount="2000.00")
    JournalLineFactory(team=team, journal_entry=entry, account=expense_acct, dr_amount="2000.00")

    reports = ReportsPage(authenticated_page, live_server.url)
    reports.goto_spending(team.default_book)

    assert reports.has_summary()
    assert reports.has_statement()
    assert reports.has_export_btn()


# ----------------------------------------------------------------------
# Default timeframe and typed dates
# ----------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_a_report_opens_on_the_books_default_timeframe(
    requires_vite, authenticated_page: Page, live_server, team, book
):
    """Set "Last month" in the book's settings and Income & Spending opens on last month."""
    settings_page = BookSettingsPage(authenticated_page, live_server.url)
    settings_page.goto(book)
    settings_page.set_report_timeframe("last_month")
    settings_page.save()

    last_month_end = date.today().replace(day=1) - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    reports = ReportsPage(authenticated_page, live_server.url)
    reports.goto_spending(book)

    def label(d):
        return f"{d:%b} {d.day}, {d.year}"

    assert reports.date_range_label() == f"{label(last_month_start)} – {label(last_month_end)}"
    assert f"start_date={last_month_start.isoformat()}" in authenticated_page.url


@pytest.mark.django_db(transaction=True)
def test_a_date_range_can_be_typed(requires_vite, authenticated_page: Page, live_server, team, book):
    """DDMMYYYY into the start box, Enter, the end box, Enter: the report reloads on that range."""
    reports = ReportsPage(authenticated_page, live_server.url)
    reports.goto_spending(book)
    reports.type_date_range("01022026", "28022026")

    assert "start_date=2026-02-01" in authenticated_page.url
    assert "end_date=2026-02-28" in authenticated_page.url
    assert reports.date_range_label() == "Feb 1, 2026 – Feb 28, 2026"


@pytest.mark.django_db(transaction=True)
def test_a_typed_date_that_does_not_exist_is_refused(requires_vite, authenticated_page: Page, live_server, team, book):
    reports = ReportsPage(authenticated_page, live_server.url)
    reports.goto_spending(book)

    assert "DDMMYYYY" in reports.typed_date_error("start", "31022026")
