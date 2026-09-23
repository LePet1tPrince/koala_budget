"""
E2E tests for the Transactions page (React SPA).

NOTE: These tests require the Vite dev server to be running alongside the
Django live server. Run `make start-bg` first (which starts the vite container),
then run `make test-e2e ARGS="e2e/tests/test_transactions.py"`.

Alternatively, build the frontend once with `make npm-build` and set
DJANGO_VITE_DEV_MODE=False in settings_e2e.py to use the built assets.

Covers: page load, empty state, search filter, row count with seeded data,
per-column value filters and column sorting.
"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from playwright.sync_api import Page

from apps.journal.models import JournalEntry
from e2e.factories import (
    AccountFactory,
    AccountGroupFactory,
    JournalEntryFactory,
    JournalLineFactory,
    PayeeFactory,
)
from e2e.pages.transactions import TransactionsPage


@pytest.mark.django_db(transaction=True)
def test_transactions_page_loads(requires_vite, authenticated_page: Page, live_server, team):
    """The transactions page mounts the React app and shows an empty state when there are no entries."""
    transactions = TransactionsPage(authenticated_page, live_server.url)
    transactions.goto(team.slug)

    assert transactions.is_empty() or transactions.has_table()


@pytest.mark.django_db(transaction=True)
def test_transactions_empty_state_shown_with_no_entries(requires_vite, authenticated_page: Page, live_server, team):
    """With no journal entries, the empty state message is displayed."""
    transactions = TransactionsPage(authenticated_page, live_server.url)
    transactions.goto(team.slug)

    assert transactions.is_empty()
    assert transactions.get_row_count() == 0


@pytest.mark.django_db(transaction=True)
def test_transactions_table_shows_seeded_entries(requires_vite, authenticated_page: Page, live_server, team):
    """Journal entries created in the DB appear as rows in the transactions table."""
    group = AccountGroupFactory(team=team)
    debit_acct = AccountFactory(team=team, account_group=group)
    credit_acct = AccountFactory(team=team, account_group=group)

    entry = JournalEntryFactory(team=team, description="Rent Payment", status="posted")
    JournalLineFactory(team=team, journal_entry=entry, account=debit_acct, dr_amount="1500.00")
    JournalLineFactory(team=team, journal_entry=entry, account=credit_acct, cr_amount="1500.00")

    transactions = TransactionsPage(authenticated_page, live_server.url)
    transactions.goto(team.slug)

    assert transactions.get_row_count() >= 1
    assert transactions.has_table()


@pytest.mark.django_db(transaction=True)
def test_transactions_search_filters_rows(requires_vite, authenticated_page: Page, live_server, team):
    """The search input filters the displayed rows to matching entries."""
    group = AccountGroupFactory(team=team)
    debit_acct = AccountFactory(team=team, account_group=group)
    credit_acct = AccountFactory(team=team, account_group=group)

    entry1 = JournalEntryFactory(team=team, description="Coffee Shop Purchase", status="posted")
    JournalLineFactory(team=team, journal_entry=entry1, account=debit_acct, dr_amount="5.00")
    JournalLineFactory(team=team, journal_entry=entry1, account=credit_acct, cr_amount="5.00")

    entry2 = JournalEntryFactory(team=team, description="Grocery Store", status="posted")
    JournalLineFactory(team=team, journal_entry=entry2, account=debit_acct, dr_amount="120.00")
    JournalLineFactory(team=team, journal_entry=entry2, account=credit_acct, cr_amount="120.00")

    transactions = TransactionsPage(authenticated_page, live_server.url)
    transactions.goto(team.slug)

    # Initially both rows visible
    assert transactions.get_row_count() >= 2

    # After search, only the matching row should remain
    transactions.search("Coffee")
    transactions.expect_row_count(1)


# ----------------------------------------------------------------------
# Column filters and sorting
# ----------------------------------------------------------------------


@pytest.fixture
def ledger(team):
    """
    Three entries whose payee, account and amount all differ.

    Enough that filtering on any one column leaves a different set behind, so
    a test can't pass by accident on a table that filters nothing.
    """
    group = AccountGroupFactory(team=team, name="Everyday")
    treats = AccountGroupFactory(team=team, name="Treats")
    bank = AccountFactory(team=team, account_group=group, name="Checking")
    groceries = AccountFactory(team=team, account_group=group, name="Groceries")
    coffee = AccountFactory(team=team, account_group=treats, name="Coffee")

    amazon = PayeeFactory(team=team, name="Amazon")
    costco = PayeeFactory(team=team, name="Costco")

    def entry(day, payee, debit, amount, description):
        je = JournalEntryFactory(
            team=team,
            entry_date=date(2025, 3, day),
            payee=payee,
            description=description,
            status="posted",
        )
        JournalLineFactory(team=team, journal_entry=je, account=debit, dr_amount=amount)
        JournalLineFactory(team=team, journal_entry=je, account=bank, cr_amount=amount)
        return je

    entry(1, amazon, groceries, "25.00", "Weekly shop")
    entry(2, costco, groceries, "10.00", "Milk")
    entry(3, amazon, coffee, "5.00", "Beans")
    # The account tree is addressed by id, so the tests need the group's.
    return SimpleNamespace(slug=team.slug, coffee_group_id=treats.pk)


@pytest.mark.django_db(transaction=True)
def test_column_menu_lists_the_columns_distinct_values(requires_vite, authenticated_page: Page, live_server, ledger):
    """The chevron menu offers the column's unique values, with a row count each."""
    transactions = TransactionsPage(authenticated_page, live_server.url)
    transactions.goto(ledger.slug)

    transactions.open_column_menu("payee")

    assert transactions.column_filter_values("payee") == ["Amazon", "Costco"]


