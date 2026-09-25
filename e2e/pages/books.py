"""Page Objects for sets of books: the Team › Book switcher and the book settings pages."""

from .base import BasePage


class BookSwitcher(BasePage):
    """The sidebar tile (desktop). Its menu lists the team's books, then other teams."""

    def open(self):
        self.page.locator("[data-testid='team-switcher']").click()

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


class BookSettingsPage(BasePage):
    """This book's settings: name, address and the future-income toggle, on one page with one Save."""

    def path(self, book) -> str:
        return f"{book.base_url}settings/"

    def goto(self, book):
        super().goto(self.path(book), wait_for="[data-testid='book-settings-form']")

    def toggle(self):
        self.page.locator("[data-testid='budget-future-income-toggle']").click()

    def consequence(self) -> str:
        return self.page.locator("[data-testid='budget-future-income-consequence']").inner_text()

    def save(self):
        self.page.locator("[data-testid='book-settings-save']").click()
        self.page.wait_for_load_state("domcontentloaded")


class BookListPage(BasePage):
    """My books: every book in the team, with Archive / Delete behind a type-the-name dialog."""

    def path(self, team) -> str:
        return f"/a/{team.slug}/books/"

    def goto(self, team):
        super().goto(self.path(team), wait_for="[data-testid='book-list']")

    def _confirm(self, action: str, book, name: str):
        self.page.locator(f"[data-testid='book-{action}-{book.slug}']").click()
        dialog = self.page.locator(f"[data-testid='book-{action}-dialog-{book.slug}']")
        dialog.wait_for(state="visible")
        self.page.locator(f"[data-testid='book-{action}-confirm-{book.slug}']").fill(name)

    def submit_button(self, action: str, book):
        return self.page.locator(f"[data-testid='book-{action}-submit-{book.slug}']")

    def archive(self, book, name: str):
        self._confirm("archive", book, name)
        self.submit_button("archive", book).click()
        self.page.wait_for_selector("[data-testid='book-list']")

    def delete(self, book, name: str):
        self._confirm("delete", book, name)
        self.submit_button("delete", book).click()
        self.page.wait_for_selector("[data-testid='book-list']")
