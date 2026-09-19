"""
E2E tests for the YNAB import.

The whole feature is one React app talking to one set of endpoints, so these walk
it the way a migrating user does: drop both exports, look at what we made of them,
change one thing, and land on a dashboard that shows their own money.

The sample export in `docs/reference/` is the fixture -- 7,572 rows of a real
budget. It is slow enough that most tests here use the small synthetic export from
the unit fixtures instead, and only the two that are *about* the real thing pay for
it.

Every test needs Vite (`requires_vite`) and the un-onboarded team fixture: the
import refuses a team that already has transactions, and the shared `team` fixture
is marked past the walkthrough but is otherwise empty, which is exactly the state a
migrating user is in.
"""

import pytest
from playwright.sync_api import Page

from apps.accounts.models import Account
from apps.budget.models import Budget, Goal
from apps.journal.models import JournalEntry
from apps.ynab_import.tests.fixtures import TINY_PLAN, TINY_REGISTER
from e2e.pages.ynab_import import YnabImportPage, sample_export_paths


@pytest.fixture
def tiny_export(tmp_path):
    """The small hand-written export, as two files on disk."""
    register = tmp_path / "My Budget - Register.csv"
    plan = tmp_path / "My Budget - Plan.csv"
    register.write_text(TINY_REGISTER)
    plan.write_text(TINY_PLAN)
    return [str(register), str(plan)]


@pytest.fixture
def import_page(authenticated_page: Page, live_server, team) -> YnabImportPage:
    page = YnabImportPage(authenticated_page, live_server.url)
    page.goto_import(team.slug)
    return page


@pytest.mark.django_db
def test_wizard_walks_from_files_to_imported_books(import_page, tiny_export, team, requires_vite):
    import_page.upload(tiny_export)
    assert import_page.account_rows() == 3

    import_page.continue_to_preview()
    assert "Net worth" in import_page.preview_text()

    import_page.apply()
    assert import_page.succeeded(), import_page.page.content()[:2000]

    # The books, not the screen: what the user leaves with is a ledger.
    assert JournalEntry.objects.filter(team=team).count() == 7  # 5 transactions + 2 opening balances
    assert Account.objects.filter(team=team, name="Chequing").exists()
    assert Budget.objects.filter(team=team).exists()
    assert Goal.objects.filter(team=team, name="House").exists()


@pytest.mark.django_db
def test_the_inferred_account_types_are_shown_and_can_be_changed(import_page, tiny_export, team, requires_vite):
    import_page.upload(tiny_export)

    # Inferred: a card with a negative starting balance is money owed.
    assert import_page.account_type("Visa") == "liability"
    assert import_page.account_type("Chequing") == "asset"

    import_page.set_account_type("Savings", "liability")
    import_page.continue_to_preview()
    import_page.apply()

    account = Account.objects.get(team=team, name="Savings")
    assert account.account_group.account_type == "liability"


@pytest.mark.django_db
def test_an_account_can_be_left_behind(import_page, tiny_export, team, requires_vite):
    import_page.upload(tiny_export)
    import_page.drop_account("Savings")
    import_page.continue_to_preview()
    import_page.apply()

    assert not Account.objects.filter(team=team, name="Savings").exists()
    # The transfer to it still balances -- it posts against the equity offset.
    assert all(entry.is_balanced for entry in JournalEntry.objects.filter(team=team))


@pytest.mark.django_db
def test_income_payees_become_income_accounts(import_page, tiny_export, team, requires_vite):
    import_page.upload(tiny_export)
    import_page.click_next()
    import_page.page.wait_for_selector("[data-testid='ynab-income-table']")

    assert import_page.income_rows() >= 1
    import_page.set_income_account("Employer", "Day job")

    import_page.continue_to_preview()
    import_page.apply()

    assert Account.objects.filter(team=team, name="Day job", account_group__account_type="income").exists()


@pytest.mark.django_db
def test_a_savings_category_can_be_imported_as_a_spending_category(import_page, tiny_export, team, requires_vite):
    import_page.upload(tiny_export)
    import_page.click_next()
    import_page.page.wait_for_selector("[data-testid='ynab-income-table']")
    import_page.click_next()
    import_page.page.wait_for_selector("[data-testid='ynab-goals-grid']")

    assert import_page.goal_cards() >= 1
    import_page.set_goal_kind("House", "expense")

    import_page.continue_to_preview()
    import_page.apply()

    assert not Goal.objects.filter(team=team, name="House").exists()
    assert Account.objects.filter(team=team, name="House", account_group__account_type="expense").exists()


@pytest.mark.django_db
def test_one_file_is_not_enough(import_page, tiny_export, requires_vite):
    # An import needs both halves of the export, so one file leaves the button
    # disabled rather than posting half of one.
    import_page.choose_files(tiny_export[:1])
    assert not import_page.can_upload()

    import_page.choose_files(tiny_export)
    assert import_page.can_upload()


@pytest.mark.django_db
def test_a_team_that_already_has_books_is_told_why_not(import_page, tiny_export, team, requires_vite):
    import_page.upload(tiny_export)
    import_page.continue_to_preview()
    import_page.apply()

    import_page.goto_import(team.slug)
    assert import_page.is_blocked()
    assert "empty team" in import_page.page.locator("[data-testid='ynab-blocked']").inner_text()


@pytest.mark.django_db
def test_the_reconciliation_is_shown_before_anything_is_written(import_page, tiny_export, team, requires_vite):
    import_page.upload(tiny_export)
    import_page.continue_to_preview()

    text = import_page.preview_text()
    assert "Every transaction reached the right category" in text
    assert "Every account ends on the balance YNAB shows" in text
    # Nothing is written until the last screen.
    assert not JournalEntry.objects.filter(team=team).exists()


@pytest.mark.slow
@pytest.mark.django_db
def test_a_real_five_year_export_imports_and_reconciles(import_page, team, requires_vite):
    """
    The sample export: 36 accounts, 58 months, 7,572 rows.

    This is the test the whole feature exists to pass -- everything else is a
    detail of one screen.
    """
    paths = sample_export_paths()
    if len(paths) < 2:
        pytest.skip("The sample YNAB export is not available")

    import_page.upload(paths, timeout=120_000)
    assert import_page.account_rows() == 36

    import_page.continue_to_preview(timeout=120_000)
    preview = import_page.preview_text()
    assert "6,623" in preview  # transactions, plus the opening balances
    assert "$292,472.98" in preview  # the net worth they will land on

    import_page.apply()
    assert import_page.succeeded()

    result = import_page.result_text()
    assert "Your budget is in" in result
    assert "$292,472.98" in result

    assert JournalEntry.objects.filter(team=team).count() == 6636
    assert Budget.objects.filter(team=team).count() == 1872
    assert Goal.objects.filter(team=team).count() == 3

    import_page.go_to_dashboard()
    import_page.page.wait_for_url(f"**/a/{team.slug}/", timeout=30_000, wait_until="domcontentloaded")
    assert "$292,472.98" in import_page.page.locator("body").inner_text()
