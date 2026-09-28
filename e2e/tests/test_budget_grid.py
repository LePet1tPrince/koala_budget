"""
E2E for the multi-month budget grid: what a cell keeps when you leave it, and
the in-page dialog that replaces the browser's "leave site?" prompt.

Requires the Vite dev server (the grid is React).
"""

from datetime import date
from decimal import Decimal

import pytest
from playwright.sync_api import Page, expect

from apps.accounts.models import ACCOUNT_TYPE_EXPENSE
from apps.budget.models import Budget
from e2e.factories import AccountFactory, AccountGroupFactory


def _grid_url(live_server, book):
    return f"{live_server.url}/a/{book.team.slug}/{book.slug}/budget/grid/?start={date.today().year}-01-01"


def _cell(page: Page, name: str, month: date):
    return page.get_by_label(f"{name} {month.strftime('%b %Y')}", exact=True)


@pytest.fixture
def zed_category(team):
    group = AccountGroupFactory(team=team, account_type=ACCOUNT_TYPE_EXPENSE)
    return AccountFactory(team=team, account_group=group, name="Zed Groceries")


@pytest.mark.django_db(transaction=True)
def test_grid_cell_drops_what_is_not_an_amount(
    requires_vite, authenticated_page: Page, live_server, team, zed_category
):
    page = authenticated_page
    page.goto(_grid_url(live_server, team.default_book))
    jan, feb = date(date.today().year, 1, 1), date(date.today().year, 2, 1)
    cell = _cell(page, "Zed Groceries", jan)

    cell.fill("jjj")
    cell.press("Tab")
    expect(cell).to_have_value("")
    expect(page.get_by_test_id("budget-grid-save-bar")).to_have_count(0)

    cell.fill("12abc")
    cell.press("Tab")
    expect(cell).to_have_value("12")

    cell.fill("10+5x2")
    cell.press("Tab")
    expect(cell).to_have_value("20.00")

    # Garbage typed over a value goes back to that value, not to blank.
    other = _cell(page, "Zed Groceries", feb)
    other.fill("75")
    other.press("Tab")
    other.fill("abc")
    other.press("Tab")
    expect(other).to_have_value("75")


@pytest.mark.django_db(transaction=True)
def test_leaving_with_unsaved_changes_asks_in_page(
    requires_vite, authenticated_page: Page, live_server, team, zed_category
):
    page = authenticated_page
    native = []
    page.on("dialog", lambda d: (native.append(d.message), d.dismiss()))
    page.goto(_grid_url(live_server, team.default_book))
    jan = date(date.today().year, 1, 1)

    cell = _cell(page, "Zed Groceries", jan)
    cell.fill("150")
    cell.press("Tab")

    dialog = page.get_by_test_id("budget-grid-leave-dialog")
    page.get_by_role("link", name="Back to Budget").click()
    expect(dialog).to_be_visible()
    page.get_by_test_id("budget-grid-leave-cancel").click()
    expect(dialog).to_be_hidden()
    assert "/budget/grid/" in page.url

    page.get_by_role("link", name="Back to Budget").click()
    page.get_by_test_id("budget-grid-leave-save").click()
    page.wait_for_url(lambda url: "/grid/" not in url)

    assert native == []
    saved = Budget.objects.get(book=team.default_book, category=zed_category, month=jan)
    assert saved.budget_amount == Decimal("150.00")
