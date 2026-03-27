"""
E2E tests for the Bank Feed feature (React SPA).

NOTE: These tests require the Vite dev server to be running alongside the
Django live server. Run `make start-bg` first (which starts the vite container),
then run `make test-e2e ARGS="e2e/tests/test_bank_feed.py"`.

Covers: account cards displayed, selecting an account, filter toggles,
add-transaction modal opens.
"""

import pytest
from playwright.sync_api import Page

from e2e.factories import AccountGroupFactory, AssetAccountFactory
from e2e.pages.bank_feed import BankFeedPage


@pytest.mark.django_db(transaction=True)
def test_bank_feed_shows_accounts_with_feed(requires_vite, authenticated_page: Page, live_server, team):
    """Accounts with has_feed=True appear as cards on the bank feed home page."""
    group = AccountGroupFactory(team=team)
    feed_account = AssetAccountFactory(team=team, account_group=group, has_feed=True)
    # An account without a feed should not appear
    AssetAccountFactory(team=team, account_group=group, has_feed=False)

    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(team.slug)

    assert feed.has_account_card(feed_account.id)
    assert feed.get_account_card_count() == 1


@pytest.mark.django_db(transaction=True)
def test_selecting_account_shows_filter_toggles(requires_vite, authenticated_page: Page, live_server, team):
    """Clicking an account card loads the bank feed table with filter toggles."""
    group = AccountGroupFactory(team=team)
    feed_account = AssetAccountFactory(team=team, account_group=group, has_feed=True)

    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(team.slug)
    feed.click_account_card(feed_account.id)

    assert feed.is_filter_visible()


@pytest.mark.django_db(transaction=True)
def test_add_transaction_modal_opens(requires_vite, authenticated_page: Page, live_server, team):
    """Clicking the add-transaction button opens the edit modal."""
    group = AccountGroupFactory(team=team)
    feed_account = AssetAccountFactory(team=team, account_group=group, has_feed=True)

    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(team.slug)
    feed.click_account_card(feed_account.id)
    feed.click_add_transaction()

    assert authenticated_page.locator("[data-testid='edit-transaction-modal']").is_visible()

    # Cancel should close the modal
    feed.close_modal()
    authenticated_page.wait_for_selector("[data-testid='edit-transaction-modal']", state="hidden")
