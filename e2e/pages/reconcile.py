"""Page objects for statement reconciliation (`apps.reconciliation`)."""

from playwright.sync_api import expect

from .base import BasePage


class ReconcilePage(BasePage):
    """The per-account page: start form, workspace, result, history."""

    def goto(self, book, account_id: int, query: str = ""):
        super().goto(f"{book.base_url}reconcile/{account_id}/{query}", wait_for="[data-testid='reconcile-title']")
        # Either the start form or a resumed workspace.
        self.page.wait_for_selector(
            "[data-testid='reconcile-start-form'], [data-testid='reconcile-workspace']", timeout=15_000
        )

    def start(self, balance: str):
        """Start a draft on the default statement date with `balance` as printed."""
        self.page.locator("[data-testid='statement-balance']").fill(balance)
        self.page.locator("[data-testid='reconcile-start-btn']").click()
        self.page.wait_for_selector("[data-testid='reconcile-workspace']", timeout=15_000)

    def row(self, line_id: int):
        return self.page.locator(f"[data-testid='line-row-{line_id}']")

    def tick(self, line_id: int):
        self.row(line_id).click()
        expect(self.row(line_id)).to_have_attribute("data-ticked", "true")

    def is_ticked(self, line_id: int) -> bool:
        return self.row(line_id).get_attribute("data-ticked") == "true"

    def tick_all_through(self):
        self.page.locator("[data-testid='tick-through-btn']").click()

    def difference(self):
        return self.page.locator("[data-testid='summary-difference']")

    def wait_saved(self):
        expect(self.page.get_by_text("All ticks saved")).to_be_visible(timeout=10_000)

    def finish(self):
        self.page.locator("[data-testid='reconcile-finish-btn']").click()

    def finish_with_adjustment(self):
        self.finish()
        self.page.locator("[data-testid='finish-adjust-btn']").click()

    def done(self):
        return self.page.locator("[data-testid='reconcile-done']")

    def hint(self, kind: str):
        return self.page.locator(f"[data-testid='hint-{kind}']")

    def history_statuses(self):
        """A locator over the status badges; assert with `expect(...).to_have_text([...])` (it refreshes async)."""
        return self.page.locator("[data-testid='history-status']")


class ReconcileHubPage(BasePage):
    def goto(self, book):
        super().goto(f"{book.base_url}reconcile/", wait_for="[data-testid='reconcile-hub']")

    def status_for(self, account_id: int) -> str:
        row = self.page.locator(f"[data-testid='reconcile-account-row'][data-account-id='{account_id}']")
        return row.locator("[data-testid='reconcile-account-status']").inner_text()
