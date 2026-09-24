"""
E2E tests for multiple sets of books (docs/books-plan.md §9).

Switching books, creating one through the walkthrough, the future-income setting
hiding and restoring the budget's Income section, and old `/a/{team}/...` links.
"""

import pytest
from playwright.sync_api import Page

from e2e.factories import AccountFactory, AccountGroupFactory
from e2e.pages.books import BookBudgetingPage, BookCreatePage, BookSwitcher
from e2e.pages.budget import BudgetPage
from e2e.pages.onboarding import OnboardingPage


@pytest.mark.django_db(transaction=True)
def test_switching_books_changes_what_the_pages_show(authenticated_page: Page, live_server, team, book, second_book):
    from apps.accounts.models import ACCOUNT_TYPE_EXPENSE, Account, AccountGroup

    AccountFactory(
        team=team,
        account_group=AccountGroupFactory(team=team, account_type=ACCOUNT_TYPE_EXPENSE),
        name="Personal Groceries",
    )
    group = AccountGroup.objects.create(book=second_book, name="Business costs", account_type=ACCOUNT_TYPE_EXPENSE)
    Account.objects.create(book=second_book, name="Office Rent", account_group=group)

    budget = BudgetPage(authenticated_page, live_server.url)
    budget.goto_budget(book)
    assert authenticated_page.get_by_text("Personal Groceries").count() > 0

    switcher = BookSwitcher(authenticated_page, live_server.url)
    switcher.switch_to(second_book)
    assert switcher.current_book_name() == "Business"

    budget.goto_budget(second_book)
    assert authenticated_page.get_by_text("Office Rent").count() > 0
    assert authenticated_page.get_by_text("Personal Groceries").count() == 0


@pytest.mark.django_db(transaction=True)
def test_the_team_root_opens_the_book_last_used(authenticated_page: Page, live_server, team, second_book):
    BudgetPage(authenticated_page, live_server.url).goto_budget(second_book)
    authenticated_page.goto(f"{live_server.url}/a/{team.slug}/", wait_until="domcontentloaded")
    assert authenticated_page.url.rstrip("/").endswith(second_book.base_url.rstrip("/"))


@pytest.mark.django_db(transaction=True)
def test_creating_a_book_starts_the_walkthrough(authenticated_page: Page, live_server, team, requires_vite):
    from apps.books.models import Book

    create = BookCreatePage(authenticated_page, live_server.url)
    create.goto(team)
    create.create("Side Business")

    new_book = Book.objects.get(team=team, name="Side Business")
    authenticated_page.wait_for_url(f"**{new_book.base_url}onboarding/", timeout=30_000, wait_until="domcontentloaded")
    onboarding = OnboardingPage(authenticated_page, live_server.url)
    authenticated_page.wait_for_selector("[data-testid='onboarding-takeover']", timeout=10_000)
    assert onboarding.is_welcome_visible()


@pytest.mark.django_db(transaction=True)
def test_future_income_toggle_hides_and_restores_the_income_section(authenticated_page: Page, live_server, team, book):
    from apps.accounts.models import ACCOUNT_TYPE_EXPENSE, ACCOUNT_TYPE_INCOME

    AccountFactory(
        team=team, account_group=AccountGroupFactory(team=team, account_type=ACCOUNT_TYPE_INCOME), name="Paycheque"
    )
    AccountFactory(
        team=team, account_group=AccountGroupFactory(team=team, account_type=ACCOUNT_TYPE_EXPENSE), name="Groceries"
    )

    budget = BudgetPage(authenticated_page, live_server.url)
    budget.goto_budget(book)
    assert authenticated_page.locator("[data-testid='budget-total-income']").count() == 1

    settings = BookBudgetingPage(authenticated_page, live_server.url)
    settings.goto(book)
    # The consequence is stated before saving.
    assert "Turned off, your Unassigned would be" in settings.consequence()
    settings.toggle()
    settings.save()

    budget.goto_budget(book)
    assert authenticated_page.locator("[data-testid='budget-total-income']").count() == 0
    assert authenticated_page.get_by_text("Paycheque").count() == 0

    settings.goto(book)
    settings.toggle()
    settings.save()
    budget.goto_budget(book)
    assert authenticated_page.locator("[data-testid='budget-total-income']").count() == 1


@pytest.mark.django_db(transaction=True)
def test_an_old_link_lands_on_the_default_book(authenticated_page: Page, live_server, team, book):
    authenticated_page.goto(f"{live_server.url}/a/{team.slug}/budget/?month=2026-03-01", wait_until="domcontentloaded")
    assert f"{book.base_url}budget/" in authenticated_page.url
    assert "month=2026-03-01" in authenticated_page.url
