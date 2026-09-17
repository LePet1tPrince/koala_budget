"""Page Object Model for the Transactions page (React-rendered)."""

import contextlib

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect

from .base import BasePage


class TransactionsPage(BasePage):
    def path(self, team_slug: str) -> str:
        return f"/a/{team_slug}/journal/transactions/"

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def goto(self, team_slug: str):
        """Navigate to the transactions page and wait for the React app to mount."""
        console_msgs = []
        failed_urls = []
        self.page.on("console", lambda msg: console_msgs.append(f"[{msg.type}] {msg.text}"))
        self.page.on("requestfailed", lambda req: failed_urls.append(f"{req.failure} {req.url}"))

        self.page.goto(self.url(self.path(team_slug)))
        # Wait for React to finish loading: either the table or the empty state appears
        try:
            self.page.wait_for_selector(
                "[data-testid='transactions-table'], [data-testid='transactions-empty-state']",
                timeout=15_000,
            )
        except Exception:
            print(f"\n[TransactionsPage] Page HTML snippet:\n{self.page.content()[:3000]}")
            print("\n[TransactionsPage] Console messages:\n" + "\n".join(console_msgs[-20:]))
            print("\n[TransactionsPage] Failed requests:\n" + "\n".join(failed_urls))
            raise

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
        """Type into the search box and wait for the filtered rows to land.

        Search is server-side and debounced 300ms, so the rows on screen stay
        stale until the refetch resolves -- waiting the debounce alone returns
        just as the request is dispatched, and the caller then counts the old
        rows. Wait for the in-flight indicator to clear instead.
        """
        self.page.locator("[data-testid='transaction-search']").fill(query)
        indicator = self.page.locator("[data-testid='transactions-refetching']")
        # The fetch can resolve before we look, so a missed "visible" is fine;
        # the "hidden" wait below still confirms nothing is in flight.
        with contextlib.suppress(PlaywrightTimeoutError):
            indicator.wait_for(state="visible", timeout=2_000)
        indicator.wait_for(state="hidden", timeout=15_000)

    def expect_row_count(self, count: int, timeout: int = 15_000):
        """Auto-retrying row-count assertion, so a late render can't fail it."""
        expect(self.page.locator("[data-testid='transaction-row']")).to_have_count(count, timeout=timeout)
