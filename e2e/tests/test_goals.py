"""
E2E for goals as envelopes (docs/goals-envelopes-plan.md §7).

Categorizing a purchase to a goal in categorize mode is spending from the goal:
the goal card shows it spent, Unassigned doesn't move, and the income statement
lists it under Goal spending rather than as an expense.

Requires the Vite dev server (categorize mode is React), like test_categorize.py.
"""

from datetime import date, timedelta
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
    budget.goto_goals(team.default_book)
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

    budget.goto_goals(team.default_book)
    assert budget.goal_spent("Zed Car") == "$250.00"
    assert budget.goal_left("Zed Car").startswith("$750.00")
    assert budget.goal_state("Zed Car") == "spending"
    # Spending money set aside for it moves nothing.
    assert budget.unassigned_pill_value() == pill_before

    reports = ReportsPage(authenticated_page, live_server.url)
    reports.goto_income_statement(team.default_book)
    assert reports.goal_spending_rows() == ["Zed Car"]


# ---------------------------------------------------------------------------
# Goal-linked accounts (docs/goal-linked-accounts-plan.md)
# ---------------------------------------------------------------------------


def _money(text: str) -> Decimal:
    """ "$1,234.50" / "−$3.00" / "-$3.00" -> Decimal."""
    cleaned = text.replace("\u2212", "-").replace("$", "").replace(",", "").strip()
    return Decimal(cleaned)


@pytest.fixture
def savings_fixture(team):
    """Checking with $5,000 and "Zed Savings" with $1,200 (as of yesterday), both bank-feed accounts."""
    month = date.today() - timedelta(days=1)
    book = team.default_book
    cash = AccountGroupFactory(team=team, account_type="asset", name="Zed Cash")
    opening = AssetAccountFactory(team=team, account_group=AccountGroupFactory(team=team, account_type="goal"))
    checking = AssetAccountFactory(team=team, name="Zed Checking", account_group=cash, has_feed=True)
    savings = AssetAccountFactory(team=team, name="Zed Savings", account_group=cash, has_feed=True)
    for account, amount in ((checking, "5000.00"), (savings, "1200.00")):
        entry = JournalEntryFactory(team=team, entry_date=month)
        JournalLineFactory(team=team, journal_entry=entry, account=account, dr_amount=Decimal(amount))
        JournalLineFactory(team=team, journal_entry=entry, account=opening, cr_amount=Decimal(amount))
    return {"book": book, "checking": checking, "savings": savings}


@pytest.mark.django_db(transaction=True)
def test_link_an_account_from_the_goal_form(
    requires_vite, authenticated_page: Page, live_server, team, savings_fixture
):
    book = savings_fixture["book"]
    budget = BudgetPage(authenticated_page, live_server.url)
    budget.goto_goal_create(book)
    authenticated_page.locator("[name='name']").fill("Zed Rainy Day")
    authenticated_page.locator("[name='target_amount']").fill("10000")
    budget.tick_link_account("Zed Savings")

    # The preview counts the $1,200 already there.
    expect(budget.link_preview()).to_contain_text("Adds $1,200.00 to this goal")
    budget.submit_goal_form()
    authenticated_page.wait_for_url(f"**{book.base_url}budget/goals/", timeout=10_000)

    goal = Goal.objects.get(book=book, name="Zed Rainy Day")
    assert list(goal.account_links.values_list("account__name", flat=True)) == ["Zed Savings"]
    budget.goto_goals(book)
    assert budget.goal_card_links("Zed Rainy Day") == "Linked · Zed Savings"
    assert budget.goal_saved("Zed Rainy Day") == "$1,200.00"


@pytest.mark.django_db(transaction=True)
def test_a_transfer_into_a_linked_account_funds_the_goal(
    requires_vite, authenticated_page: Page, live_server, team, savings_fixture
):
    from apps.budget.models import GoalAccountLink

    book = savings_fixture["book"]
    goal = Goal.objects.create(book=book, name="Zed Rainy Day", target_amount=Decimal("10000.00"))
    GoalAccountLink.objects.create(
        book=book,
        goal=goal,
        account=savings_fixture["savings"],
        start_date=date.today(),
        include_starting_balance=False,
    )
    row = BankTransaction.objects.create(
        book=book,
        account=savings_fixture["checking"],
        posted_date=date.today(),
        amount=Decimal("300.00"),
        description="TRANSFER TO SAVINGS",
        source=BankTransaction.SOURCE_CSV,
    )

    budget = BudgetPage(authenticated_page, live_server.url)
    budget.goto_goals(book)
    assert budget.goal_saved("Zed Rainy Day") == "$0.00"
    pill_before = budget.unassigned_pill_value()

    categorize = CategorizePage(authenticated_page, live_server.url)
    categorize.goto(book)
    categorize.search("zed savings")
    assert categorize.active_row_name() == "Zed Savings"
    categorize.press("Enter")
    for _ in range(50):
        row.refresh_from_db()
        if row.journal_entry_id:
            break
        authenticated_page.wait_for_timeout(100)
    assert row.journal_entry_id

    budget.goto_goals(book)
    assert budget.goal_saved("Zed Rainy Day") == "$300.00"
    # Money set aside: Unassigned went down by the transfer.
    assert _money(budget.unassigned_pill_value()) == _money(pill_before) - Decimal("300.00")


@pytest.mark.django_db(transaction=True)
def test_change_the_outflow_setting_and_unlink(
    requires_vite, authenticated_page: Page, live_server, team, savings_fixture
):
    from django.utils import timezone

    from apps.budget.models import GoalAccountLink

    book = savings_fixture["book"]
    goal = Goal.objects.create(book=book, name="Zed Trip", target_amount=Decimal("3000.00"))
    link = GoalAccountLink.objects.create(
        book=book, goal=goal, account=savings_fixture["savings"], start_date=date.today()
    )
    # An older link is ended rather than dropped when unlinked.
    GoalAccountLink.objects.filter(pk=link.pk).update(created_at=timezone.now() - timedelta(days=3))

    budget = BudgetPage(authenticated_page, live_server.url)
    budget.goto(f"{book.base_url}budget/goals/{goal.pk}/edit/", wait_for="[data-testid='goal-form']")
    expect(budget.goal_link_row("Zed Savings").locator("[data-testid='goal-link-checkbox']")).to_be_checked()
    budget.choose_outflow("spend")
    budget.submit_goal_form()
    authenticated_page.wait_for_url(f"**/budget/goals/{goal.pk}/", timeout=10_000)
    expect(authenticated_page.locator("[data-testid='goal-outflow-setting']")).to_contain_text(
        "Count it as spent from the goal"
    )

    expect(budget.detail_links()).to_have_count(1)
    budget.unlink_first()
    expect(budget.detail_links()).to_have_count(0)
    link.refresh_from_db()
    assert link.end_date == date.today()
