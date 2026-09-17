"""
E2E tests for the Bank Feed feature (React SPA).

NOTE: These tests require the Vite dev server to be running alongside the
Django live server. Run `make start-bg` first (which starts the vite container),
then run `make test-e2e ARGS="e2e/tests/test_bank_feed.py"`.

Covers: account cards displayed, selecting an account, filter toggles,
add-transaction modal opens.
"""

from decimal import Decimal

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


# ----------------------------------------------------------------------
# Batch action bar contract
#
# These lock which actions the bar offers for a given selection BEFORE it
# is rewritten off MUI (restyle plan Phase 7). The bar's availability
# rules are not cosmetic: Reconcile is withheld from an uncategorized
# selection, and Duplicate and Reconcile are withheld once any selected
# row is reconciled. They are addressed by button label rather than
# testid, so the rewrite has to keep the labels a user reads.
# ----------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_no_batch_bar_until_a_row_is_selected(requires_vite, authenticated_page, live_server, feed_fixture):
    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(feed_fixture["account"].team.slug)
    feed.click_account_card(feed_fixture["account"].id)
    feed.wait_for_table()

    assert feed.batch_buttons() == []


@pytest.mark.django_db(transaction=True)
def test_uncategorized_selection_cannot_reconcile(requires_vite, authenticated_page, live_server, feed_fixture):
    """Reconcile is offered but disabled — reconciling an uncategorized row is meaningless."""
    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(feed_fixture["account"].team.slug)
    feed.click_account_card(feed_fixture["account"].id)
    feed.wait_for_table()
    feed.select_row(feed_fixture["rows"]["uncategorized"].id)

    assert feed.batch_buttons() == ["Bulk Edit", "Archive", "Reconcile", "Duplicate", "Export"]
    assert feed.batch_button("Reconcile").is_disabled()


@pytest.mark.django_db(transaction=True)
def test_categorized_unreconciled_selection_can_reconcile(requires_vite, authenticated_page, live_server, feed_fixture):
    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(feed_fixture["account"].team.slug)
    feed.click_account_card(feed_fixture["account"].id)
    feed.wait_for_table()
    feed.select_row(feed_fixture["rows"]["unreconciled"].id)

    assert feed.batch_buttons() == ["Bulk Edit", "Archive", "Reconcile", "Duplicate", "Export"]
    assert feed.batch_button("Reconcile").is_enabled()


@pytest.mark.django_db(transaction=True)
def test_reconciled_selection_offers_unreconcile_not_reconcile(
    requires_vite, authenticated_page, live_server, feed_fixture
):
    """A reconciled row can be undone, but not re-reconciled or duplicated.

    Archive is withheld too: `showArchiveButton` in `LineApp` requires *some*
    selected row to be neither archived nor reconciled, which mirrors the server
    guard that refuses to archive a reconciled transfer leg. A mixed selection
    does show Archive — see the next test.
    """
    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(feed_fixture["account"].team.slug)
    feed.click_account_card(feed_fixture["account"].id)
    feed.wait_for_table()
    feed.select_row(feed_fixture["rows"]["reconciled"].id)

    assert feed.batch_buttons() == ["Bulk Edit", "Unreconcile", "Export"]


@pytest.mark.django_db(transaction=True)
def test_mixed_selection_withholds_both_reconcile_and_unreconcile(
    requires_vite, authenticated_page, live_server, feed_fixture
):
    """One reconciled row in the selection is enough to withhold Reconcile and Duplicate;
    Unreconcile needs *all* of them reconciled, so a mixed selection gets neither."""
    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(feed_fixture["account"].team.slug)
    feed.click_account_card(feed_fixture["account"].id)
    feed.wait_for_table()
    feed.select_row(feed_fixture["rows"]["reconciled"].id)
    feed.select_row(feed_fixture["rows"]["unreconciled"].id)

    assert feed.batch_buttons() == ["Bulk Edit", "Archive", "Export"]


@pytest.mark.django_db(transaction=True)
def test_archived_view_offers_unarchive_and_delete_only(requires_vite, authenticated_page, live_server, feed_fixture):
    """The archived view is a different set of verbs: nothing to edit, reconcile or duplicate."""
    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(feed_fixture["account"].team.slug)
    feed.click_account_card(feed_fixture["account"].id)
    feed.wait_for_table()
    feed.click_filter("archived")
    feed.select_row(feed_fixture["rows"]["archived"].id)

    assert feed.batch_buttons() == ["Unarchive", "Delete", "Export"]


@pytest.mark.django_db(transaction=True)
def test_clearing_the_selection_dismisses_the_bar(requires_vite, authenticated_page, live_server, feed_fixture):
    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(feed_fixture["account"].team.slug)
    feed.click_account_card(feed_fixture["account"].id)
    feed.wait_for_table()
    feed.select_row(feed_fixture["rows"]["unreconciled"].id)
    assert feed.batch_buttons() != []

    feed.deselect_row(feed_fixture["rows"]["unreconciled"].id)

    assert feed.batch_buttons() == []


