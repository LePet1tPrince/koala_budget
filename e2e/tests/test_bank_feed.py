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

from apps.accounts.models import ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY
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
    feed.goto(team.default_book)

    assert feed.has_account_card(feed_account.id)
    assert feed.get_account_card_count() == 1


@pytest.mark.django_db(transaction=True)
def test_selecting_account_shows_filter_toggles(requires_vite, authenticated_page: Page, live_server, team):
    """Clicking an account card loads the bank feed table with filter toggles."""
    group = AccountGroupFactory(team=team)
    feed_account = AssetAccountFactory(team=team, account_group=group, has_feed=True)

    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(team.default_book)
    feed.click_account_card(feed_account.id)

    assert feed.is_filter_visible()


@pytest.mark.django_db(transaction=True)
def test_add_transaction_modal_opens(requires_vite, authenticated_page: Page, live_server, team):
    """Clicking the add-transaction button opens the edit modal."""
    group = AccountGroupFactory(team=team)
    feed_account = AssetAccountFactory(team=team, account_group=group, has_feed=True)

    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(team.default_book)
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
    feed.goto(feed_fixture["account"].book)
    feed.click_account_card(feed_fixture["account"].id)
    feed.wait_for_table()

    assert feed.has_row_matching("ROW-UNCATEGORIZED")
    assert feed.has_row_matching("ROW-UNRECONCILED")
    assert feed.has_row_matching("ROW-RECONCILED")
    assert not feed.has_row_matching("ROW-ARCHIVED")


@pytest.mark.django_db(transaction=True)
def test_to_review_filter_hides_reconciled(requires_vite, authenticated_page, live_server, feed_fixture):
    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(feed_fixture["account"].book)
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
    feed.goto(feed_fixture["account"].book)
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
    feed.goto(feed_fixture["account"].book)
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
    feed.goto(feed_fixture["account"].book)
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
    feed.goto(feed_fixture["account"].book)
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
    feed.goto(feed_fixture["account"].book)
    feed.click_account_card(feed_fixture["account"].id)
    feed.wait_for_table()

    assert feed.batch_buttons() == []


@pytest.mark.django_db(transaction=True)
def test_uncategorized_selection_cannot_reconcile(requires_vite, authenticated_page, live_server, feed_fixture):
    """Reconcile is offered but disabled — reconciling an uncategorized row is meaningless."""
    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(feed_fixture["account"].book)
    feed.click_account_card(feed_fixture["account"].id)
    feed.wait_for_table()
    feed.select_row(feed_fixture["rows"]["uncategorized"].id)

    assert feed.batch_buttons() == ["Bulk Edit", "Archive", "Reconcile", "Duplicate", "Export"]
    assert feed.batch_button("Reconcile").is_disabled()


@pytest.mark.django_db(transaction=True)
def test_categorized_unreconciled_selection_can_reconcile(requires_vite, authenticated_page, live_server, feed_fixture):
    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(feed_fixture["account"].book)
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
    feed.goto(feed_fixture["account"].book)
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
    feed.goto(feed_fixture["account"].book)
    feed.click_account_card(feed_fixture["account"].id)
    feed.wait_for_table()
    feed.select_row(feed_fixture["rows"]["reconciled"].id)
    feed.select_row(feed_fixture["rows"]["unreconciled"].id)

    assert feed.batch_buttons() == ["Bulk Edit", "Archive", "Export"]


@pytest.mark.django_db(transaction=True)
def test_archived_view_offers_unarchive_and_delete_only(requires_vite, authenticated_page, live_server, feed_fixture):
    """The archived view is a different set of verbs: nothing to edit, reconcile or duplicate."""
    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(feed_fixture["account"].book)
    feed.click_account_card(feed_fixture["account"].id)
    feed.wait_for_table()
    feed.click_filter("archived")
    feed.select_row(feed_fixture["rows"]["archived"].id)

    assert feed.batch_buttons() == ["Unarchive", "Delete", "Export"]


