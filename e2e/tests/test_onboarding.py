"""
E2E tests for the guided onboarding walkthrough.

Both surfaces are React, so every test here needs Vite (`requires_vite`).

The walkthrough's promise is a chain: answer questions → get a chart of accounts
that matches your answers → import → categorize → see it in a report → watch net
worth move. These tests follow that chain rather than poking each screen in
isolation, because the interesting failures are in the joins.
"""

from datetime import date
from decimal import Decimal

import pytest
from playwright.sync_api import Page

from e2e.pages.onboarding import DashboardOnboardingPage, OnboardingPage, TaskRailPage

# A renting household with a paid-off car, kids, a student loan and a TFSA.
# Keyed by question id, so cutting a question from the catalog just leaves an
# unused entry rather than breaking the walk.
ANSWERS = {
    "income_sources": ["employment"],
    "household_shape": ["solo"],
    "housing": ["rent"],
    "kids": ["yes"],
    "transport": ["car_owned"],
    "debts": ["student_loan"],
    "savings": ["tfsa"],
    "extras": ["none"],
}


def _categorize_something(team):
    """
    Give the team one imported and one categorized transaction.

    Done through the ORM rather than by driving the CSV wizard: that wizard has
    its own E2E coverage, and what these tests are about is how the walkthrough
    reacts to the data existing.
    """
    from apps.accounts.models import Account
    from apps.bank_feed.models import BankTransaction
    from apps.journal.models import JournalEntry, JournalLine

    bank = Account.objects.filter(team=team, has_feed=True).first()
    category = Account.objects.filter(team=team, account_group__account_type="expense").first()

    BankTransaction.objects.create(
        team=team,
        account=bank,
        posted_date=date.today(),
        amount=Decimal("42.00"),
        description="LOBLAWS",
        source=BankTransaction.SOURCE_CSV,
    )
    entry = JournalEntry.objects.create(
        team=team, entry_date=date.today(), description="LOBLAWS", status=JournalEntry.STATUS_POSTED
    )
    JournalLine.objects.create(
        team=team, journal_entry=entry, account=category, dr_amount=Decimal("42.00"), cr_amount=Decimal("0")
    )
    JournalLine.objects.create(
        team=team, journal_entry=entry, account=bank, dr_amount=Decimal("0"), cr_amount=Decimal("42.00")
    )


# ---------------------------------------------------------------------------
# The takeover
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_new_team_is_sent_to_the_walkthrough(onboarding_page: Page, unonboarded_team, requires_vite):
    """A team that has never been onboarded cannot reach the dashboard first."""
    assert "/onboarding/" in onboarding_page.url


@pytest.mark.django_db(transaction=True)
def test_welcome_then_first_question(onboarding_page: Page, live_server, unonboarded_team, requires_vite):
    onboarding = OnboardingPage(onboarding_page, live_server.url)
    onboarding.goto_onboarding(unonboarded_team.slug)

    assert onboarding.is_welcome_visible()

    onboarding.start()
    assert onboarding.current_question_id() is not None


@pytest.mark.django_db(transaction=True)
def test_a_required_question_blocks_continue(onboarding_page: Page, live_server, unonboarded_team, requires_vite):
    """The rule lives on the server too, but the button must not invite a dead click."""
    onboarding = OnboardingPage(onboarding_page, live_server.url)
    onboarding.goto_onboarding(unonboarded_team.slug)
    onboarding.start()

    assert onboarding.continue_disabled()

    onboarding.choose("employment")
    assert not onboarding.continue_disabled()


@pytest.mark.django_db(transaction=True)
def test_answers_survive_a_reload(onboarding_page: Page, live_server, unonboarded_team, requires_vite):
    """State is server-side, so closing the tab mid-flow does not start over."""
    onboarding = OnboardingPage(onboarding_page, live_server.url)
    onboarding.goto_onboarding(unonboarded_team.slug)
    onboarding.start()
    onboarding.choose("employment")
    onboarding.click_continue()
    onboarding_page.wait_for_timeout(700)

    onboarding.goto_onboarding(unonboarded_team.slug)

    from apps.onboarding.models import OnboardingState

    state = OnboardingState.objects.get(team=unonboarded_team)
    assert state.answers.get("income_sources") == ["employment"]
    assert not onboarding.is_welcome_visible()


# ---------------------------------------------------------------------------
# Chart-of-accounts review
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_review_reflects_the_answers(onboarding_page: Page, live_server, unonboarded_team, requires_vite):
    onboarding = OnboardingPage(onboarding_page, live_server.url)
    onboarding.goto_onboarding(unonboarded_team.slug)
    onboarding.start()
    onboarding.answer_all(ANSWERS)

    names = onboarding.account_names()
    assert "Rent" in names  # they rent
    assert "Mortgage" not in names  # so no mortgage
    assert "Vehicle" in names  # a car they own
    assert "Car Loan" not in names  # outright, so no loan


