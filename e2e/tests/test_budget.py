"""
E2E tests for the Budget and Goals features.

The budget table page uses a small React component (BudgetMonthPicker) but
the main content is Django-template rendered, so most tests do NOT require
the Vite dev server (the month picker simply won't load, but the budget
table itself is server-rendered).

Covers: budget table display, goals list, create goal, cancel goal form.
"""

import pytest
from playwright.sync_api import Page

from e2e.factories import AccountFactory, AccountGroupFactory
from e2e.pages.budget import BudgetPage


@pytest.mark.django_db(transaction=True)
def test_budget_home_empty_state(authenticated_page: Page, live_server, team):
    """Budget home shows an empty state when there are no income/expense accounts."""
    budget = BudgetPage(authenticated_page, live_server.url)
    budget.goto_budget(team.default_book)

    assert budget.is_budget_empty()
    assert not budget.has_budget_table() or budget.get_budget_row_count() == 0


@pytest.mark.django_db(transaction=True)
def test_budget_home_shows_rows_for_accounts(authenticated_page: Page, live_server, team):
    """Income and expense accounts appear as rows in the budget table."""
    from apps.accounts.models import ACCOUNT_TYPE_EXPENSE, ACCOUNT_TYPE_INCOME

    income_group = AccountGroupFactory(team=team, account_type=ACCOUNT_TYPE_INCOME)
    expense_group = AccountGroupFactory(team=team, account_type=ACCOUNT_TYPE_EXPENSE)
    AccountFactory(team=team, account_group=income_group)
    AccountFactory(team=team, account_group=expense_group)
    AccountFactory(team=team, account_group=expense_group)

    budget = BudgetPage(authenticated_page, live_server.url)
    budget.goto_budget(team.default_book)

    assert budget.has_budget_table()
    assert budget.get_budget_row_count() == 3
    assert budget.has_grand_total()


@pytest.mark.django_db(transaction=True)
def test_goals_list_empty_state(authenticated_page: Page, live_server, team):
    """Goals list shows the empty-state card (and no goal cards) when no goals exist."""
    budget = BudgetPage(authenticated_page, live_server.url)
    budget.goto_goals(team.default_book)

    assert budget.has_goals_empty_state()
    assert budget.get_goal_card_count() == 0


@pytest.mark.django_db(transaction=True)
def test_create_goal(authenticated_page: Page, live_server, team):
    """User can create a new savings goal via the form."""
    budget = BudgetPage(authenticated_page, live_server.url)
    budget.create_goal(
        name="Emergency Fund",
        target_amount="5000.00",
        book=team.default_book,
    )

    # After save, redirects back to goals area
    assert f"{team.default_book.base_url}budget/goals" in authenticated_page.url


@pytest.mark.django_db(transaction=True)
def test_cancel_goal_form_returns_to_goals_list(authenticated_page: Page, live_server, team):
    """Clicking Cancel on the goal form returns the user to the goals list."""
    budget = BudgetPage(authenticated_page, live_server.url)
    budget.goto_goal_create(team.default_book)
    budget.cancel_goal_form()

    authenticated_page.wait_for_url(f"**{team.default_book.base_url}budget/goals/", timeout=5_000)
    assert f"{team.default_book.base_url}budget/goals/" in authenticated_page.url


@pytest.mark.django_db(transaction=True)
def test_new_goal_button_navigates_to_form(authenticated_page: Page, live_server, team):
    """The 'New Goal' button on the goals list navigates to the create form."""
    budget = BudgetPage(authenticated_page, live_server.url)
    budget.goto_goals(team.default_book)
    budget.click_new_goal()

    assert f"{team.default_book.base_url}budget/goals/new/" in authenticated_page.url
    assert authenticated_page.locator("[data-testid='goal-form']").is_visible()


