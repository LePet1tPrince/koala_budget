"""
E2E tests for Categorize Mode (React SPA).

NOTE: These tests require the Vite dev server to be running alongside the
Django live server. Run `make start-bg` first, then
`make test-e2e ARGS="e2e/tests/test_categorize.py"`.

Covers the keyboard contract of the category search — typing highlights the
best match, the arrow keys walk the list, Enter categorizes and Escape backs
out of the search rather than out of the page — and the suggestion block that
sits above the list.
"""

import pytest
from playwright.sync_api import Page

from e2e.factories import AccountFactory, AccountGroupFactory, AssetAccountFactory, feed_transaction
from e2e.pages.categorize import CategorizePage

# The team fixture bootstraps a full chart of accounts, so a search has to be
# narrow enough to leave only the categories a test is about. These three share
# a prefix nothing else in the chart carries; within one group they sort by name,
# which is the order the arrow keys walk.
CATEGORY_NAMES = ("Zed Coffee", "Zed Dining", "Zed Groceries")


@pytest.fixture
def categorize_fixture(team):
    """One feed account, three findable expense categories and one uncategorized row."""
    group = AccountGroupFactory(team=team)
    account = AssetAccountFactory(team=team, account_group=group, has_feed=True)
    expense_group = AccountGroupFactory(team=team)
    categories = {name: AccountFactory(team=team, account_group=expense_group, name=name) for name in CATEGORY_NAMES}
    row = feed_transaction(team, account, description="UNCATEGORIZED ROW", merchant_name="Blue Bottle")
    return {"account": account, "categories": categories, "row": row}


@pytest.mark.django_db(transaction=True)
def test_empty_search_highlights_nothing(requires_vite, authenticated_page: Page, live_server, categorize_fixture):
    """Nothing is highlighted until the user types, so a stray Enter categorizes nothing."""
    categorize = CategorizePage(authenticated_page, live_server.url)
    categorize.goto(categorize_fixture["account"].team.slug)

    assert categorize.active_row_name() is None
    assert not categorize.has_keyboard_hint()

    before = categorize.current_card_title()
    categorize.press("Enter")
    assert categorize.current_card_title() == before


@pytest.mark.django_db(transaction=True)
def test_typing_highlights_the_first_match(requires_vite, authenticated_page: Page, live_server, categorize_fixture):
    """Typing points the highlight at the top match, so Enter takes it without arrowing."""
    categorize = CategorizePage(authenticated_page, live_server.url)
    categorize.goto(categorize_fixture["account"].team.slug)

    categorize.search("zed dining")

    assert categorize.active_row_name() == "Zed Dining"
    assert categorize.has_keyboard_hint()


@pytest.mark.django_db(transaction=True)
def test_arrow_keys_walk_the_list(requires_vite, authenticated_page: Page, live_server, categorize_fixture):
    """Down moves to the next row, up moves back, and the ends wrap."""
    categorize = CategorizePage(authenticated_page, live_server.url)
    categorize.goto(categorize_fixture["account"].team.slug)

    categorize.search("zed")
    assert categorize.active_row_name() == "Zed Coffee"

    categorize.press("ArrowDown")
    assert categorize.active_row_name() == "Zed Dining"

    categorize.press("ArrowDown")
    assert categorize.active_row_name() == "Zed Groceries"

    categorize.press("ArrowUp")
    assert categorize.active_row_name() == "Zed Dining"

    # Past the last row, back to the first.
    categorize.press("ArrowDown")
    categorize.press("ArrowDown")
    assert categorize.active_row_name() == "Zed Coffee"


@pytest.mark.django_db(transaction=True)
def test_enter_categorizes_the_highlighted_row(
    requires_vite, authenticated_page: Page, live_server, categorize_fixture, team
):
    """Enter on the highlighted row categorizes the card without touching the mouse."""
    categorize = CategorizePage(authenticated_page, live_server.url)
    categorize.goto(team.slug)

    categorize.search("zed")
    categorize.press("ArrowDown")
    assert categorize.active_row_name() == "Zed Dining"
    categorize.press("Enter")

    authenticated_page.wait_for_timeout(1_500)

    categorize_fixture["row"].refresh_from_db()
    entry = categorize_fixture["row"].journal_entry
    assert entry is not None
    categorized_to = {
        line.account.name for line in entry.lines.all() if line.account_id != categorize_fixture["account"].id
    }
    assert categorized_to == {"Zed Dining"}


@pytest.mark.django_db(transaction=True)
def test_escape_clears_the_search_without_leaving(
    requires_vite, authenticated_page: Page, live_server, categorize_fixture, team
):
    """Escape backs out of the search first; categorize mode is only left from an empty box."""
    categorize = CategorizePage(authenticated_page, live_server.url)
    categorize.goto(team.slug)

    categorize.search("zed dining")
    categorize.press("Escape")

    assert "/categorize/" in authenticated_page.url
    assert categorize.search_box.input_value() == ""
    assert categorize.active_row_name() is None


