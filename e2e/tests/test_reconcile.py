"""
E2E tests for statement reconciliation (docs/statement-reconciliation-plan.md §11).

NOTE: needs the Vite dev server (or built assets), like the other React pages.
"""

import calendar
from datetime import date, timedelta
from decimal import Decimal

import pytest
from playwright.sync_api import Page, expect

from apps.bank_feed.models import BankTransaction
from apps.journal.models import JournalEntry, JournalLine
from apps.reconciliation.models import Reconciliation
from e2e.factories import AccountFactory, AccountGroupFactory, AssetAccountFactory
from e2e.pages.bank_feed import BankFeedPage
from e2e.pages.reconcile import ReconcileHubPage, ReconcilePage


def _statement_date() -> date:
    """The page's default: the end of last month."""
    return date.today().replace(day=1) - timedelta(days=1)


def _in_period(day: int) -> date:
    end = _statement_date()
    return end.replace(day=min(day, calendar.monthrange(end.year, end.month)[1]))


def entry(team, account, category, amount, *, on, description, feed=True, reconciled=False):
    """A posted two-line entry; `amount` is the effect on `account` in ledger sign (dr - cr)."""
    amount = Decimal(amount)
    je = JournalEntry.objects.create(team=team, entry_date=on, description=description, status="posted")
    line = JournalLine.objects.create(
        team=team,
        journal_entry=je,
        account=account,
        dr_amount=max(amount, 0),
        cr_amount=max(-amount, 0),
        is_reconciled=reconciled,
    )
    JournalLine.objects.create(
        team=team, journal_entry=je, account=category, dr_amount=max(-amount, 0), cr_amount=max(amount, 0)
    )
    tx = None
    if feed:
        tx = BankTransaction.objects.create(
            team=team,
            account=account,
            amount=-amount,
            posted_date=on,
            description=description,
            merchant_name=description,
            source="csv",
            journal_entry=je,
        )
    return line, tx


@pytest.fixture
def chequing(team):
    group = AccountGroupFactory(team=team, account_type="asset", name="Zed Banks")
    account = AssetAccountFactory(team=team, account_group=group, has_feed=True, name="Zed Chequing")
    spend = AccountGroupFactory(team=team, account_type="expense", name="Zed Spending")
    income = AccountGroupFactory(team=team, account_type="income", name="Zed Income")
    return {
        "team": team,
        "account": account,
        "groceries": AccountFactory(team=team, account_group=spend, name="Zed Groceries"),
        "coffee": AccountFactory(team=team, account_group=spend, name="Zed Coffee"),
        "salary": AccountFactory(team=team, account_group=income, name="Zed Salary"),
    }


@pytest.mark.django_db(transaction=True)
def test_statement_that_balances_finishes_and_shows_intact(
    requires_vite, authenticated_page: Page, live_server, chequing
):
    team, account = chequing["team"], chequing["account"]
    pay, _ = entry(team, account, chequing["salary"], "2450.00", on=_in_period(1), description="Paycheque")
    rent, _ = entry(team, account, chequing["groceries"], "-1800.00", on=_in_period(2), description="Rent")

    page = ReconcilePage(authenticated_page, live_server.url)
    page.goto(team.slug, account.id)
    page.start("650.00")
    expect(page.difference()).to_have_text("$650.00")
    page.tick(pay.id)
    page.tick(rent.id)
    expect(page.difference()).to_have_text("$0.00")
    page.wait_saved()
    page.finish()
    expect(page.done()).to_contain_text("You’re clear")

    expect(page.history_statuses()).to_have_text(["Intact"])
    pay.refresh_from_db()
    assert pay.is_reconciled

    hub = ReconcileHubPage(authenticated_page, live_server.url)
    hub.goto(team.slug)
    assert "Intact" in hub.status_for(account.id)


@pytest.mark.django_db(transaction=True)
def test_duplicate_is_named_by_a_hint_and_fixed_in_one_click(
    requires_vite, authenticated_page: Page, live_server, chequing
):
    team, account = chequing["team"], chequing["account"]
    entry(team, account, chequing["coffee"], "-12.75", on=_in_period(20), description="Coffee")
    entry(team, account, chequing["coffee"], "-12.75", on=_in_period(20), description="Coffee")

    page = ReconcilePage(authenticated_page, live_server.url)
    page.goto(team.slug, account.id)
    page.start("-12.75")
    page.tick_all_through()
    expect(page.difference()).to_have_text("$12.75")
    expect(page.hint("duplicate")).to_be_visible()
    page.hint("duplicate").locator("[data-testid='hint-action']").click()
    expect(page.difference()).to_have_text("$0.00")
    page.wait_saved()
    page.finish()
    expect(page.done()).to_be_visible()