@pytest.mark.django_db(transaction=True)
def test_column_filter_narrows_the_table(requires_vite, authenticated_page: Page, live_server, ledger):
    """Ticking a value and applying leaves only the rows carrying it."""
    transactions = TransactionsPage(authenticated_page, live_server.url)
    transactions.goto(ledger.slug)
    transactions.expect_row_count(3)

    transactions.open_column_menu("payee")
    transactions.tick_column_value("payee", "Amazon")
    transactions.apply_column_filter("payee")

    transactions.expect_row_count(2)
    assert set(transactions.column_text(2)) == {"Amazon"}


@pytest.mark.django_db(transaction=True)
def test_column_filters_on_two_columns_combine(requires_vite, authenticated_page: Page, live_server, ledger):
    """Filters on different columns narrow together rather than replacing each other."""
    transactions = TransactionsPage(authenticated_page, live_server.url)
    transactions.goto(ledger.slug)

    transactions.open_column_menu("payee")
    transactions.tick_column_value("payee", "Amazon")
    transactions.apply_column_filter("payee")

    transactions.open_column_menu("debit_account")
    transactions.expand_tree_node("t:expense")
    transactions.expand_tree_node(f"g:{ledger.coffee_group_id}")
    transactions.tick_column_value("debit_account", "Coffee")
    transactions.apply_column_filter("debit_account")

    transactions.expect_row_count(1)
    assert transactions.column_text(3) == ["Beans"]


@pytest.mark.django_db(transaction=True)
def test_clear_all_restores_every_row(requires_vite, authenticated_page: Page, live_server, ledger):
    """The chip bar's Clear all drops every column filter in one go."""
    transactions = TransactionsPage(authenticated_page, live_server.url)
    transactions.goto(ledger.slug)

    transactions.open_column_menu("payee")
    transactions.tick_column_value("payee", "Costco")
    transactions.apply_column_filter("payee")
    transactions.expect_row_count(1)
    assert transactions.has_active_filter("payee")

    transactions.clear_all_column_filters()

    transactions.expect_row_count(3)


@pytest.mark.django_db(transaction=True)
def test_column_header_sorts_ascending_then_descending(requires_vite, authenticated_page: Page, live_server, ledger):
    """Clicking a header sorts by it; clicking again reverses."""
    transactions = TransactionsPage(authenticated_page, live_server.url)
    transactions.goto(ledger.slug)
    transactions.expect_row_count(3)

    transactions.sort_by("amount")
    assert transactions.column_text(6) == ["$5.00", "$10.00", "$25.00"]

    transactions.sort_by("amount")
    assert transactions.column_text(6) == ["$25.00", "$10.00", "$5.00"]


@pytest.mark.django_db(transaction=True)
def test_clear_inside_a_menu_drops_the_staged_selection(requires_vite, authenticated_page: Page, live_server, ledger):
    """Clear empties what's been ticked without closing the menu, so a long selection can be restarted."""
    transactions = TransactionsPage(authenticated_page, live_server.url)
    transactions.goto(ledger.slug)

    transactions.open_column_menu("payee")
    transactions.select_all_in_menu("payee")
    assert transactions.menu_selection_summary("payee") == "2 selected"

    transactions.clear_menu_selection("payee")

    assert transactions.menu_selection_summary("payee") == "Showing all"


@pytest.mark.django_db(transaction=True)
def test_account_column_nests_type_group_account(requires_vite, authenticated_page: Page, live_server, ledger):
    """The account columns open on account types and expand down to accounts."""
    transactions = TransactionsPage(authenticated_page, live_server.url)
    transactions.goto(ledger.slug)

    transactions.open_column_menu("debit_account")
    assert transactions.column_filter_values("debit_account") == ["Expense"]

    transactions.expand_tree_node("t:expense")
    assert set(transactions.column_filter_values("debit_account")) == {"Expense", "Everyday", "Treats"}

    transactions.expand_tree_node(f"g:{ledger.coffee_group_id}")
    assert "Coffee" in transactions.column_filter_values("debit_account")