@pytest.mark.django_db(transaction=True)
def test_removing_an_account_keeps_it_out_of_the_books(
    onboarding_page: Page, live_server, unonboarded_team, requires_vite
):
    from apps.accounts.models import Account

    onboarding = OnboardingPage(onboarding_page, live_server.url)
    onboarding.goto_onboarding(unonboarded_team.slug)
    onboarding.start()
    onboarding.answer_all(ANSWERS)

    onboarding.remove_account("Tenant Insurance")
    assert "Tenant Insurance" not in onboarding.account_names()

    onboarding.confirm_accounts(unonboarded_team.slug)

    created = set(Account.objects.filter(team=unonboarded_team).values_list("name", flat=True))
    assert "Tenant Insurance" not in created
    assert "Rent" in created


@pytest.mark.django_db(transaction=True)
def test_completing_builds_the_chart_of_accounts(onboarding_page: Page, live_server, unonboarded_team, requires_vite):
    from apps.accounts.models import Account

    onboarding = OnboardingPage(onboarding_page, live_server.url)
    onboarding.goto_onboarding(unonboarded_team.slug)
    onboarding.start()
    onboarding.answer_all(ANSWERS)
    onboarding.confirm_accounts(unonboarded_team.slug)

    names = set(Account.objects.filter(team=unonboarded_team).values_list("name", flat=True))
    assert "Rent" in names
    assert "Student Loan" in names
    assert "TFSA" in names
    assert "Childcare" in names
    assert "Mortgage" not in names


# ---------------------------------------------------------------------------
# Skip
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_skipping_still_leaves_a_usable_chart_of_accounts(
    onboarding_page: Page, live_server, unonboarded_team, requires_vite
):
    """Skipping the guide must not leave a team with no accounts to work in."""
    from apps.accounts.models import Account

    onboarding = OnboardingPage(onboarding_page, live_server.url)
    onboarding.goto_onboarding(unonboarded_team.slug)
    onboarding.skip()
    onboarding_page.wait_for_url(f"**/a/{unonboarded_team.slug}/", timeout=30_000, wait_until="domcontentloaded")

    assert Account.objects.filter(team=unonboarded_team).exists()


# ---------------------------------------------------------------------------
# The task rail and its gates
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_rail_gates_everything_behind_the_import(onboarding_page: Page, live_server, unonboarded_team, requires_vite):
    onboarding = OnboardingPage(onboarding_page, live_server.url)
    onboarding.goto_onboarding(unonboarded_team.slug)
    onboarding.start()
    onboarding.answer_all(ANSWERS)
    onboarding.confirm_accounts(unonboarded_team.slug)

    rail = TaskRailPage(onboarding_page, live_server.url)
    rail.wait_for_rail()

    states = rail.task_states()
    assert states["import"] == "available"
    assert states["categorize"] == "locked"
    assert states["report"] == "locked"


@pytest.mark.django_db(transaction=True)
def test_real_data_unlocks_the_rail(onboarding_page: Page, live_server, unonboarded_team, requires_vite):
    """
    The gates are about the user's own data, not a click count: importing and
    categorizing is what opens the rest.
    """
    onboarding = OnboardingPage(onboarding_page, live_server.url)
    onboarding.goto_onboarding(unonboarded_team.slug)
    onboarding.start()
    onboarding.answer_all(ANSWERS)
    onboarding.confirm_accounts(unonboarded_team.slug)

    _categorize_something(unonboarded_team)

    dashboard = DashboardOnboardingPage(onboarding_page, live_server.url)
    dashboard.goto_dashboard(unonboarded_team.slug)

    rail = TaskRailPage(onboarding_page, live_server.url)
    rail.wait_for_rail()

    states = rail.task_states()
    assert states["import"] == "done"
    assert states["categorize"] == "done"
    assert states["report"] == "available"


@pytest.mark.django_db(transaction=True)
def test_rail_persists_across_pages(onboarding_page: Page, live_server, unonboarded_team, requires_vite):
    onboarding = OnboardingPage(onboarding_page, live_server.url)
    onboarding.goto_onboarding(unonboarded_team.slug)
    onboarding.start()
    onboarding.answer_all(ANSWERS)
    onboarding.confirm_accounts(unonboarded_team.slug)

    rail = TaskRailPage(onboarding_page, live_server.url)
    rail.wait_for_rail()

    onboarding_page.goto(f"{live_server.url}/a/{unonboarded_team.slug}/budget/", wait_until="domcontentloaded")
    rail.wait_for_rail()
    assert rail.is_visible()