@pytest.mark.django_db(transaction=True)
def test_bulk_edit_opens_from_the_bar(requires_vite, authenticated_page, live_server, feed_fixture):
    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(feed_fixture["account"].team.slug)
    feed.click_account_card(feed_fixture["account"].id)
    feed.wait_for_table()
    feed.select_row(feed_fixture["rows"]["unreconciled"].id)
    feed.batch_button("Bulk Edit").click()

    assert authenticated_page.get_by_text("Bulk Edit", exact=False).count() > 1


# ----------------------------------------------------------------------
# Transfer duplicate review contract
#
# The review modal's archive buttons mirror a server guard: a reconciled
# leg cannot be archived, because resolving voids the shared journal
# entry. Locked here before the modal is rewritten off MUI.
# ----------------------------------------------------------------------


@pytest.fixture
def transfer_pair(team):
    """Two accounts reporting the same movement — the double-count the review modal exists for."""
    group = AccountGroupFactory(team=team)
    chequing = AssetAccountFactory(team=team, account_group=group, has_feed=True, name="Chequing")
    savings = AssetAccountFactory(team=team, account_group=group, has_feed=True, name="Savings")

    # Equal magnitude, opposite direction, same day: positive = outflow.
    out_leg = feed_transaction(
        team, chequing, amount=Decimal("500.00"), posted_date="2026-03-02", description="PAIR-A-OUT"
    )
    in_leg = feed_transaction(
        team, savings, amount=Decimal("-500.00"), posted_date="2026-03-02", description="PAIR-A-IN"
    )
    return {"chequing": chequing, "savings": savings, "out_leg": out_leg, "in_leg": in_leg}


@pytest.mark.django_db(transaction=True)
def test_transfer_review_surfaces_a_candidate_pair(requires_vite, authenticated_page, live_server, transfer_pair):
    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(transfer_pair["chequing"].team.slug)
    feed.click_account_card(transfer_pair["chequing"].id)
    feed.wait_for_table()
    feed.open_transfer_review()

    assert feed.transfer_suggestion_count() == 1
    assert feed.transfer_archive_button("Chequing").is_enabled()
    assert feed.transfer_archive_button("Savings").is_enabled()
    assert feed.transfer_dismiss_button().is_enabled()


@pytest.mark.django_db(transaction=True)
def test_reconciled_leg_cannot_be_archived_from_the_review(
    requires_vite, authenticated_page, live_server, transfer_pair, team
):
    """The button for a reconciled leg is disabled, mirroring the server's refusal."""
    expense_group = AccountGroupFactory(team=team)
    category = AccountFactory(team=team, account_group=expense_group)
    reconciled_leg = feed_transaction(
        team,
        transfer_pair["savings"],
        category=category,
        reconciled=True,
        amount=Decimal("-750.00"),
        posted_date="2026-04-02",
        description="PAIR-B-IN-RECONCILED",
    )
    feed_transaction(
        team,
        transfer_pair["chequing"],
        amount=Decimal("750.00"),
        posted_date="2026-04-02",
        description="PAIR-B-OUT",
    )
    assert reconciled_leg.pk  # the pair only surfaces once both legs exist

    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(transfer_pair["chequing"].team.slug)
    feed.click_account_card(transfer_pair["chequing"].id)
    feed.wait_for_table()
    feed.open_transfer_review()

    # Two pairs now: the plain one from the fixture and the reconciled one. Both
    # involve Savings, so the buttons have to be scoped to the right card rather
    # than looked up by label across the whole modal.
    assert feed.transfer_suggestion_count() == 2
    card = feed.transfer_suggestion_containing("PAIR-B-IN-RECONCILED")
    assert card.get_by_text("Reconciled", exact=True).count() == 1

    # The reconciled leg cannot be archived; its unreconciled counterpart still can.
    assert card.get_by_role("button", name="Duplicate — archive Savings").is_disabled()
    assert card.get_by_role("button", name="Duplicate — archive Chequing").is_enabled()

    # The other pair, with nothing reconciled, is unaffected.
    plain = feed.transfer_suggestion_containing("PAIR-A-OUT")
    assert plain.get_by_role("button", name="Duplicate — archive Savings").is_enabled()


@pytest.mark.django_db(transaction=True)
def test_dismissing_a_pair_removes_it_from_the_review(requires_vite, authenticated_page, live_server, transfer_pair):
    """'Not a duplicate' records a dismissal, so the pair stops being suggested."""
    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(transfer_pair["chequing"].team.slug)
    feed.click_account_card(transfer_pair["chequing"].id)
    feed.wait_for_table()
    feed.open_transfer_review()
    feed.transfer_dismiss_button().click()
    authenticated_page.get_by_text("All transfers reviewed.").wait_for(timeout=10_000)

    assert feed.transfer_suggestion_count() == 0
