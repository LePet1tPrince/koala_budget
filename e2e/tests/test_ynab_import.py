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

from apps.accounts.models import Account, AccountGroup
from apps.bank_feed.models import BankTransaction
from apps.budget.models import Budget, Goal
from apps.journal.models import JournalEntry
from apps.ynab_import.tests.fixtures import TINY_PLAN, TINY_REGISTER
from e2e.factories import JournalEntryFactory
from e2e.pages.bank_feed import BankFeedPage
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
    page.goto_import(team.default_book)
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
    assert JournalEntry.objects.filter(book=team.default_book).count() == 7  # 5 transactions + 2 opening balances
    assert Account.objects.filter(book=team.default_book, name="Chequing").exists()
    assert Budget.objects.filter(book=team.default_book).exists()
    assert Goal.objects.filter(book=team.default_book, name="House").exists()


@pytest.mark.django_db
def test_the_inferred_account_types_are_shown_and_can_be_changed(import_page, tiny_export, team, requires_vite):
    import_page.upload(tiny_export)

    # Inferred: a card with a negative starting balance is money owed.
    assert import_page.account_type("Visa") == "liability"
    assert import_page.account_type("Chequing") == "asset"

    import_page.set_account_type("Savings", "liability")
    import_page.continue_to_preview()
    import_page.apply()

    account = Account.objects.get(book=team.default_book, name="Savings")
    assert account.account_group.account_type == "liability"


@pytest.mark.django_db
def test_accounts_are_filed_into_groups_picked_from_one_list(import_page, tiny_export, team, requires_vite):
    import_page.upload(tiny_export)

    # The defaults are singular, and each type offers only its own groups.
    assert import_page.account_group("Chequing") == "Bank Account"
    assert import_page.account_group("Visa") == "Credit Card"
    assert "Credit Card" not in import_page.group_names("asset")

    # A group added at the top is offered on every row of its type...
    import_page.add_group("asset", "Everyday")
    assert "Everyday" in import_page.group_names("asset")
    import_page.set_account_group("Chequing", "Everyday")
    # ...and retyping the name in another casing picks the same group, not a new one.
    import_page.set_account_group("Savings", "everyday")
    assert import_page.account_group("Savings") == "Everyday"

    # Retyping an account moves it into a group of its new type.
    import_page.set_account_type("Chequing", "liability")
    assert import_page.account_group("Chequing") in import_page.group_names("liability")
    import_page.set_account_type("Chequing", "asset")
    import_page.set_account_group("Chequing", "Everyday")

    import_page.continue_to_preview()
    import_page.apply()

    group = AccountGroup.objects.get(book=team.default_book, name="Everyday")
    assert set(group.accounts.values_list("name", flat=True)) == {"Chequing", "Savings"}


@pytest.mark.django_db
def test_a_group_is_picked_by_filter_and_keyboard(import_page, tiny_export, team, requires_vite):
    import_page.upload(tiny_export)
    import_page.add_group("asset", "Everyday")
    import_page.add_group("asset", "Emergency")

    # The filter narrows the list; Enter takes the highlighted match.
    import_page.pick_group_by_keyboard("Chequing", "every", ["Enter"])
    assert import_page.account_group("Chequing") == "Everyday"

    # ↓ / Tab walk the list from the current choice and wrap past the "New group"
    # row at the end; Shift+Tab walks back.
    assert import_page.group_names("asset") == ["Bank Account", "Tracking Account", "Everyday", "Emergency"]
    import_page.pick_group_by_keyboard("Chequing", "", ["ArrowDown", "Enter"])
    assert import_page.account_group("Chequing") == "Emergency"
    import_page.pick_group_by_keyboard("Chequing", "", ["Tab", "Tab", "Tab", "Shift+Tab", "Enter"])
    assert import_page.account_group("Chequing") == "Bank Account"


@pytest.mark.django_db
def test_a_group_can_be_renamed_and_emptied_from_its_chip(import_page, tiny_export, team, requires_vite):
    import_page.upload(tiny_export)
    bank = "ynab-groups-asset"
    assert import_page.account_group("Chequing") == "Bank Account"

    # Renaming a chip renames it for every row using it, in place.
    import_page.rename_name(bank, "Bank Account", "Everyday Banking")
    assert "Bank Account" not in import_page.chip_names(bank)
    assert "Everyday Banking" in import_page.chip_names(bank)
    assert import_page.account_group("Chequing") == "Everyday Banking"

    # "Move all" sends every row in a group to another, leaving the chip unused.
    import_page.move_all(bank, "Everyday Banking", "Tracking Account")
    assert import_page.account_group("Chequing") == "Tracking Account"
    assert "Everyday Banking" in import_page.chip_names(bank)

    # Renaming onto an existing name combines the two.
    import_page.rename_name(bank, "Tracking Account", "everyday banking")
    assert "Tracking Account" not in import_page.chip_names(bank)
    assert import_page.account_group("Chequing") == "Everyday Banking"
    assert import_page.account_group("Savings") == "Everyday Banking"

    import_page.continue_to_preview()
    import_page.apply()
    group = AccountGroup.objects.get(book=team.default_book, name="Everyday Banking")
    assert set(group.accounts.values_list("name", flat=True)) == {"Chequing", "Savings"}