@pytest.mark.django_db(transaction=True)
def test_hide_and_unhide_a_budget_category(authenticated_page: Page, live_server, team):
    """A category hidden from the budget folds into a collapsed group and comes back with Unhide.

    Requires the Vite dev server (the hide/unhide buttons re-render the month in place).
    """
    from playwright.sync_api import expect

    from apps.accounts.models import ACCOUNT_TYPE_EXPENSE, Account

    group = AccountGroupFactory(team=team, account_type=ACCOUNT_TYPE_EXPENSE)
    gym = AccountFactory(team=team, account_group=group, name="Zed Old Gym")
    AccountFactory(team=team, account_group=group, name="Zed Groceries")

    budget = BudgetPage(authenticated_page, live_server.url)
    budget.goto_budget(team.default_book)
    budget.hide_category("Zed Old Gym")

    expect(budget.budget_row("Zed Old Gym")).to_have_count(0)
    expect(budget.hidden_row("Zed Old Gym")).to_be_hidden()
    expect(budget.hidden_toggle()).to_have_text("1 hidden category")
    gym.refresh_from_db()
    assert gym.hidden_from_budget

    budget.hidden_toggle().click()
    expect(budget.hidden_toggle()).to_have_attribute("aria-expanded", "true")
    expect(budget.hidden_row("Zed Old Gym")).to_be_visible()

    budget.unhide_category("Zed Old Gym")
    expect(budget.hidden_toggle()).to_have_count(0)
    expect(budget.budget_row("Zed Groceries")).to_be_visible()
    assert not Account.objects.get(pk=gym.pk).hidden_from_budget


def _income_and_expense_categories(team):
    from apps.accounts.models import ACCOUNT_TYPE_EXPENSE, ACCOUNT_TYPE_INCOME

    book = team.default_book
    book.budget_future_income = True
    book.save()
    income_group = AccountGroupFactory(team=team, account_type=ACCOUNT_TYPE_INCOME)
    expense_group = AccountGroupFactory(team=team, account_type=ACCOUNT_TYPE_EXPENSE)
    AccountFactory(team=team, account_group=income_group, name="Zed Salary")
    AccountFactory(team=team, account_group=income_group, name="Zed Side Gig")
    AccountFactory(team=team, account_group=expense_group, name="Zed Groceries")
    AccountFactory(team=team, account_group=expense_group, name="Zed Rent")


@pytest.mark.django_db(transaction=True)
def test_budget_tabs_show_one_section_and_remember_it(authenticated_page: Page, live_server, team):
    """Income and Expenses are tabs: one panel on screen, the choice in the URL and kept on reload.

    Requires the Vite dev server (the tabs switch in place).
    """
    from playwright.sync_api import expect

    _income_and_expense_categories(team)
    budget = BudgetPage(authenticated_page, live_server.url)
    budget.goto_budget(team.default_book)

    assert budget.active_tab() == "expense"
    expect(budget.panel("expense")).to_be_visible()
    expect(budget.panel("income")).to_be_hidden()

    budget.select_tab("income")
    expect(budget.panel("income")).to_be_visible()
    expect(budget.panel("expense")).to_be_hidden()
    expect(budget.tab("income")).to_have_attribute("aria-selected", "true")
    assert "tab=income" in authenticated_page.url

    # Moving down a column never crosses into a tab that is out of view.
    budget.amount_inputs("income").last.focus()
    authenticated_page.keyboard.press("ArrowDown")
    expect(budget.amount_inputs("income").last).to_be_focused()

    # A plain visit (no ?tab=) reopens the tab last used.
    budget.goto_budget(team.default_book)
    assert budget.active_tab() == "income"
    expect(budget.panel("income")).to_be_visible()


@pytest.mark.django_db(transaction=True)
def test_budget_rows_are_condensed(authenticated_page: Page, live_server, team):
    """A budget row holds a 24px amount field and a hairline of padding: about 29px tall."""
    _income_and_expense_categories(team)
    budget = BudgetPage(authenticated_page, live_server.url)
    budget.goto_budget(team.default_book)

    assert budget.row_height() <= 30
