"""Page Object Model for the Accounts section.

The accounts home is a React drag-and-drop board (requires the Vite dev
server); the create/edit forms are Django-template rendered.
"""

from .base import BasePage


class AccountsPage(BasePage):
    def home_path(self, book) -> str:
        return f"{book.base_url}accounts/"

    def create_path(self, book) -> str:
        return f"{book.base_url}accounts/accounts/new/"

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def goto_home(self, book):
        self.goto(self.home_path(book), wait_for="[data-testid='account-type-section']")

    def goto_create(self, book):
        self.goto(self.create_path(book), wait_for="[data-testid='account-form']")

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_account_names(self) -> list[str]:
        return self.page.locator("[data-testid='account-name']").all_text_contents()

    def get_row_count(self) -> int:
        return self.page.locator("[data-testid='account-row']").count()

    def get_group_names(self) -> list[str]:
        return self.page.locator("[data-testid='group-name']").all_text_contents()

    def selected_tab(self) -> str:
        tab = self.page.locator("[data-testid^='account-type-tab-'][aria-selected='true']")
        return tab.get_attribute("data-testid").removeprefix("account-type-tab-")

    def account_row(self, name: str):
        return self.page.locator("[data-testid='account-row']", has=self.page.locator(f"text='{name}'"))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def select_tab(self, key: str):
        """Show one account type: asset, liability, income, expense or goal (goals + equity)."""
        self.page.locator(f"[data-testid='account-type-tab-{key}']").click()
        self.page.wait_for_selector(f"[data-testid='account-type-tab-{key}'][aria-selected='true']")

    def toggle_hidden(self, name: str):
        """Click an account's eye and wait for the board to confirm the save."""
        self.account_row(name).locator("[data-testid='account-visibility-toggle']").click()
        self.page.wait_for_selector("[data-testid='board-toast']")

    def click_new_account(self):
        self.page.locator("[data-testid='new-account-btn']").click()
        self.page.wait_for_selector("[data-testid='account-form']")

    def fill_account_form(self, name: str, account_group_name: str, account_type: str = "expense"):
        self.page.locator("[name='name']").fill(name)
        # The create form uses Alpine button pickers (not <select>s): choose the
        # account type first, which reveals that type's group buttons.
        self.page.locator(f"[data-testid='type-btn-{account_type}']").click()
        self.page.locator("[data-testid='group-btn']", has_text=account_group_name).first.click()

    def submit_form(self):
        self.page.locator("[data-testid='save-btn']").click()

    def click_cancel(self):
        self.page.locator("[data-testid='cancel-btn']").click()

    def click_account(self, name: str):
        self.page.locator("[data-testid='account-name']", has_text=name).first.click()

    def create_account(self, name: str, account_group_name: str, book, account_type: str = "expense"):
        """High-level helper: navigate to create form, fill, and submit."""
        self.goto_create(book)
        self.fill_account_form(name, account_group_name, account_type)
        self.submit_form()
        # After save, Django redirects to the account detail page
        self.page.wait_for_url(f"**{book.base_url}accounts/**", timeout=10_000)