@pytest.mark.django_db
def test_an_income_account_can_be_renamed_from_its_chip(import_page, tiny_export, team, requires_vite):
    import_page.upload(tiny_export)
    import_page.click_next()
    import_page.page.wait_for_selector("[data-testid='ynab-income-table']")
    bank = "ynab-income-accounts"
    (original,) = [name for name in import_page.chip_names(bank) if name]

    import_page.rename_name(bank, original, "Salary")
    assert import_page.chip_names(bank) == ["Salary"]

    import_page.continue_to_preview()
    import_page.apply()
    assert Account.objects.filter(book=team.default_book, name="Salary", account_group__account_type="income").exists()
    assert not Account.objects.filter(book=team.default_book, name=original).exists()


@pytest.mark.django_db
def test_closing_mid_review_asks_in_a_dialog_not_a_browser_prompt(import_page, tiny_export, team, requires_vite):
    native_prompts = []
    import_page.page.on("dialog", lambda dialog: (native_prompts.append(dialog.type), dialog.dismiss()))
    import_page.upload(tiny_export)
    start_url = import_page.page.url

    import_page.click_close()
    assert import_page.leave_dialog_open()
    import_page.keep_going()
    assert not import_page.leave_dialog_open()
    assert import_page.page.url == start_url
    assert import_page.account_rows() >= 1

    import_page.click_close()
    import_page.leave_import()
    import_page.page.wait_for_url(lambda url: url != start_url, timeout=10_000)
    assert native_prompts == []


@pytest.mark.django_db
def test_an_account_can_be_left_behind(import_page, tiny_export, team, requires_vite):
    import_page.upload(tiny_export)
    import_page.drop_account("Savings")
    import_page.continue_to_preview()
    import_page.apply()

    assert not Account.objects.filter(book=team.default_book, name="Savings").exists()
    # The transfer to it still balances -- it posts against the equity offset.
    assert all(entry.is_balanced for entry in JournalEntry.objects.filter(book=team.default_book))


@pytest.mark.django_db
def test_imported_transactions_land_in_the_account_feeds(import_page, tiny_export, team, requires_vite):
    import_page.upload(tiny_export)
    # Everyday accounts start in the Inbox; a tracking account does not.
    assert import_page.in_inbox("Chequing")
    assert import_page.in_inbox("Visa")
    assert not import_page.in_inbox("Savings")
    import_page.continue_to_preview()
    import_page.apply()
    assert import_page.succeeded(), import_page.page.content()[:2000]

    book = team.default_book
    chequing = Account.objects.get(book=book, name="Chequing")
    assert BankTransaction.objects.filter(book=book, account=chequing, source="ynab").count() == 3

    feed = BankFeedPage(import_page.page, import_page.base_url)
    feed.goto(book)
    feed.click_account_card(chequing.id)
    feed.wait_for_table()
    assert feed.has_row_matching("Weekly shop")


@pytest.mark.django_db
def test_an_account_can_be_kept_out_of_the_inbox(import_page, tiny_export, team, requires_vite):
    import_page.upload(tiny_export)
    import_page.set_in_inbox("Visa", False)
    import_page.continue_to_preview()
    import_page.apply()
    assert import_page.succeeded(), import_page.page.content()[:2000]

    visa = Account.objects.get(book=team.default_book, name="Visa")
    assert not visa.has_feed
    assert not BankTransaction.objects.filter(account=visa).exists()


@pytest.mark.django_db
def test_income_payees_become_income_accounts(import_page, tiny_export, team, requires_vite):
    import_page.upload(tiny_export)
    import_page.click_next()
    import_page.page.wait_for_selector("[data-testid='ynab-income-table']")

    assert import_page.income_rows() >= 1
    import_page.set_income_account("Employer", "Day job")

    import_page.continue_to_preview()
    import_page.apply()

    assert Account.objects.filter(book=team.default_book, name="Day job", account_group__account_type="income").exists()


@pytest.mark.django_db
def test_an_income_account_made_on_one_row_is_offered_on_the_others(import_page, tiny_export, team, requires_vite):
    import_page.upload(tiny_export)
    import_page.click_next()
    import_page.page.wait_for_selector("[data-testid='ynab-income-table']")

    rows = import_page.page.locator("[data-testid='ynab-income-row']:has([data-testid='ynab-income-account'])")
    payees = [rows.nth(i).get_attribute("data-payee") for i in range(rows.count())]
    assert payees, "the tiny export has at least one income payee"

    import_page.set_income_account(payees[0], "Paycheque")
    names = import_page.page.locator("[data-testid='ynab-income-accounts-chip']")
    assert "Paycheque" in [names.nth(i).get_attribute("data-name") for i in range(names.count())]
    for payee in payees[1:]:
        import_page.set_income_account(payee, "Paycheque")

    import_page.continue_to_preview()
    import_page.apply()

    paycheque = Account.objects.filter(book=team.default_book, name="Paycheque", account_group__account_type="income")
    assert paycheque.exists()


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

    assert not Goal.objects.filter(book=team.default_book, name="House").exists()
    assert Account.objects.filter(book=team.default_book, name="House", account_group__account_type="expense").exists()


