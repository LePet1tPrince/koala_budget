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

from e2e.factories import AccountFactory, AccountGroupFactory, AssetAccountFactory, feed_transaction
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


# ----------------------------------------------------------------------
# Filter contract
#
# These lock the behaviour of the Quick Filters menu and the Archived view
# BEFORE the table is rewritten off MUI (restyle plan Phase 5b), so the
# rewrite has to match what the table does today rather than what the
# rewrite's author believes it does. They read rows out of a plain <table>,
# which both the current and the replacement markup produce.
# ----------------------------------------------------------------------


@pytest.fixture
def feed_fixture(team):
    """One account with a row in each state the filters discriminate on."""
    group = AccountGroupFactory(team=team)
    account = AssetAccountFactory(team=team, account_group=group, has_feed=True)
    expense_group = AccountGroupFactory(team=team)
    category = AccountFactory(team=team, account_group=expense_group)

    rows = {
        "uncategorized": feed_transaction(team, account, description="ROW-UNCATEGORIZED"),
        "unreconciled": feed_transaction(
            team, account, category=category, reconciled=False, description="ROW-UNRECONCILED"
        ),
        "reconciled": feed_transaction(team, account, category=category, reconciled=True, description="ROW-RECONCILED"),
        "archived": feed_transaction(team, account, archived=True, description="ROW-ARCHIVED"),
    }
    return {"account": account, "category": category, "rows": rows}


@pytest.mark.django_db(transaction=True)
def test_default_view_shows_every_unarchived_row(requires_vite, authenticated_page, live_server, feed_fixture):
    """No filter selected: categorized and uncategorized, reconciled and not — but never archived."""
    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(feed_fixture["account"].team.slug)
    feed.click_account_card(feed_fixture["account"].id)
    feed.wait_for_table()

    assert feed.has_row_matching("ROW-UNCATEGORIZED")
    assert feed.has_row_matching("ROW-UNRECONCILED")
    assert feed.has_row_matching("ROW-RECONCILED")
    assert not feed.has_row_matching("ROW-ARCHIVED")


@pytest.mark.django_db(transaction=True)
def test_to_review_filter_hides_reconciled(requires_vite, authenticated_page, live_server, feed_fixture):
    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(feed_fixture["account"].team.slug)
    feed.click_account_card(feed_fixture["account"].id)
    feed.wait_for_table()

    feed.click_filter("to-review")

    assert feed.has_row_matching("ROW-UNRECONCILED")
    assert feed.has_row_matching("ROW-UNCATEGORIZED")  # uncategorized is unreconciled too
    assert not feed.has_row_matching("ROW-RECONCILED")
    assert not feed.has_row_matching("ROW-ARCHIVED")


@pytest.mark.django_db(transaction=True)
def test_reconciled_filter_shows_only_reconciled(requires_vite, authenticated_page, live_server, feed_fixture):
    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(feed_fixture["account"].team.slug)
    feed.click_account_card(feed_fixture["account"].id)
    feed.wait_for_table()

    feed.click_filter("reconciled")

    assert feed.has_row_matching("ROW-RECONCILED")
    assert not feed.has_row_matching("ROW-UNRECONCILED")
    assert not feed.has_row_matching("ROW-UNCATEGORIZED")


@pytest.mark.django_db(transaction=True)
def test_to_review_and_reconciled_are_mutually_exclusive(requires_vite, authenticated_page, live_server, feed_fixture):
    """Selecting one clears the other — they are opposite states, not a narrowing."""
    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(feed_fixture["account"].team.slug)
    feed.click_account_card(feed_fixture["account"].id)
    feed.wait_for_table()

    feed.click_filter("to-review")
    feed.click_filter("reconciled")

    # If both were applied at once nothing could match; the second must win outright.
    assert feed.has_row_matching("ROW-RECONCILED")
    assert not feed.has_row_matching("ROW-UNRECONCILED")


@pytest.mark.django_db(transaction=True)
def test_uncategorized_filter_is_independent(requires_vite, authenticated_page, live_server, feed_fixture):
    """Uncategorized narrows whatever else is selected rather than replacing it."""
    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(feed_fixture["account"].team.slug)
    feed.click_account_card(feed_fixture["account"].id)
    feed.wait_for_table()

    feed.click_filter("uncategorized")
    assert feed.has_row_matching("ROW-UNCATEGORIZED")
    assert not feed.has_row_matching("ROW-UNRECONCILED")
    assert not feed.has_row_matching("ROW-RECONCILED")

    # Combined with To Review it still leaves the uncategorized row, which is both.
    feed.click_filter("to-review")
    assert feed.has_row_matching("ROW-UNCATEGORIZED")
    assert not feed.has_row_matching("ROW-RECONCILED")


@pytest.mark.django_db(transaction=True)
def test_archived_is_a_separate_view(requires_vite, authenticated_page, live_server, feed_fixture):
    """Archived shows only archived rows and disables the quick filters entirely."""
    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(feed_fixture["account"].team.slug)
    feed.click_account_card(feed_fixture["account"].id)
    feed.wait_for_table()

    feed.click_filter("archived")

    assert feed.has_row_matching("ROW-ARCHIVED")
    assert not feed.has_row_matching("ROW-UNCATEGORIZED")
    assert not feed.has_row_matching("ROW-RECONCILED")
    assert feed.quick_filters_disabled()

    # Leaving the archived view restores the active one.
    feed.click_filter("archived")
    assert not feed.has_row_matching("ROW-ARCHIVED")
    assert feed.has_row_matching("ROW-UNCATEGORIZED")
    assert not feed.quick_filters_disabled()
