"""
E2E tests for the Transactions page (React SPA).

NOTE: These tests require the Vite dev server to be running alongside the
Django live server. Run `make start-bg` first (which starts the vite container),
then run `make test-e2e ARGS="e2e/tests/test_transactions.py"`.

Alternatively, build the frontend once with `make npm-build` and set
DJANGO_VITE_DEV_MODE=False in settings_e2e.py to use the built assets.

Covers: page load, empty state, search filter, row count with seeded data.
"""

import pytest
from playwright.sync_api import Page

from e2e.factories import (
    AccountFactory,
    AccountGroupFactory,
    JournalEntryFactory,
    JournalLineFactory,
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
    acct = AccountFactory(team=team, account_group=group)

    entry1 = JournalEntryFactory(team=team, description="Coffee Shop Purchase", status="posted")
    JournalLineFactory(team=team, journal_entry=entry1, account=acct, dr_amount="5.00")

    entry2 = JournalEntryFactory(team=team, description="Grocery Store", status="posted")
    JournalLineFactory(team=team, journal_entry=entry2, account=acct, dr_amount="120.00")

    transactions = TransactionsPage(authenticated_page, live_server.url)
    transactions.goto(team.slug)

    # Initially both rows visible
    assert transactions.get_row_count() >= 2

    # After search, only the matching row should remain
    transactions.search("Coffee")
    assert transactions.get_row_count() == 1