@pytest.mark.django_db(transaction=True)
def test_clearing_the_selection_dismisses_the_bar(requires_vite, authenticated_page, live_server, feed_fixture):
    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(feed_fixture["account"].book)
    feed.click_account_card(feed_fixture["account"].id)
    feed.wait_for_table()
    feed.select_row(feed_fixture["rows"]["unreconciled"].id)
    assert feed.batch_buttons() != []

    feed.deselect_row(feed_fixture["rows"]["unreconciled"].id)

    assert feed.batch_buttons() == []


@pytest.mark.django_db(transaction=True)
def test_bulk_edit_opens_from_the_bar(requires_vite, authenticated_page, live_server, feed_fixture):
    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(feed_fixture["account"].book)
    feed.click_account_card(feed_fixture["account"].id)
    feed.wait_for_table()
    feed.select_row(feed_fixture["rows"]["unreconciled"].id)
    feed.batch_button("Bulk Edit").click()

    assert authenticated_page.get_by_text("Bulk Edit", exact=False).count() > 1


# ----------------------------------------------------------------------
# Possible duplicate transfers, matched inline
#
# A transfer between two of the user's own accounts is reported by both
# banks. Each leg's row carries a chip; its panel shows the other leg and
# what Match will do. The server picks the leg to archive (a reconciled leg
# is always kept), so the panel's sentence is what the click does.
# ----------------------------------------------------------------------


@pytest.fixture
def transfer_pair(team):
    """Two accounts reporting the same movement — the double-count matching exists for."""
    # An asset group: a transfer only mirrors into the other feed between asset/liability accounts.
    group = AccountGroupFactory(team=team, account_type=ACCOUNT_TYPE_ASSET)
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


def _open_feed(page, live_server, account):
    feed = BankFeedPage(page, live_server.url)
    feed.goto(account.book)
    feed.click_account_card(account.id)
    feed.wait_for_table()
    return feed


def _switch_account(feed, account):
    feed.open_account_picker()
    feed.click_account_card(account.id)
    feed.wait_for_table()


@pytest.mark.django_db(transaction=True)
def test_possible_transfer_chip_shows_in_both_feeds(requires_vite, authenticated_page, live_server, transfer_pair):
    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(transfer_pair["chequing"].book)
    # Each account's card counts the pairs with a leg there.
    authenticated_page.locator("[data-testid='card-match-count']").first.wait_for(timeout=10_000)
    assert feed.account_card_match_count(transfer_pair["chequing"].id) == "1"
    assert feed.account_card_match_count(transfer_pair["savings"].id) == "1"

    feed.click_account_card(transfer_pair["chequing"].id)
    feed.wait_for_table()
    feed.match_chip(transfer_pair["out_leg"].id).wait_for(timeout=10_000)

    _switch_account(feed, transfer_pair["savings"])
    feed.match_chip(transfer_pair["in_leg"].id).wait_for(timeout=10_000)


@pytest.mark.django_db(transaction=True)
def test_panel_shows_the_other_side_and_the_outcome(requires_vite, authenticated_page, live_server, transfer_pair):
    feed = _open_feed(authenticated_page, live_server, transfer_pair["chequing"])
    feed.match_chip(transfer_pair["out_leg"].id).wait_for(timeout=10_000)
    feed.open_match(transfer_pair["out_leg"].id)

    counterpart = feed.match_counterpart_text()
    assert "Savings" in counterpart
    assert "PAIR-A-IN" in counterpart
    # Nothing reconciled or categorized, same source: the outflow (this row) is kept.
    assert "keeps this transaction and archives the one in Savings" in feed.match_outcome_text()
    assert feed.match_button().is_enabled()

    # Escape closes the panel without changing anything.
    authenticated_page.keyboard.press("Escape")
    feed.match_panel().wait_for(state="detached", timeout=5_000)
    assert feed.has_match_chip(transfer_pair["out_leg"].id)


