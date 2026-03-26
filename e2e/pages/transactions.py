"""Page Object Model for the Transactions page (React-rendered)."""

from .base import BasePage


class TransactionsPage(BasePage):
    def path(self, team_slug: str) -> str:
        return f"/a/{team_slug}/journal/transactions/"

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def goto(self, team_slug: str):
        """Navigate to the transactions page and wait for the React app to mount."""
        self.page.goto(self.url(self.path(team_slug)))
        # Wait for React to finish loading: either the table or the empty state appears
        self.page.wait_for_selector(
            "[data-testid='transactions-table'], [data-testid='transactions-empty-state']",
            timeout=15_000,
        )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_row_count(self) -> int:
        return self.page.locator("[data-testid='transaction-row']").count()

    def has_table(self) -> bool:
        return self.page.locator("[data-testid='transactions-table']").is_visible()

    def is_empty(self) -> bool:
        return self.page.locator("[data-testid='transactions-empty-state']").is_visible()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def search(self, query: str):
        self.page.locator("[data-testid='transaction-search']").fill(query)
        # React filters client-side so no explicit wait needed, but give a tick
        self.page.wait_for_timeout(300)
