"""
E2E for simple arithmetic in amount fields.

Typing "120+35" into an amount field and leaving it (Tab, Enter or a click
elsewhere) replaces the formula with its result, and what is saved is the
result. Server-rendered fields get this from `common/amount-fields.js`, React
ones from `common/AmountInput.jsx`; both are covered here.

Requires the Vite dev server (the budget auto-save and the modals are JS).
"""

from datetime import date
from decimal import Decimal

import pytest
from playwright.sync_api import Page, expect

from apps.accounts.models import ACCOUNT_TYPE_EXPENSE
from apps.budget.models import Budget, Goal, GoalAllocation
from e2e.factories import (
    AccountFactory,
    AccountGroupFactory,
    AssetAccountFactory,
    JournalEntryFactory,
    JournalLineFactory,
)
from e2e.pages.budget import BudgetPage
from e2e.pages.transactions import TransactionsPage


@pytest.mark.django_db(transaction=True)
def test_budget_amount_formula_is_evaluated_and_saved(requires_vite, authenticated_page: Page, live_server, team):
    group = AccountGroupFactory(team=team, account_type=ACCOUNT_TYPE_EXPENSE)
    category = AccountFactory(team=team, account_group=group, name="Zed Groceries")

    budget = BudgetPage(authenticated_page, live_server.url)
    budget.goto_budget(team.default_book)

    field = authenticated_page.locator(f"#budget-form-{category.pk} input[name='budget_amount']")
    field.fill("120+35*2")
    with authenticated_page.expect_response(lambda r: "save-amount" in r.url, timeout=10_000) as response:
        field.press("Tab")

    assert response.value.ok
    expect(field).to_have_value("190.00")
    saved = Budget.objects.get(book=team.default_book, category=category)
    assert saved.budget_amount == Decimal("190.00")


@pytest.mark.django_db(transaction=True)
def test_goal_custom_amount_formula_is_assigned(requires_vite, authenticated_page: Page, live_server, team):
    month = date.today().replace(day=1)
    checking = AssetAccountFactory(team=team, account_group=AccountGroupFactory(team=team, account_type="asset"))
    opening = AssetAccountFactory(team=team, account_group=AccountGroupFactory(team=team, account_type="goal"))
    entry = JournalEntryFactory(team=team, entry_date=month)
    JournalLineFactory(team=team, journal_entry=entry, account=checking, dr_amount=Decimal("5000.00"))
    JournalLineFactory(team=team, journal_entry=entry, account=opening, cr_amount=Decimal("5000.00"))
    goal = Goal.objects.create(book=team.default_book, name="Zed Trip", target_amount=Decimal("3000.00"))

    budget = BudgetPage(authenticated_page, live_server.url)
    budget.goto_goals(team.default_book, style="summit")

    card = budget.goal_card("Zed Trip")
    field = card.locator("[data-custom-input]")
    field.fill("3*50")
    field.press("Enter")

    expect(field).to_have_value("", timeout=10_000)  # cleared once the assignment lands
    allocation = GoalAllocation.objects.get(book=team.default_book, goal=goal, month=month)
    assert allocation.amount == Decimal("150.00")


@pytest.fixture
def plain_outflow(team):
    banks = AccountGroupFactory(team=team, name="Bank Accounts", account_type="asset")
    everyday = AccountGroupFactory(team=team, name="Everyday", account_type="expense")
    chequing = AccountFactory(team=team, account_group=banks, name="Chequing", has_feed=True)
    groceries = AccountFactory(team=team, account_group=everyday, name="Groceries")
    AccountFactory(team=team, account_group=everyday, name="Household Goods")
    entry = JournalEntryFactory(team=team, description="Weekly shop", status="posted", entry_date=date(2026, 3, 4))
    JournalLineFactory(team=team, journal_entry=entry, account=chequing, cr_amount="84.20")
    JournalLineFactory(team=team, journal_entry=entry, account=groceries, dr_amount="84.20")
    return entry


@pytest.mark.django_db(transaction=True)
def test_transaction_amount_formula_is_evaluated_and_saved(
    requires_vite, authenticated_page: Page, live_server, team, plain_outflow
):
    transactions = TransactionsPage(authenticated_page, live_server.url)
    transactions.goto(team.default_book)
    transactions.open_editor("Weekly shop")

    field = authenticated_page.locator("[data-testid='transaction-outflow']")
    field.fill("50+40.25")
    field.press("Tab")
    expect(field).to_have_value("90.25")

    transactions.save_editor()
    amounts = sorted(line.dr_amount + line.cr_amount for line in plain_outflow.lines.all())
    assert amounts == [Decimal("90.25"), Decimal("90.25")]


@pytest.mark.django_db(transaction=True)
def test_split_leg_formula_is_evaluated(requires_vite, authenticated_page: Page, live_server, team, plain_outflow):
    transactions = TransactionsPage(authenticated_page, live_server.url)
    transactions.goto(team.default_book)
    transactions.open_editor("Weekly shop")
    transactions.start_split()

    leg = authenticated_page.locator("[data-testid='split-amount-0']")
    leg.fill("84.20/2")
    leg.press("Tab")
    expect(leg).to_have_value("42.10")
