"""
E2E tests for the Chart of Accounts feature.

Covers: the drag-and-drop accounts board (home), create account, edit account.
The board is a React component, so these tests need the Vite dev server
(`make start-bg`) like the other React-mounted pages.
"""

import pytest
from playwright.sync_api import Page

from e2e.factories import AccountFactory, AccountGroupFactory
from e2e.pages.accounts import AccountsPage


@pytest.mark.django_db(transaction=True)
def test_accounts_board_shows_existing_accounts(authenticated_page: Page, live_server, team):
    """Accounts created in the DB appear on the accounts board."""
    group = AccountGroupFactory(team=team)
    AccountFactory(team=team, account_group=group, name="Checking Account")
    AccountFactory(team=team, account_group=group, name="Savings Account")

    accounts = AccountsPage(authenticated_page, live_server.url)
    accounts.goto_home(team.slug)

    names = accounts.get_account_names()
    assert "Checking Account" in names
    assert "Savings Account" in names
    assert accounts.get_row_count() == 2
    assert group.name in accounts.get_group_names()


@pytest.mark.django_db(transaction=True)
def test_create_account(authenticated_page: Page, live_server, team):
    """User can create a new account via the form."""
    group = AccountGroupFactory(team=team, name="Expenses")

    accounts = AccountsPage(authenticated_page, live_server.url)
    accounts.create_account(
        name="Office Supplies",
        account_group_name=group.name,
        team_slug=team.slug,
    )

    # Should redirect back to accounts area after save
    assert f"/a/{team.slug}/accounts/accounts" in authenticated_page.url


@pytest.mark.django_db(transaction=True)
def test_accounts_board_empty_state(authenticated_page: Page, live_server, team):
    """With no accounts, the board shows all type sections with add-group buttons."""
    accounts = AccountsPage(authenticated_page, live_server.url)
    accounts.goto_home(team.slug)

    assert accounts.get_row_count() == 0
    # All five flow-type sections render, each with a "new group" affordance
    assert authenticated_page.locator("[data-testid='account-type-section']").count() == 5
    assert authenticated_page.locator("[data-testid='add-group-btn']").count() == 5


@pytest.mark.django_db(transaction=True)
def test_cancel_create_account_returns_home(authenticated_page: Page, live_server, team):
    """Clicking Cancel on the create form takes the user back to the accounts home."""
    accounts = AccountsPage(authenticated_page, live_server.url)
    accounts.goto_create(team.slug)
    accounts.click_cancel()

    authenticated_page.wait_for_url(f"**/a/{team.slug}/accounts/", timeout=5_000)
    assert authenticated_page.url.rstrip("/").endswith(f"/a/{team.slug}/accounts")


@pytest.mark.django_db(transaction=True)
def test_add_account_inline_from_group(authenticated_page: Page, live_server, team):
    """The "+ Add account" row inside a group creates an account in that group."""
    AccountGroupFactory(team=team, name="Bank Accounts")

    accounts = AccountsPage(authenticated_page, live_server.url)
    accounts.goto_home(team.slug)

    authenticated_page.locator("[data-testid='add-account-btn']").first.click()
    authenticated_page.locator("input[placeholder='New account name']").fill("Inline Chequing")
    authenticated_page.keyboard.press("Enter")

    authenticated_page.wait_for_selector("[data-testid='account-name']:has-text('Inline Chequing')")
    assert "Inline Chequing" in accounts.get_account_names()


@pytest.mark.django_db(transaction=True)
def test_add_group_inline_from_section(authenticated_page: Page, live_server, team):
    """The "+ New … group" button at the bottom of a section creates a group."""
    accounts = AccountsPage(authenticated_page, live_server.url)
    accounts.goto_home(team.slug)

    section = authenticated_page.locator("[data-testid='account-type-section'][data-account-type='asset']")
    section.locator("[data-testid='add-group-btn']").click()
    section.locator("input[placeholder='New group name']").fill("Real Estate")
    authenticated_page.keyboard.press("Enter")

    authenticated_page.wait_for_selector("[data-testid='group-name']:has-text('Real Estate')")
    assert "Real Estate" in accounts.get_group_names()


@pytest.mark.django_db(transaction=True)
def test_edit_account_form_prefills_name(authenticated_page: Page, live_server, team):
    """The edit form is pre-populated with the existing account name."""
    group = AccountGroupFactory(team=team)
    account = AccountFactory(team=team, account_group=group, name="My Test Account")

    accounts = AccountsPage(authenticated_page, live_server.url)
    accounts.goto(
        f"/a/{team.slug}/accounts/accounts/{account.pk}/update/",
        wait_for="[data-testid='account-form']",
    )

    name_value = authenticated_page.locator("[name='name']").input_value()
    assert name_value == "My Test Account"
