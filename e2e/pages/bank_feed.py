"""Page Object Model for the Bank Feed page (React-rendered)."""

from .base import BasePage


class BankFeedPage(BasePage):
    def path(self, team_slug: str) -> str:
        return f"/a/{team_slug}/bankfeed/"

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def goto(self, team_slug: str):
        """Navigate to the bank feed page and wait for the React app to mount."""
        self.page.goto(self.url(self.path(team_slug)))
        # Wait until at least one account card or the line-app container is visible
        self.page.wait_for_selector("#line-app", timeout=15_000)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_account_card_count(self) -> int:
        return self.page.locator("[data-testid^='account-card-']").count()

    def has_account_card(self, account_id: int) -> bool:
        return self.page.locator(f"[data-testid='account-card-{account_id}']").is_visible()

    def is_filter_visible(self) -> bool:
        return self.page.locator("[data-testid='filter-to-review']").is_visible()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def click_account_card(self, account_id: int):
        """Select an account card to load its bank feed."""
        self.page.locator(f"[data-testid='account-card-{account_id}']").click()
        # After clicking, the filter toggles and table should appear
        self.page.wait_for_selector("[data-testid='filter-to-review']", timeout=10_000)

    def click_add_transaction(self):
        """Click the add-transaction button to open the edit modal."""
        self.page.locator("[data-testid='add-transaction-btn']").click()
        self.page.wait_for_selector("[data-testid='edit-transaction-modal']", timeout=5_000)

    def close_modal(self):
        self.page.locator("[data-testid='modal-cancel-btn']").click()

    def click_filter(self, mode: str):
        """Click a filter toggle. mode is one of: to_review, reconciled, archived."""
        self.page.locator(f"[data-testid='filter-{mode}']").click()
        self.page.wait_for_timeout(300)
