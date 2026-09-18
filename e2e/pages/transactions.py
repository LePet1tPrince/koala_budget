"""Page Object Model for the Transactions page (React-rendered)."""

import contextlib
import re

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

    # ------------------------------------------------------------------
    # Column menus (filter + sort)
    # ------------------------------------------------------------------

    def open_column_menu(self, column: str):
        """Open one column's chevron menu and wait for its values to load."""
        self.page.locator(f"[data-testid='column-menu-btn-{column}']").click()
        self.page.wait_for_selector(f"[data-testid='column-menu-{column}']")
        # The values come from the API, so the list starts empty.
        self.page.wait_for_selector(f"[data-testid='column-menu-{column}'] input[type='checkbox']", timeout=15_000)

    def column_filter_values(self, column: str) -> list[str]:
        """The value labels currently offered in an open column menu."""
        menu = self.page.locator(f"[data-testid='column-menu-{column}']")
        return [text.strip() for text in menu.locator("[data-testid='column-value-label']").all_inner_texts()]

    def tick_column_value(self, column: str, label: str):
        """
        Tick a value by its exact label; a nested value must be expanded first.

        Exact, because every row also renders its count: a substring match for
        "3" would just as happily hit the year row whose count is 3.
        """
        menu = self.page.locator(f"[data-testid='column-menu-{column}']")
        exact = re.compile(f"^{re.escape(label)}$")
        menu.locator("label:has(input[type='checkbox'])").filter(
            has=self.page.get_by_test_id("column-value-label").filter(has_text=exact)
        ).first.click()

    def expand_tree_node(self, value: str):
        """Open one branch of a hierarchical column's value tree."""
        self.page.locator(f"[data-testid='tree-toggle-{value}']").click()

    def menu_selection_summary(self, column: str) -> str:
        """The open menu's "N selected" / "Showing all" caption."""
        return self.page.locator(f"[data-testid='column-selected-count-{column}']").inner_text().strip()

    def select_all_in_menu(self, column: str):
        self.page.locator(f"[data-testid='column-select-all-{column}']").click()

    def clear_menu_selection(self, column: str):
        """Drop the staged selection without closing the menu."""
        self.page.locator(f"[data-testid='column-clear-selection-{column}']").click()

    def apply_column_filter(self, column: str):
        """Commit an open column menu's selection and wait for the refetch."""
        self.page.locator(f"[data-testid='column-apply-{column}']").click()
        self._wait_for_refetch()

    def clear_all_column_filters(self):
        self.page.locator("[data-testid='clear-column-filters']").click()
        self._wait_for_refetch()

    def has_active_filter(self, column: str) -> bool:
        return self.page.locator(f"[data-testid='active-filter-{column}']").is_visible()

    def active_filter_text(self, column: str) -> str:
        return self.page.locator(f"[data-testid='active-filter-{column}']").inner_text().strip()

    def sort_by(self, column: str):
        """Click a column header, cycling it ascending -> descending -> unsorted."""
        self.page.locator(f"[data-testid='column-sort-{column}']").click()
        self._wait_for_refetch()

    def column_text(self, index: int) -> list[str]:
        """Every row's cell in the 1-based column `index`, top to bottom."""
        cells = self.page.locator(f"[data-testid='transaction-row'] td:nth-child({index})")
        return [text.strip() for text in cells.all_inner_texts()]

    def _wait_for_refetch(self):
        """Wait out the in-flight request, the way `search` does."""
        indicator = self.page.locator("[data-testid='transactions-refetching']")
        with contextlib.suppress(PlaywrightTimeoutError):
            indicator.wait_for(state="visible", timeout=2_000)
        indicator.wait_for(state="hidden", timeout=15_000)