@pytest.mark.django_db(transaction=True)
def test_credit_card_balance_owed_is_typed_as_printed(requires_vite, authenticated_page: Page, live_server, chequing):
    team = chequing["team"]
    cards = AccountGroupFactory(team=team, account_type="liability", name="Zed Cards")
    card = AccountFactory(team=team, account_group=cards, name="Zed Visa", has_feed=True)
    charge, _ = entry(team, card, chequing["groceries"], "-284.56", on=_in_period(5), description="Groceries")

    page = ReconcilePage(authenticated_page, live_server.url)
    page.goto(team.slug, card.id)
    expect(page.page.get_by_text("Balance owed")).to_be_visible()
    page.start("284.56")
    page.tick(charge.id)
    expect(page.difference()).to_have_text("$0.00")


@pytest.mark.django_db(transaction=True)
def test_finish_with_adjustment_posts_a_reconciled_feed_row(
    requires_vite, authenticated_page: Page, live_server, chequing
):
    team, account = chequing["team"], chequing["account"]
    line, _ = entry(team, account, chequing["groceries"], "-40.00", on=_in_period(3), description="Store")

    page = ReconcilePage(authenticated_page, live_server.url)
    page.goto(team.slug, account.id)
    page.start("-42.50")
    page.tick(line.id)
    expect(page.difference()).to_have_text("-$2.50")
    page.wait_saved()
    page.finish_with_adjustment()
    expect(page.done()).to_contain_text("adjustment")

    adjustment = BankTransaction.objects.get(account=account, source="system")
    assert adjustment.amount == Decimal("2.50")
    assert adjustment.journal_entry.lines.get(account=account).is_reconciled


@pytest.mark.django_db(transaction=True)
def test_draft_resumes_after_reload(requires_vite, authenticated_page: Page, live_server, chequing):
    team, account = chequing["team"], chequing["account"]
    line, _ = entry(team, account, chequing["groceries"], "-40.00", on=_in_period(3), description="Store")

    page = ReconcilePage(authenticated_page, live_server.url)
    page.goto(team.slug, account.id)
    page.start("-40.00")
    page.tick(line.id)
    page.wait_saved()

    page.goto(team.slug, account.id)
    expect(page.row(line.id)).to_have_attribute("data-ticked", "true")
    expect(page.difference()).to_have_text("$0.00")


@pytest.mark.django_db(transaction=True)
def test_feed_selection_arrives_ticked(requires_vite, authenticated_page: Page, live_server, chequing):
    team, account = chequing["team"], chequing["account"]
    line, tx = entry(team, account, chequing["groceries"], "-40.00", on=_in_period(3), description="Store")
    other, _ = entry(team, account, chequing["groceries"], "-5.00", on=_in_period(4), description="Other")

    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(team.slug)
    feed.click_account_card(account.id)
    feed.wait_for_table()
    feed.select_row(tx.id)
    feed.batch_button("Reconcile").click()

    page = ReconcilePage(authenticated_page, live_server.url)
    authenticated_page.wait_for_selector("[data-testid='reconcile-start-form']", timeout=15_000)
    page.start("-40.00")
    expect(page.row(line.id)).to_have_attribute("data-ticked", "true")
    expect(page.row(other.id)).to_have_attribute("data-ticked", "false")
    expect(page.difference()).to_have_text("$0.00")


@pytest.mark.django_db(transaction=True)
def test_unreconciling_in_the_feed_marks_the_statement_changed(
    requires_vite, authenticated_page: Page, live_server, chequing
):
    team, account = chequing["team"], chequing["account"]
    line, tx = entry(team, account, chequing["groceries"], "-40.00", on=_in_period(3), description="Store")
    rec = Reconciliation.objects.create(
        team=team,
        account=account,
        statement_date=_statement_date(),
        statement_balance=Decimal("-40.00"),
        status="completed",
        cleared_total=Decimal("-40.00"),
        opening_balance=Decimal("0"),
    )
    line.is_reconciled = True
    line.reconciliation = rec
    line.save()

    feed = BankFeedPage(authenticated_page, live_server.url)
    feed.goto(team.slug)
    feed.click_account_card(account.id)
    feed.wait_for_table()
    expect(authenticated_page.locator("[data-testid='reconciled-through']")).to_contain_text("Intact")
    feed.select_row(tx.id)
    feed.batch_button("Unreconcile").click()
    expect(authenticated_page.locator("[data-testid='unreconcile-statement-warning']")).to_be_visible()
    authenticated_page.locator("[data-testid='unreconcile-dialog']").get_by_role("button", name="Unreconcile").click()
    expect(authenticated_page.locator("[data-testid='reconciled-through']")).to_contain_text("Changed")

    hub = ReconcileHubPage(authenticated_page, live_server.url)
    hub.goto(team.slug)
    assert "Changed" in hub.status_for(account.id)

    # The next statement (the default date follows the last one) names the line
    # that moved and offers it again.
    page = ReconcilePage(authenticated_page, live_server.url)
    page.goto(team.slug, account.id)
    expect(page.history_statuses()).to_have_text(["Changed"])
    page.start("-40.00")
    expect(authenticated_page.locator("[data-testid='drift-banner']")).to_contain_text("Store")
    expect(page.row(line.id)).to_be_visible()
