"""Page Object Model for the Accounts section (Django-template rendered)."""

from playwright.sync_api import Page

from .base import BasePage


class AccountsPage(BasePage):
    def list_path(self, team_slug: str) -> str:
        return f"/a/{team_slug}/accounts/accounts/"

    def create_path(self, team_slug: str) -> str:
        return f"/a/{team_slug}/accounts/accounts/new/"

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def goto_list(self, team_slug: str):
        self.goto(self.list_path(team_slug), wait_for="[data-testid='accounts-table'], [data-testid='new-account-btn']")

    def goto_create(self, team_slug: str):
        self.goto(self.create_path(team_slug), wait_for="[data-testid='account-form']")

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_account_names(self) -> list[str]:
        return self.page.locator("[data-testid='account-name']").all_text_contents()

    def get_row_count(self) -> int:
        return self.page.locator("[data-testid='account-row']").count()

    def has_table(self) -> bool:
        return self.page.locator("[data-testid='accounts-table']").is_visible()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def click_new_account(self):
        self.page.locator("[data-testid='new-account-btn']").click()
        self.page.wait_for_selector("[data-testid='account-form']")

    def fill_account_form(self, name: str, account_number: str, account_group_name: str):
        self.page.locator("[name='name']").fill(name)
        self.page.locator("[name='account_number']").fill(account_number)
        self.page.select_option("[name='account_group']", label=account_group_name)

    def submit_form(self):
        self.page.locator("[data-testid='save-btn']").click()

    def click_cancel(self):
        self.page.locator("[data-testid='cancel-btn']").click()

    def click_edit(self, index: int = 0):
        self.page.locator("[data-testid='edit-account-btn']").nth(index).click()
        self.page.wait_for_selector("[data-testid='account-form']")

    def create_account(self, name: str, account_number: str, account_group_name: str, team_slug: str):
        """High-level helper: navigate to create form, fill, and submit."""
        self.goto_create(team_slug)
        self.fill_account_form(name, account_number, account_group_name)
        self.submit_form()
        # After save, Django redirects back to the list
        self.page.wait_for_url(f"**/a/{team_slug}/accounts/**", timeout=10_000)
