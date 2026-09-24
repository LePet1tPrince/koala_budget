"""
E2E for goals as envelopes (docs/goals-envelopes-plan.md §7).

Categorizing a purchase to a goal in categorize mode is spending from the goal:
the goal card shows it spent, Unassigned doesn't move, and the income statement
lists it under Goal spending rather than as an expense.

Requires the Vite dev server (categorize mode is React), like test_categorize.py.
"""

from datetime import date
from decimal import Decimal

import pytest
from playwright.sync_api import Page, expect

from apps.bank_feed.models import BankTransaction
from apps.budget.models import Goal, GoalAllocation
from e2e.factories import AccountGroupFactory, AssetAccountFactory, JournalEntryFactory, JournalLineFactory
from e2e.pages.budget import BudgetPage
from e2e.pages.categorize import CategorizePage
from e2e.pages.reports import ReportsPage


@pytest.fixture
def goal_fixture(team):
    """A funded checking account, a "Zed Car" goal with $1,000 in it, and one uncategorized $250 purchase."""
    today = date.today()
    month = today.replace(day=1)
    checking = AssetAccountFactory(
        team=team, account_group=AccountGroupFactory(team=team, account_type="asset"), has_feed=True
    )
    opening = AssetAccountFactory(team=team, account_group=AccountGroupFactory(team=team, account_type="goal"))
    entry = JournalEntryFactory(team=team, entry_date=month)
    JournalLineFactory(team=team, journal_entry=entry, account=checking, dr_amount=Decimal("5000.00"))
    JournalLineFactory(team=team, journal_entry=entry, account=opening, cr_amount=Decimal("5000.00"))

    goal = Goal.objects.create(book=team.default_book, name="Zed Car", target_amount=Decimal("3000.00"))
    GoalAllocation.objects.create(book=team.default_book, goal=goal, month=month, amount=Decimal("1000.00"))
    row = BankTransaction.objects.create(
        book=team.default_book,
        account=checking,
        posted_date=today,
        amount=Decimal("250.00"),
        description="CAR DEALER DEPOSIT",
        merchant_name="Car Dealer",
        source=BankTransaction.SOURCE_CSV,
    )
    return {"goal": goal, "row": row, "month": month}


@pytest.mark.django_db(transaction=True)
def test_categorizing_a_purchase_to_a_goal_spends_from_it(
    requires_vite, authenticated_page: Page, live_server, team, goal_fixture
):
    budget = BudgetPage(authenticated_page, live_server.url)
    budget.goto_goals(team.default_book, style="summit")
    assert budget.goal_spent("Zed Car") == "$0.00"
    pill_before = budget.unassigned_pill_value()

    categorize = CategorizePage(authenticated_page, live_server.url)
    categorize.goto(team.default_book)
    categorize.search("zed car")
    assert categorize.active_row_name() == "Goal: Zed Car"
    # The picker shows what the goal holds.
    expect(authenticated_page.locator("[data-testid='goal-left']").first).to_contain_text("$1,000.00 left")
    categorize.press("Enter")

    row = goal_fixture["row"]
    for _ in range(50):
        row.refresh_from_db()
        if row.journal_entry_id:
            break
        authenticated_page.wait_for_timeout(100)
    assert row.journal_entry.lines.filter(account=goal_fixture["goal"].account, dr_amount=Decimal("250.00")).exists()

    budget.goto_goals(team.default_book, style="summit")
    assert budget.goal_spent("Zed Car") == "$250.00"
    assert budget.goal_left("Zed Car").startswith("$750.00")
    assert budget.goal_state("Zed Car") == "spending"
    # Spending money set aside for it moves nothing.
    assert budget.unassigned_pill_value() == pill_before

    reports = ReportsPage(authenticated_page, live_server.url)
    reports.goto_income_statement(team.default_book)
    assert reports.goal_spending_rows() == ["Zed Car"]