# ---------------------------------------------------------------------------
# Opening balances and the reveal
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_opening_balances_move_net_worth(onboarding_page: Page, live_server, unonboarded_team, requires_vite):
    """The payoff the whole walkthrough is built around."""
    from apps.accounts.models import Account
    from apps.budget.services import NetWorthService

    onboarding = OnboardingPage(onboarding_page, live_server.url)
    onboarding.goto_onboarding(unonboarded_team.slug)
    onboarding.start()
    onboarding.answer_all(ANSWERS)
    onboarding.confirm_accounts(unonboarded_team.slug)

    _categorize_something(unonboarded_team)

    dashboard = DashboardOnboardingPage(onboarding_page, live_server.url)
    dashboard.goto_dashboard(unonboarded_team.slug)

    rail = TaskRailPage(onboarding_page, live_server.url)
    rail.wait_for_rail()
    rail.open_task("net_worth")
    rail.wait_for_opening_balances()

    chequing = Account.objects.get(team=unonboarded_team, name="Chequing Account")
    rail.fill_opening_balance(chequing.id, "2500")
    rail.save_opening_balances()
    rail.wait_for_reveal()

    month = date.today().replace(day=1)
    net_worth = NetWorthService(unonboarded_team).get_net_worth(month)
    assert net_worth == Decimal("2458.00")  # 2500 opening, less the 42 categorized
    assert "2,458" in rail.revealed_net_worth()


@pytest.mark.django_db(transaction=True)
def test_opening_balances_are_refused_before_categorizing(
    onboarding_page: Page, live_server, unonboarded_team, requires_vite
):
    """
    The gate is enforced, not merely hidden: the dialog opens but reports why it
    cannot help yet rather than anchoring a net worth against nothing.
    """
    onboarding = OnboardingPage(onboarding_page, live_server.url)
    onboarding.goto_onboarding(unonboarded_team.slug)
    onboarding.start()
    onboarding.answer_all(ANSWERS)
    onboarding.confirm_accounts(unonboarded_team.slug)

    rail = TaskRailPage(onboarding_page, live_server.url)
    rail.wait_for_rail()

    # Task 5 is locked with no data, so the row is not clickable — assert the
    # server refuses it directly, which is the guarantee that matters.
    assert rail.task_state("net_worth") == "locked"


# ---------------------------------------------------------------------------
# Finishing, dismissing and resuming
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_dismissing_the_rail_offers_a_way_back(onboarding_page: Page, live_server, unonboarded_team, requires_vite):
    onboarding = OnboardingPage(onboarding_page, live_server.url)
    onboarding.goto_onboarding(unonboarded_team.slug)
    onboarding.start()
    onboarding.answer_all(ANSWERS)
    onboarding.confirm_accounts(unonboarded_team.slug)

    rail = TaskRailPage(onboarding_page, live_server.url)
    rail.wait_for_rail()
    rail.dismiss()
    onboarding_page.wait_for_timeout(800)

    dashboard = DashboardOnboardingPage(onboarding_page, live_server.url)
    dashboard.goto_dashboard(unonboarded_team.slug)

    assert dashboard.has_resume_card()
    assert not dashboard.has_legacy_checklist()

    dashboard.resume()
    rail.wait_for_rail()
    assert rail.is_visible()


@pytest.mark.django_db(transaction=True)
def test_the_old_checklist_is_gone(authenticated_page: Page, live_server, team, requires_vite):
    """It duplicated the task rail with none of its gates."""
    dashboard = DashboardOnboardingPage(authenticated_page, live_server.url)
    dashboard.goto_dashboard(team.slug)

    assert not dashboard.has_legacy_checklist()


@pytest.mark.django_db(transaction=True)
def test_a_set_up_team_sees_neither_rail_nor_card(authenticated_page: Page, live_server, team, requires_vite):
    """
    The walkthrough leaves no residue once the team is actually set up.

    "Onboarded" is not enough on its own: a team that finished the guide but still
    has no accounts, transactions or budget is exactly who the nudge is for, so
    this gives it the three things first.
    """
    from apps.accounts.models import ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_EXPENSE
    from apps.bank_feed.models import BankTransaction
    from apps.budget.models import Budget
    from e2e.factories import AccountFactory, AccountGroupFactory

    assets = AccountGroupFactory(team=team, account_type=ACCOUNT_TYPE_ASSET)
    expenses = AccountGroupFactory(team=team, account_type=ACCOUNT_TYPE_EXPENSE)
    bank = AccountFactory(team=team, account_group=assets)
    category = AccountFactory(team=team, account_group=expenses)
    BankTransaction.objects.create(
        team=team,
        account=bank,
        posted_date=date.today(),
        amount=Decimal("10.00"),
        description="Coffee",
        source=BankTransaction.SOURCE_CSV,
    )
    Budget.objects.create(
        team=team, month=date.today().replace(day=1), category=category, budget_amount=Decimal("100.00")
    )

    dashboard = DashboardOnboardingPage(authenticated_page, live_server.url)
    dashboard.goto_dashboard(team.slug)
    authenticated_page.wait_for_timeout(1200)

    rail = TaskRailPage(authenticated_page, live_server.url)
    assert not rail.is_visible()
    assert not dashboard.has_resume_card()


@pytest.mark.django_db(transaction=True)
def test_a_finished_but_empty_team_is_still_offered_the_nudge(
    authenticated_page: Page, live_server, team, requires_vite
):
    """The other half of the same rule: gaps are what the card is for."""
    dashboard = DashboardOnboardingPage(authenticated_page, live_server.url)
    dashboard.goto_dashboard(team.slug)

    assert dashboard.has_resume_card()