@pytest.mark.django_db(transaction=True)
def test_match_keeps_the_reconciled_leg(requires_vite, authenticated_page, live_server, transfer_pair, team):
    """With one side reconciled, Match archives the other and the transfer shows in both feeds."""
    expense_group = AccountGroupFactory(team=team)
    category = AccountFactory(team=team, account_group=expense_group)
    feed_transaction(
        team,
        transfer_pair["savings"],
        category=category,
        reconciled=True,
        amount=Decimal("-750.00"),
        posted_date="2026-04-02",
        description="PAIR-B-IN-RECONCILED",
    )
    out_b = feed_transaction(
        team,
        transfer_pair["chequing"],
        amount=Decimal("750.00"),
        posted_date="2026-04-02",
        description="PAIR-B-OUT",
    )

    feed = _open_feed(authenticated_page, live_server, transfer_pair["chequing"])
    feed.match_chip(out_b.id).wait_for(timeout=10_000)
    feed.open_match(out_b.id)
    outcome = feed.match_outcome_text()
    assert "keeps the one in Savings and archives this transaction" in outcome
    assert "reconciled" in outcome

    feed.match_button().click()
    authenticated_page.get_by_text("Matched — kept the one in Savings", exact=False).wait_for(timeout=10_000)

    # PAIR-B-OUT is archived; the kept leg's transfer now shows here as its mirror.
    authenticated_page.locator(f"[data-testid='feed-row-{out_b.id}']").wait_for(state="detached", timeout=10_000)
    assert feed.has_row_matching("PAIR-B-IN-RECONCILED")
    assert not feed.has_match_chip(out_b.id)
    # The other pair is untouched.
    assert feed.has_match_chip(transfer_pair["out_leg"].id)


@pytest.mark.django_db(transaction=True)
def test_match_is_unavailable_when_both_sides_are_reconciled(
    requires_vite, authenticated_page, live_server, transfer_pair, team
):
    expense_group = AccountGroupFactory(team=team)
    category = AccountFactory(team=team, account_group=expense_group)
    for account, amount, description in (
        (transfer_pair["savings"], "-750.00", "PAIR-C-IN"),
        (transfer_pair["chequing"], "750.00", "PAIR-C-OUT"),
    ):
        tx = feed_transaction(
            team,
            account,
            category=category,
            reconciled=True,
            amount=Decimal(amount),
            posted_date="2026-05-02",
            description=description,
        )
    out_c = tx

    feed = _open_feed(authenticated_page, live_server, transfer_pair["chequing"])
    feed.match_chip(out_c.id).wait_for(timeout=10_000)
    feed.open_match(out_c.id)

    assert "Both sides are reconciled" in feed.match_outcome_text()
    assert feed.match_button().is_disabled()
    assert feed.not_a_match_button().is_enabled()


@pytest.mark.django_db(transaction=True)
def test_not_a_match_removes_the_chip_from_both_feeds(requires_vite, authenticated_page, live_server, transfer_pair):
    feed = _open_feed(authenticated_page, live_server, transfer_pair["chequing"])
    feed.match_chip(transfer_pair["out_leg"].id).wait_for(timeout=10_000)
    feed.open_match(transfer_pair["out_leg"].id)
    feed.not_a_match_button().click()
    feed.match_chip(transfer_pair["out_leg"].id).wait_for(state="detached", timeout=10_000)

    _switch_account(feed, transfer_pair["savings"])
    assert feed.has_row_matching("PAIR-A-IN")
    assert not feed.has_match_chip(transfer_pair["in_leg"].id)

    # Recorded server-side, so it survives a reload.
    feed = _open_feed(authenticated_page, live_server, transfer_pair["chequing"])
    assert feed.has_row_matching("PAIR-A-OUT")
    assert not feed.has_match_chip(transfer_pair["out_leg"].id)