@pytest.mark.django_db(transaction=True)
def test_suggestions_name_the_transactions_behind_them(
    requires_vite, authenticated_page: Page, live_server, categorize_fixture, team
):
    """A category used on two transactions with this payee is suggested, and says so."""
    account = categorize_fixture["account"]
    groceries = categorize_fixture["categories"]["Zed Groceries"]
    for _ in range(2):
        feed_transaction(team, account, category=groceries, merchant_name="Blue Bottle", description="HISTORY")

    categorize = CategorizePage(authenticated_page, live_server.url)
    categorize.goto(team.slug)
    categorize.wait_for_suggestions()

    assert categorize.suggestion_notes() == ["2 transactions with this payee were categorized as this"]


@pytest.mark.django_db(transaction=True)
def test_payee_and_description_are_editable_on_the_card(
    requires_vite, authenticated_page: Page, live_server, categorize_fixture, team
):
    """The card at the top of the stack shows the bank's payee/description in editable fields."""
    categorize = CategorizePage(authenticated_page, live_server.url)
    categorize.goto(team.slug)

    assert categorize.current_card_title() == "Blue Bottle"
    assert categorize.current_card_description() == "UNCATEGORIZED ROW"
    assert not categorize.details_are_dirty()

    categorize.edit_payee("Blue Bottle Coffee")
    assert categorize.details_are_dirty()


@pytest.mark.django_db(transaction=True)
def test_edits_are_saved_with_the_categorization(
    requires_vite, authenticated_page: Page, live_server, categorize_fixture, team
):
    """Nothing is written while typing — the edits land in the same step that files the card."""
    row = categorize_fixture["row"]

    categorize = CategorizePage(authenticated_page, live_server.url)
    categorize.goto(team.slug)

    categorize.edit_payee("Blue Bottle Coffee")
    categorize.edit_description("Morning coffee")

    # Still untouched in the database: a draft is not a save.
    row.refresh_from_db()
    assert row.merchant_name == "Blue Bottle"
    assert row.description == "UNCATEGORIZED ROW"

    categorize.search("zed coffee")
    categorize.press("Enter")
    authenticated_page.wait_for_timeout(1_500)

    row.refresh_from_db()
    assert row.merchant_name == "Blue Bottle Coffee"
    assert row.description == "Morning coffee"
    # The edits reach the ledger too, not just the staging row.
    assert row.journal_entry is not None
    assert row.journal_entry.description == "Morning coffee"
    assert row.journal_entry.payee.name == "Blue Bottle Coffee"
    categorized_to = {line.account.name for line in row.journal_entry.lines.all() if line.account_id != row.account_id}
    assert categorized_to == {"Zed Coffee"}


@pytest.mark.django_db(transaction=True)
def test_revert_puts_the_banks_wording_back(
    requires_vite, authenticated_page: Page, live_server, categorize_fixture, team
):
    """Revert drops the draft, leaving the card as the bank reported it."""
    categorize = CategorizePage(authenticated_page, live_server.url)
    categorize.goto(team.slug)

    categorize.edit_payee("Something else")
    categorize.edit_description("Something else entirely")
    assert categorize.details_are_dirty()

    categorize.revert_details()

    assert not categorize.details_are_dirty()
    assert categorize.current_card_title() == "Blue Bottle"
    assert categorize.current_card_description() == "UNCATEGORIZED ROW"


@pytest.mark.django_db(transaction=True)
def test_escape_in_an_edited_field_stays_in_categorize_mode(
    requires_vite, authenticated_page: Page, live_server, categorize_fixture, team
):
    """Escape backs out of the edit, never out of the queue — losing your place mid-word is worse."""
    categorize = CategorizePage(authenticated_page, live_server.url)
    categorize.goto(team.slug)

    categorize.description_field.fill("Half-typed")
    categorize.description_field.press("Escape")

    assert "/categorize/" in authenticated_page.url
    assert categorize.current_card_description() == "UNCATEGORIZED ROW"


@pytest.mark.django_db(transaction=True)
def test_a_draft_survives_a_skip(requires_vite, authenticated_page: Page, live_server, categorize_fixture, team):
    """A skipped card comes back around, so the edit that was typed on it is still there."""
    account = categorize_fixture["account"]
    feed_transaction(team, account, description="SECOND ROW", merchant_name="Other Merchant")

    categorize = CategorizePage(authenticated_page, live_server.url)
    categorize.goto(team.slug)

    categorize.edit_payee("Renamed while passing through")

    # Skipping rotates the edited card to the back of the queue...
    authenticated_page.get_by_role("button", name="Skip for now").click()
    authenticated_page.wait_for_timeout(600)
    assert categorize.current_card_title() != "Renamed while passing through"

    # ...and skipping the other one brings it back with the draft intact.
    authenticated_page.get_by_role("button", name="Skip for now").click()
    authenticated_page.wait_for_timeout(600)
    assert categorize.current_card_title() == "Renamed while passing through"
    assert categorize.details_are_dirty()
