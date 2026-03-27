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
    budget.goto_budget(team.slug)

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
    budget.goto_budget(team.slug)

    assert budget.has_budget_table()
    assert budget.get_budget_row_count() == 3
    assert budget.has_grand_total()


@pytest.mark.django_db(transaction=True)
def test_goals_list_empty_state(authenticated_page: Page, live_server, team):
    """Goals list shows a summary card and empty table when no goals exist."""
    budget = BudgetPage(authenticated_page, live_server.url)
    budget.goto_goals(team.slug)

    assert budget.has_goals_summary()
    assert budget.has_goals_table()
    assert budget.get_goal_row_count() == 0


@pytest.mark.django_db(transaction=True)
def test_create_goal(authenticated_page: Page, live_server, team):
    """User can create a new savings goal via the form."""
    budget = BudgetPage(authenticated_page, live_server.url)
    budget.create_goal(
        name="Emergency Fund",
        target_amount="5000.00",
        team_slug=team.slug,
    )

    # After save, redirects back to goals area
    assert f"/a/{team.slug}/budget/goals" in authenticated_page.url


@pytest.mark.django_db(transaction=True)
def test_cancel_goal_form_returns_to_goals_list(authenticated_page: Page, live_server, team):
    """Clicking Cancel on the goal form returns the user to the goals list."""
    budget = BudgetPage(authenticated_page, live_server.url)
    budget.goto_goal_create(team.slug)
    budget.cancel_goal_form()

    authenticated_page.wait_for_url(f"**/a/{team.slug}/budget/goals/", timeout=5_000)
    assert f"/a/{team.slug}/budget/goals/" in authenticated_page.url


@pytest.mark.django_db(transaction=True)
def test_new_goal_button_navigates_to_form(authenticated_page: Page, live_server, team):
    """The 'New Goal' button on the goals list navigates to the create form."""
    budget = BudgetPage(authenticated_page, live_server.url)
    budget.goto_goals(team.slug)
    budget.click_new_goal()

    assert f"/a/{team.slug}/budget/goals/new/" in authenticated_page.url
    assert authenticated_page.locator("[data-testid='goal-form']").is_visible()