@pytest.mark.django_db(transaction=True)
def test_go_to_other_side_opens_the_counterpart(requires_vite, authenticated_page, live_server, transfer_pair):
    feed = _open_feed(authenticated_page, live_server, transfer_pair["chequing"])
    feed.match_chip(transfer_pair["out_leg"].id).wait_for(timeout=10_000)
    feed.open_match(transfer_pair["out_leg"].id)
    feed.goto_counterpart_button().click()

    authenticated_page.get_by_text("Lines for Savings").wait_for(timeout=10_000)
    row = authenticated_page.locator(f"[data-testid='feed-row-{transfer_pair['in_leg'].id}']")
    row.wait_for(timeout=10_000)
    assert "feed-row-flash" in (row.get_attribute("class") or "")


@pytest.mark.django_db(transaction=True)
def test_possible_transfers_quick_filter(requires_vite, authenticated_page, live_server, transfer_pair, team):
    feed_transaction(
        team,
        transfer_pair["chequing"],
        amount=Decimal("12.34"),
        posted_date="2026-03-03",
        description="NOT-A-TRANSFER",
    )
    feed = _open_feed(authenticated_page, live_server, transfer_pair["chequing"])
    feed.match_chip(transfer_pair["out_leg"].id).wait_for(timeout=10_000)
    assert feed.has_row_matching("NOT-A-TRANSFER")

    feed.click_filter("transfers")

    assert feed.has_row_matching("PAIR-A-OUT")
    assert not feed.has_row_matching("NOT-A-TRANSFER")


@pytest.mark.django_db(transaction=True)
def test_csv_category_picker_is_keyboard_driven(requires_vite, authenticated_page: Page, live_server, team, tmp_path):
    """
    The Map Categories picker: the search filters, ↑/↓ move the highlight (stopping
    at the ends), Enter takes it. Shared with the YNAB import's chip menus through
    `common/useListNavigation`, so this locks the behaviour both rely on.
    """
    group = AccountGroupFactory(team=team, name="Zed Spending")
    AccountFactory(team=team, account_group=group, name="Zed Groceries")
    AccountFactory(team=team, account_group=group, name="Zed Dining")
    feed_account = AssetAccountFactory(team=team, has_feed=True)
    csv_file = tmp_path / "statement.csv"
    csv_file.write_text("Date,Description,Amount,Category\n2026-01-05,Grocer,-40.00,Food\n")

    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(team.default_book)
    feed.click_account_card(feed_account.id)
    feed.open_csv_upload(str(csv_file))
    page = authenticated_page
    page.get_by_role("button", name="Next", exact=True).click()

    trigger = page.get_by_role("button", name="-- Leave uncategorized --")
    trigger.click()
    search = page.get_by_placeholder("Search accounts...")
    search.fill("zed")
    # Rows: "Leave uncategorized", Zed Dining, Zed Groceries, "Create new account".
    search.press("ArrowUp")  # already at the top: stays there
    search.press("ArrowDown")
    search.press("ArrowDown")
    search.press("Enter")
    assert page.get_by_role("button", name="Zed Groceries").is_visible()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("account_type", "inverted", "hint"),
    [
        (ACCOUNT_TYPE_ASSET, True, "Positive amounts are money in, negative are money out."),
        (ACCOUNT_TYPE_LIABILITY, False, "Positive amounts are money out, negative are money in."),
    ],
)
def test_csv_sign_convention_defaults_by_account_type(
    requires_vite, authenticated_page: Page, live_server, team, tmp_path, account_type, inverted, hint
):
    """
    A single amount column defaults to the account's usual export convention: a bank
    account writes a deposit as positive (money in), a credit card writes a charge as
    positive (money out).
    """
    group = AccountGroupFactory(team=team, name=f"Zed {account_type}", account_type=account_type)
    feed_account = AccountFactory(team=team, account_group=group, has_feed=True)
    csv_file = tmp_path / "statement.csv"
    csv_file.write_text("Date,Description,Amount\n2026-01-05,Grocer,-40.00\n")

    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(team.default_book)
    feed.click_account_card(feed_account.id)
    feed.open_csv_upload(str(csv_file))

    checkbox = authenticated_page.locator("[data-testid='invert-amounts']")
    assert checkbox.is_checked() is inverted
    assert authenticated_page.get_by_text(hint, exact=True).is_visible()
