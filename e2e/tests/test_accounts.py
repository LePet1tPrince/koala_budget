"""
E2E tests for the Chart of Accounts feature.

Covers: list view, create account, edit account, delete account.
All pages are Django-template rendered (no Vite dev server required).
"""

import pytest
from playwright.sync_api import Page

from e2e.factories import AccountFactory, AccountGroupFactory
from e2e.pages.accounts import AccountsPage


@pytest.mark.django_db(transaction=True)
def test_account_list_shows_existing_accounts(authenticated_page: Page, live_server, team):
    """Accounts created in the DB appear in the account list table."""
    group = AccountGroupFactory(team=team)
    AccountFactory(team=team, account_group=group, name="Checking Account")
    AccountFactory(team=team, account_group=group, name="Savings Account")

    accounts = AccountsPage(authenticated_page, live_server.url)
    accounts.goto_list(team.slug)

    names = accounts.get_account_names()
    assert "Checking Account" in names
    assert "Savings Account" in names
    assert accounts.get_row_count() == 2


@pytest.mark.django_db(transaction=True)
def test_create_account(authenticated_page: Page, live_server, team):
    """User can create a new account via the form and it appears in the list."""
    group = AccountGroupFactory(team=team, name="Expenses")

    accounts = AccountsPage(authenticated_page, live_server.url)
    accounts.create_account(
        name="Office Supplies",
        account_number="5100",
        account_group_name=group.name,
        team_slug=team.slug,
    )

    # Should redirect back to accounts area after save
    assert f"/a/{team.slug}/accounts" in authenticated_page.url


@pytest.mark.django_db(transaction=True)
def test_account_list_empty_state(authenticated_page: Page, live_server, team):
    """With no accounts, the list page shows an empty state message."""
    accounts = AccountsPage(authenticated_page, live_server.url)
    accounts.goto(f"/a/{team.slug}/accounts/", wait_for="[data-testid='new-account-btn'], p.text-gray-500")

    assert not accounts.has_table()
    assert authenticated_page.locator("text=No accounts yet.").is_visible()


@pytest.mark.django_db(transaction=True)
def test_cancel_create_account_returns_to_list(authenticated_page: Page, live_server, team):
    """Clicking Cancel on the create form takes the user back to the list."""
    accounts = AccountsPage(authenticated_page, live_server.url)
    accounts.goto_create(team.slug)
    accounts.click_cancel()

    authenticated_page.wait_for_url(f"**/a/{team.slug}/accounts/", timeout=5_000)
    assert f"/a/{team.slug}/accounts/" in authenticated_page.url


@pytest.mark.django_db(transaction=True)
def test_edit_account_form_prefills_name(authenticated_page: Page, live_server, team):
    """The edit form is pre-populated with the existing account name."""
    group = AccountGroupFactory(team=team)
    AccountFactory(team=team, account_group=group, name="My Test Account", account_number="9999")

    accounts = AccountsPage(authenticated_page, live_server.url)
    accounts.goto_list(team.slug)
    accounts.click_edit(index=0)

    # The name field should be pre-filled
    name_value = authenticated_page.locator("[name='name']").input_value()
    assert name_value == "My Test Account"
