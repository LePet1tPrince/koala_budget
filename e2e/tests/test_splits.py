"""
E2E tests for split transactions.

NOTE: These tests require the Vite dev server to be running alongside the
Django live server. Run `make start-bg` first, then
`make test-e2e ARGS="e2e/tests/test_splits.py"`.

A split is one bank transaction apportioned across several categories. These
cover what the user can actually do with one: see that it is split without
opening it, open it and find its legs, re-apportion, add a leg, unsplit, and be
stopped from saving one that does not add up.
"""

from decimal import Decimal

import pytest
from playwright.sync_api import Page, expect

from e2e.factories import (
    AccountFactory,
    AccountGroupFactory,
    AssetAccountFactory,
    feed_transaction,
    split_feed_transaction,
)
from e2e.pages.bank_feed import BankFeedPage

# The team fixture bootstraps a full chart of accounts, so a category search has
# to be narrow enough to leave only the ones a test is about. These share a
# prefix nothing else in the chart carries.
GROCERIES = "Zed Groceries"
HOUSEHOLD = "Zed Household"
DINING = "Zed Dining"


@pytest.fixture
def split_fixture(team):
    """One feed account, three findable categories, a split row and a plain one."""
    group = AccountGroupFactory(team=team)
    account = AssetAccountFactory(team=team, account_group=group, has_feed=True)
    expense_group = AccountGroupFactory(team=team)
    categories = {
        name: AccountFactory(team=team, account_group=expense_group, name=name)
        for name in (GROCERIES, HOUSEHOLD, DINING)
    }

    split = split_feed_transaction(
        team,
        account,
        legs=[(categories[GROCERIES], Decimal("160.00")), (categories[HOUSEHOLD], Decimal("50.40"))],
        description="COSTCO SPLIT",
        merchant_name="Costco",
    )
    plain = feed_transaction(team, account, description="PLAIN ROW", merchant_name="Corner Coffee")

    return {"team": team, "account": account, "categories": categories, "split": split, "plain": plain}


@pytest.mark.django_db(transaction=True)
def test_split_row_shows_a_split_badge(requires_vite, authenticated_page: Page, live_server, split_fixture):
    """A split says so in the feed, rather than showing one leg as its category."""
    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(split_fixture["team"].slug)
    feed.click_account_card(split_fixture["account"].id)

    assert feed.split_badge_text(split_fixture["split"].id) == "Split (2)"
    assert not feed.has_split_badge(split_fixture["plain"].id)


@pytest.mark.django_db(transaction=True)
def test_opening_a_split_shows_its_legs(requires_vite, authenticated_page: Page, live_server, split_fixture):
    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(split_fixture["team"].slug)
    feed.click_account_card(split_fixture["account"].id)
    feed.open_row(split_fixture["split"].id)

    assert feed.has_split_editor()
    assert feed.split_amounts() == ["160.00", "50.40"]
    assert feed.split_remaining() == "$0.00"


@pytest.mark.django_db(transaction=True)
def test_unbalanced_split_cannot_be_saved(requires_vite, authenticated_page: Page, live_server, split_fixture):
    """The shortfall is named, and Save stays disabled until it is gone."""
    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(split_fixture["team"].slug)
    feed.click_account_card(split_fixture["account"].id)
    feed.open_row(split_fixture["split"].id)

    feed.set_split_amount(0, "100.00")
    assert feed.split_remaining() == "$60.00"
    assert feed.save_disabled()

    # Clicking the shortfall assigns it, which is the way out of this state.
    feed.assign_split_remainder()
    assert feed.split_remaining() == "$0.00"
    assert not feed.save_disabled()


@pytest.mark.django_db(transaction=True)
def test_reapportioning_a_split_saves(requires_vite, authenticated_page: Page, live_server, split_fixture):
    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(split_fixture["team"].slug)
    feed.click_account_card(split_fixture["account"].id)
    feed.open_row(split_fixture["split"].id)

    feed.set_split_amount(0, "100.00")
    feed.assign_split_remainder()
    feed.save_modal()

    entry = split_fixture["split"].journal_entry
    entry.refresh_from_db()
    assert entry.total_debits == entry.total_credits
    amounts = sorted(str(line.dr_amount) for line in entry.lines.all())
    assert amounts == ["0.00", "100.00", "110.40"]


@pytest.mark.django_db(transaction=True)
def test_adding_a_leg_to_a_split(requires_vite, authenticated_page: Page, live_server, split_fixture):
    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(split_fixture["team"].slug)
    feed.click_account_card(split_fixture["account"].id)
    feed.open_row(split_fixture["split"].id)

    feed.set_split_amount(0, "100.00")
    feed.add_split_leg()
    feed.choose_split_category(2, DINING)
    feed.set_split_amount(2, "60.00")
    assert feed.split_remaining() == "$0.00"
    feed.save_modal()

    assert feed.split_badge_text(split_fixture["split"].id) == "Split (3)"
    entry = split_fixture["split"].journal_entry
    entry.refresh_from_db()
    assert entry.lines.count() == 4
    assert entry.total_debits == entry.total_credits


@pytest.mark.django_db(transaction=True)
def test_splitting_an_uncategorized_transaction(requires_vite, authenticated_page: Page, live_server, split_fixture):
    """The path a user actually takes: an uncategorized row, split from scratch."""
    team = split_fixture["team"]
    account = split_fixture["account"]
    row = feed_transaction(team, account, description="CANADIAN TIRE", merchant_name="Canadian Tire")

    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(team.slug)
    feed.click_account_card(account.id)
    feed.open_row(row.id)

    feed.start_split()
    # The first leg is seeded with the whole total, so Remaining starts at zero
    # rather than greeting the user with the full amount outstanding.
    assert feed.split_remaining() == "$0.00"
    assert feed.split_leg_count() == 2

    feed.choose_split_category(0, GROCERIES)
    feed.set_split_amount(0, "15.00")
    feed.choose_split_category(1, HOUSEHOLD)
    feed.assign_split_remainder()
    feed.save_modal()

    row.refresh_from_db()
    assert row.journal_entry is not None
    assert row.journal_entry.lines.count() == 3
    assert row.journal_entry.total_debits == row.journal_entry.total_credits


@pytest.mark.django_db(transaction=True)
def test_remove_split_collapses_to_the_largest_leg(requires_vite, authenticated_page: Page, live_server, split_fixture):
    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(split_fixture["team"].slug)
    feed.click_account_card(split_fixture["account"].id)
    feed.open_row(split_fixture["split"].id)

    feed.remove_split()
    assert not feed.has_split_editor()
    feed.save_modal()

    assert not feed.has_split_badge(split_fixture["split"].id)
    entry = split_fixture["split"].journal_entry
    entry.refresh_from_db()
    assert entry.lines.count() == 2
    # The largest leg is the likeliest thing the user meant the transaction to be.
    assert entry.lines.filter(account__name=GROCERIES).exists()


@pytest.mark.django_db(transaction=True)
def test_a_split_cannot_be_reduced_below_two_legs(requires_vite, authenticated_page: Page, live_server, split_fixture):
    """Removing the second-to-last leg is blocked; Remove split is the way out."""
    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(split_fixture["team"].slug)
    feed.click_account_card(split_fixture["account"].id)
    feed.open_row(split_fixture["split"].id)

    remove_first = authenticated_page.locator("[data-testid='split-remove-0']")
    expect(remove_first).to_be_disabled()

    # With a third leg there is room to remove one.
    feed.add_split_leg()
    expect(remove_first).to_be_enabled()
    feed.remove_split_leg(2)
    assert feed.split_leg_count() == 2
    expect(remove_first).to_be_disabled()