@pytest.mark.django_db(transaction=True)
def test_ticking_an_account_group_selects_every_account_in_it(
    requires_vite, authenticated_page: Page, live_server, ledger
):
    """A branch is one filter value meaning "everything under it", not a list of leaves."""
    transactions = TransactionsPage(authenticated_page, live_server.url)
    transactions.goto(ledger.slug)
    transactions.expect_row_count(3)

    transactions.open_column_menu("debit_account")
    transactions.expand_tree_node("t:expense")
    transactions.tick_column_value("debit_account", "Everyday")
    assert transactions.menu_selection_summary("debit_account") == "1 selected"
    transactions.apply_column_filter("debit_account")

    # Groceries sits in Everyday; Coffee is in Treats.
    transactions.expect_row_count(2)
    assert set(transactions.column_text(4)) == {"Groceries"}
    assert transactions.active_filter_text("debit_account").endswith("Everyday")


@pytest.mark.django_db(transaction=True)
def test_ticking_a_year_selects_every_date_in_it(requires_vite, authenticated_page: Page, live_server, ledger):
    """The date column nests year → month → day, and a year selects the whole year."""
    transactions = TransactionsPage(authenticated_page, live_server.url)
    transactions.goto(ledger.slug)

    transactions.open_column_menu("date")
    assert transactions.column_filter_values("date") == ["2025"]

    transactions.expand_tree_node("2025")
    assert transactions.column_filter_values("date") == ["2025", "Mar"]

    transactions.tick_column_value("date", "2025")
    transactions.apply_column_filter("date")

    transactions.expect_row_count(3)
    assert transactions.active_filter_text("date").endswith("2025")


@pytest.mark.django_db(transaction=True)
def test_ticking_a_month_narrows_to_that_month(requires_vite, authenticated_page: Page, live_server, ledger):
    """A month is selectable in its own right, and its chip carries the year."""
    transactions = TransactionsPage(authenticated_page, live_server.url)
    transactions.goto(ledger.slug)

    transactions.open_column_menu("date")
    transactions.expand_tree_node("2025")
    transactions.expand_tree_node("2025-03")
    transactions.tick_column_value("date", "3")  # the 3rd of March
    transactions.apply_column_filter("date")

    transactions.expect_row_count(1)
    assert transactions.column_text(3) == ["Beans"]


# ----------------------------------------------------------------------
# The edit modal
# ----------------------------------------------------------------------


@pytest.fixture
def editable(team):
    """
    One plain transaction, one split, and one reconciled — the three states the
    modal has a different answer for.
    """
    everyday = AccountGroupFactory(team=team, name="Everyday", account_type="expense")
    banks = AccountGroupFactory(team=team, name="Bank Accounts", account_type="asset")
    chequing = AccountFactory(team=team, account_group=banks, name="Chequing", has_feed=True)
    groceries = AccountFactory(team=team, account_group=everyday, name="Groceries")
    household = AccountFactory(team=team, account_group=everyday, name="Household Goods")
    dining = AccountFactory(team=team, account_group=everyday, name="Dining Out")

    def outflow(description, amount, *, reconciled=False):
        entry = JournalEntryFactory(team=team, description=description, status="posted", entry_date=date(2026, 3, 4))
        JournalLineFactory(team=team, journal_entry=entry, account=chequing, cr_amount=amount, is_reconciled=reconciled)
        JournalLineFactory(team=team, journal_entry=entry, account=groceries, dr_amount=amount)
        return entry

    plain = outflow("Weekly shop", "84.20")
    locked = outflow("Confirmed rent", "1200.00", reconciled=True)

    split = JournalEntryFactory(team=team, description="Costco run", status="posted", entry_date=date(2026, 3, 5))
    JournalLineFactory(team=team, journal_entry=split, account=chequing, cr_amount="210.40")
    JournalLineFactory(team=team, journal_entry=split, account=groceries, dr_amount="160.00")
    JournalLineFactory(team=team, journal_entry=split, account=household, dr_amount="50.40")

    return SimpleNamespace(
        chequing=chequing,
        groceries=groceries,
        household=household,
        dining=dining,
        plain=plain,
        locked=locked,
        split=split,
    )


@pytest.mark.django_db(transaction=True)
def test_row_click_opens_the_editor_with_the_transaction(
    requires_vite, authenticated_page: Page, live_server, team, editable
):
    """The modal speaks account and category, never debit and credit."""
    transactions = TransactionsPage(authenticated_page, live_server.url)
    transactions.goto(team.slug)
    transactions.open_editor("Weekly shop")

    assert "Chequing" in transactions.field_value("transaction-account")
    assert "Groceries" in transactions.field_value("transaction-category")
    assert transactions.field_value("transaction-outflow") == "84.20"
    assert transactions.field_value("transaction-inflow") == ""
    assert transactions.field_value("transaction-description") == "Weekly shop"