@pytest.mark.django_db
def test_one_file_is_not_enough(import_page, tiny_export, requires_vite):
    # An import needs both halves of the export, so one file leaves the button
    # disabled rather than posting half of one.
    import_page.choose_files(tiny_export[:1])
    assert not import_page.can_upload()

    import_page.choose_files(tiny_export)
    assert import_page.can_upload()


@pytest.mark.django_db
def test_a_team_that_already_has_books_is_told_why_not(import_page, team, requires_vite):
    """
    A team with a ledger and no import to speak of -- books kept in the app, or an
    import old enough that nobody opening this page is asking about it.

    (A team whose *recent* import put those transactions there sees the result of
    that import instead; that is the test above.)
    """
    JournalEntryFactory(team=team)

    import_page.goto_import(team.default_book)
    assert import_page.is_blocked()
    assert "create a new set of books" in import_page.page.locator("[data-testid='ynab-blocked']").inner_text()


@pytest.mark.django_db
def test_the_reconciliation_is_shown_before_anything_is_written(import_page, tiny_export, team, requires_vite):
    import_page.upload(tiny_export)
    import_page.continue_to_preview()

    text = import_page.preview_text()
    assert "Every transaction reached the right category" in text
    assert "Every account ends on the balance YNAB shows" in text
    # Nothing is written until the last screen.
    assert not JournalEntry.objects.filter(book=team.default_book).exists()


@pytest.mark.django_db
def test_reopening_the_page_after_an_import_shows_the_result(import_page, tiny_export, team, requires_vite):
    """
    The import runs in a worker, so the browser may be gone when it lands. Coming
    back has to answer what happened -- not present an upload form, and not refuse
    with "this team already has transactions", which says nothing about the import
    the user actually ran.
    """
    import_page.upload(tiny_export)
    import_page.continue_to_preview()
    import_page.apply()
    assert import_page.succeeded()

    # A fresh page load, as though the tab had been closed and reopened.
    import_page.goto_import(team.default_book)

    assert import_page.showing() == "ynab-done"
    assert "Your budget is in" in import_page.result_text()
    assert not import_page.is_blocked()


@pytest.mark.django_db
def test_a_failed_import_is_waiting_when_the_user_comes_back(import_page, team, requires_vite):
    """
    A worker that dies writes nothing, so the team looks untouched -- and without
    this the user has no way to learn that their import even ran.
    """
    from django.utils import timezone

    from apps.ynab_import.models import YnabImport

    YnabImport.objects.create(
        book=team.default_book,
        status=YnabImport.STATUS_FAILED,
        started_at=timezone.now(),
        finished_at=timezone.now(),
        error="The import stopped before it finished.",
    )

    import_page.goto_import(team.default_book)
    assert import_page.showing() == "ynab-failed"
    assert "stopped before it finished" in import_page.page.locator("[data-testid='ynab-failed']").inner_text()

    # Starting again returns to the files rather than back to the failure.
    import_page.page.click("[data-testid='ynab-failed'] button")
    import_page.page.wait_for_selector("[data-testid='ynab-dropzone']", timeout=15_000)
    assert import_page.showing() == "ynab-dropzone"


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
    assert "6,615" in preview  # transactions (8 more wait uncategorized in the Inbox)
    assert "6,860" in preview  # rows in the account feeds
    # The net worth they will land on: YNAB's $292,472.98 plus the $1,301.65 net
    # outflow of the 8 rows that stay out of the ledger until they are categorized.
    assert "$293,774.63" in preview

    import_page.apply()
    assert import_page.succeeded()

    result = import_page.result_text()
    assert "Your budget is in" in result
    assert "$293,774.63" in result

    assert JournalEntry.objects.filter(book=team.default_book).count() == 6615 + 13
    assert BankTransaction.objects.filter(book=team.default_book).count() == 6860
    # No `Budget` rows on goal categories (56 of the old 1,872 were on them).
    assert Budget.objects.filter(book=team.default_book).count() == 1816
    # Three open goals, plus `House` -- spent out, so it arrives closed with its history.
    assert Goal.objects.filter(book=team.default_book).count() == 4
    assert Goal.objects.filter(book=team.default_book, closed_at__isnull=True).count() == 3

    import_page.go_to_dashboard()
    import_page.page.wait_for_url(f"**{team.default_book.base_url}", timeout=30_000, wait_until="domcontentloaded")
    assert "$293,774.63" in import_page.page.locator("body").inner_text()
