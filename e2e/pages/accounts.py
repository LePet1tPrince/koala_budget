"""Page Object Model for the Accounts section.

The accounts home is a React drag-and-drop board (requires the Vite dev
server); the create/edit forms are Django-template rendered.
"""

from .base import BasePage


class AccountsPage(BasePage):
    def home_path(self, team_slug: str) -> str:
        return f"/a/{team_slug}/accounts/"

    def create_path(self, team_slug: str) -> str:
        return f"/a/{team_slug}/accounts/accounts/new/"

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def goto_home(self, team_slug: str):
        self.goto(self.home_path(team_slug), wait_for="[data-testid='account-type-section']")

    def goto_create(self, team_slug: str):
        self.goto(self.create_path(team_slug), wait_for="[data-testid='account-form']")

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_account_names(self) -> list[str]:
        return self.page.locator("[data-testid='account-name']").all_text_contents()

    def get_row_count(self) -> int:
        return self.page.locator("[data-testid='account-row']").count()

    def get_group_names(self) -> list[str]:
        return self.page.locator("[data-testid='group-name']").all_text_contents()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

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

    def create_account(self, name: str, account_group_name: str, team_slug: str, account_type: str = "expense"):
        """High-level helper: navigate to create form, fill, and submit."""
        self.goto_create(team_slug)
        self.fill_account_form(name, account_group_name, account_type)
        self.submit_form()
        # After save, Django redirects to the account detail page
        self.page.wait_for_url(f"**/a/{team_slug}/accounts/**", timeout=10_000)
