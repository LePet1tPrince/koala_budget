"""Page Objects for sets of books: the Team › Book switcher and the book settings pages."""

from .base import BasePage


class BookSwitcher(BasePage):
    """The "My books" submenu of the sidebar's user menu (desktop): the team's books, then other teams."""

    def open(self):
        self.page.locator("[data-testid='user-menu']").click()
        self.page.locator("[data-testid='my-books-toggle']:visible").click()

    def current_book_name(self) -> str:
        return self.page.locator("[data-testid='switcher-book-name']").inner_text().strip()

    def switch_to(self, book):
        self.open()
        self.page.locator(f"[data-testid='book-switch-{book.slug}']:visible").click()
        self.page.wait_for_url(f"**{book.base_url}**", timeout=10_000, wait_until="domcontentloaded")

    def new_book(self):
        self.open()
        self.page.locator("[data-testid='new-book-link']:visible").click()
        self.page.wait_for_selector("[data-testid='book-create-form']", timeout=10_000)


class BookCreatePage(BasePage):
    def path(self, team) -> str:
        return f"/a/{team.slug}/books/new/"

    def goto(self, team):
        super().goto(self.path(team), wait_for="[data-testid='book-create-form']")

    def create(self, name: str, start: str = "questionnaire"):
        self.page.locator("#id_name").fill(name)
        self.page.locator(f"[data-testid='book-start-{start}']").click()
        self.page.locator("[data-testid='book-create-submit']").click()


class BookBudgetingPage(BasePage):
    def path(self, book) -> str:
        return f"{book.base_url}settings/budgeting/"

    def goto(self, book):
        super().goto(self.path(book), wait_for="[data-testid='book-budgeting-form']")

    def toggle(self):
        self.page.locator("[data-testid='budget-future-income-toggle']").click()

    def consequence(self) -> str:
        return self.page.locator("[data-testid='budget-future-income-consequence']").inner_text()

    def save(self):
        self.page.locator("[data-testid='book-budgeting-save']").click()
        self.page.wait_for_load_state("domcontentloaded")
