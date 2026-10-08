"""
E2E for goal plans (docs/goal-plans-plan.md): the budget page's Goals section,
planned from each goal's monthly contribution and changeable month by month.

A goal with no linked account is given its plan outright; a linked goal holds the
planned money back from Unassigned until a transfer lands in the account, so the
transfer itself moves nothing.

Requires the Vite dev server (the budget page's autosave and categorize mode).
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from playwright.sync_api import Page, expect

from apps.bank_feed.models import BankTransaction
from apps.budget.models import Goal, GoalAccountLink, GoalPlan
from e2e.factories import AccountGroupFactory, AssetAccountFactory, JournalEntryFactory, JournalLineFactory
from e2e.pages.budget import BudgetPage
from e2e.pages.categorize import CategorizePage


def _money(text: str) -> Decimal:
    cleaned = text.replace("−", "-").replace("$", "").replace(",", "").strip()
    return Decimal(cleaned)


@pytest.fixture
def accounts(team):
    """Checking with $5,000 and "Zed Savings" with $1,200 (as of yesterday), both bank-feed accounts."""
    day = date.today() - timedelta(days=1)
    cash = AccountGroupFactory(team=team, account_type="asset", name="Zed Cash")
    opening = AssetAccountFactory(team=team, account_group=AccountGroupFactory(team=team, account_type="goal"))
    checking = AssetAccountFactory(team=team, name="Zed Checking", account_group=cash, has_feed=True)
    savings = AssetAccountFactory(team=team, name="Zed Savings", account_group=cash, has_feed=True)
    for account, amount in ((checking, "5000.00"), (savings, "1200.00")):
        entry = JournalEntryFactory(team=team, entry_date=day)
        JournalLineFactory(team=team, journal_entry=entry, account=account, dr_amount=Decimal(amount))
        JournalLineFactory(team=team, journal_entry=entry, account=opening, cr_amount=Decimal(amount))
    return {"book": team.default_book, "checking": checking, "savings": savings}


@pytest.mark.django_db(transaction=True)
def test_a_goal_is_planned_from_its_contribution_and_changed_for_a_month(
    requires_vite, authenticated_page: Page, live_server, team, accounts
):
    book = accounts["book"]
    goal = Goal.objects.create(book=book, name="Zed RRSP", monthly_contribution=Decimal("400.00"))
    budget = BudgetPage(authenticated_page, live_server.url)
    budget.goto_budget(book)

    expect(budget.goal_plan_input("Zed RRSP")).to_have_value("400.00")
    assert budget.goal_plan_actual("Zed RRSP") == "$400.00"
    pill_before = _money(budget.unassigned_pill_value())

    budget.set_goal_plan("Zed RRSP", "250")
    assert budget.goal_plan_actual("Zed RRSP") == "$250.00"
    expect(budget.goal_plan_row("Zed RRSP").get_by_test_id("goal-plan-typed-tag")).to_be_visible()
    expect(authenticated_page.get_by_test_id("unassigned-pill").locator("[data-unassigned-pill-value]")).to_have_text(
        f"${pill_before + Decimal('150'):,.2f}"
    )
    assert GoalPlan.objects.get(goal=goal).amount == Decimal("250.00")

    budget.reset_goal_plan("Zed RRSP")
    expect(budget.goal_plan_input("Zed RRSP")).to_have_value("400.00")
    expect(budget.goal_plan_row("Zed RRSP").get_by_test_id("goal-plan-default-tag")).to_be_visible()
    assert not GoalPlan.objects.filter(goal=goal).exists()


@pytest.mark.django_db(transaction=True)
def test_a_linked_goal_holds_its_plan_until_the_transfer_lands(
    requires_vite, authenticated_page: Page, live_server, team, accounts
):
    book = accounts["book"]
    goal = Goal.objects.create(book=book, name="Zed Pension", monthly_contribution=Decimal("300.00"))
    GoalAccountLink.objects.create(
        book=book,
        goal=goal,
        account=accounts["savings"],
        # From today: the fixture's opening balance (yesterday) would otherwise
        # arrive in the account and meet the plan by itself.
        start_date=date.today(),
        include_starting_balance=False,
    )
    row = BankTransaction.objects.create(
        book=book,
        account=accounts["checking"],
        posted_date=date.today(),
        amount=Decimal("300.00"),
        description="ONLINE TRANSFER",
        source=BankTransaction.SOURCE_CSV,
    )

    budget = BudgetPage(authenticated_page, live_server.url)
    budget.goto_budget(book)
    expect(budget.goal_held("Zed Pension")).to_be_visible()
    expect(budget.goal_held("Zed Pension")).to_contain_text("$300.00")
    assert budget.goal_plan_actual("Zed Pension") == "$0.00"
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

    budget.goto_budget(book)
    expect(budget.goal_held("Zed Pension")).to_be_hidden()
    assert budget.goal_plan_actual("Zed Pension") == "$300.00"
    # The plan already held the money: the transfer moved nothing.
    assert budget.unassigned_pill_value() == pill_before


@pytest.mark.django_db(transaction=True)
def test_the_unmet_plan_setting_shows_with_a_linked_account(
    requires_vite, authenticated_page: Page, live_server, team, accounts
):
    book = accounts["book"]
    budget = BudgetPage(authenticated_page, live_server.url)
    budget.goto_goal_create(book)
    authenticated_page.locator("[name='name']").fill("Zed Pension")
    authenticated_page.locator("[name='monthly_contribution']").fill("300")
    expect(authenticated_page.get_by_test_id("goal-unmet-plan")).to_be_hidden()
    budget.tick_link_account("Zed Savings")
    expect(authenticated_page.get_by_test_id("goal-unmet-plan")).to_be_visible()
    authenticated_page.get_by_test_id("goal-unmet-plan-carry").check()
    budget.submit_goal_form()
    authenticated_page.wait_for_url(f"**{book.base_url}budget/goals/", timeout=10_000)
    assert Goal.objects.get(book=book, name="Zed Pension").unmet_plan == Goal.UNMET_CARRY