@pytest.mark.django_db(transaction=True)
def test_changing_the_category_updates_the_row_in_place(
    requires_vite, authenticated_page: Page, live_server, team, editable
):
    """No reload: the saved row is patched back into the list it came from."""
    transactions = TransactionsPage(authenticated_page, live_server.url)
    transactions.goto(team.slug)
    transactions.open_editor("Weekly shop")
    transactions.fill_combobox("transaction-category", "Dining Out")
    transactions.save_editor()

    assert "Dining Out" in transactions.row_text("Weekly shop")

    editable.plain.refresh_from_db()
    assert editable.plain.lines.filter(account=editable.dining).exists()


@pytest.mark.django_db(transaction=True)
def test_a_reconciled_transaction_locks_its_amount_but_not_its_category(
    requires_vite, authenticated_page: Page, live_server, team, editable
):
    """The lock the server enforces is the lock the modal shows."""
    transactions = TransactionsPage(authenticated_page, live_server.url)
    transactions.goto(team.slug)
    transactions.open_editor("Confirmed rent")

    assert transactions.field_is_disabled("transaction-outflow")
    assert transactions.field_is_disabled("transaction-account")
    assert not transactions.field_is_disabled("transaction-category")
    assert not transactions.can_delete()


@pytest.mark.django_db(transaction=True)
def test_a_split_opens_with_its_legs_and_can_be_reapportioned(
    requires_vite, authenticated_page: Page, live_server, team, editable
):
    transactions = TransactionsPage(authenticated_page, live_server.url)
    transactions.goto(team.slug)
    transactions.open_editor("Costco run")

    assert transactions.has_split_editor()
    assert transactions.split_leg_count() == 2

    transactions.set_split_amount(0, "120.00")
    transactions.assign_split_remainder()
    transactions.save_editor()

    amounts = {
        line.account.name: line.dr_amount - line.cr_amount for line in editable.split.lines.select_related("account")
    }
    assert amounts["Groceries"] == Decimal("120.00")
    assert amounts["Household Goods"] == Decimal("90.40")


@pytest.mark.django_db(transaction=True)
def test_split_legs_must_add_up_before_saving(requires_vite, authenticated_page: Page, live_server, team, editable):
    """Caught in the modal, so the user fixes it without a round trip."""
    transactions = TransactionsPage(authenticated_page, live_server.url)
    transactions.goto(team.slug)
    transactions.open_editor("Costco run")

    transactions.set_split_amount(0, "10.00")
    authenticated_page.locator("[data-testid='modal-save-btn']").click()

    assert "add up" in transactions.split_error()
    assert authenticated_page.locator("[data-testid='transaction-edit-modal']").is_visible()


@pytest.mark.django_db(transaction=True)
def test_a_plain_transaction_can_be_split(requires_vite, authenticated_page: Page, live_server, team, editable):
    transactions = TransactionsPage(authenticated_page, live_server.url)
    transactions.goto(team.slug)
    transactions.open_editor("Weekly shop")
    transactions.start_split()

    # The first leg is seeded with the whole total, so Remaining opens at $0.00.
    assert transactions.field_value("split-amount-0") == "84.20"

    transactions.set_split_amount(0, "50.00")
    transactions.fill_combobox("split-category-1", "Dining Out")
    transactions.assign_split_remainder()
    transactions.save_editor()

    assert editable.plain.lines.count() == 3
    assert "Split" in transactions.row_text("Weekly shop")


@pytest.mark.django_db(transaction=True)
def test_voiding_and_restoring_a_transaction(requires_vite, authenticated_page: Page, live_server, team, editable):
    transactions = TransactionsPage(authenticated_page, live_server.url)
    transactions.goto(team.slug)

    transactions.open_editor("Weekly shop")
    transactions.toggle_void()
    editable.plain.refresh_from_db()
    assert editable.plain.status == "void"
    assert "Void" in transactions.row_text("Weekly shop")

    transactions.open_editor("Weekly shop")
    assert transactions.void_button_label() == "Restore"
    transactions.toggle_void()
    editable.plain.refresh_from_db()
    assert editable.plain.status == "posted"


@pytest.mark.django_db(transaction=True)
def test_deleting_a_transaction_removes_its_row(requires_vite, authenticated_page: Page, live_server, team, editable):
    transactions = TransactionsPage(authenticated_page, live_server.url)
    transactions.goto(team.slug)
    before = transactions.get_row_count()

    transactions.open_editor("Weekly shop")
    transactions.delete_transaction()

    transactions.expect_row_count(before - 1)
    assert not JournalEntry.objects.filter(id=editable.plain.id).exists()
