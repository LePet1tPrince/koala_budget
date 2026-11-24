"""Page Object Model for the Reports section (Django-template rendered)."""

from .base import BasePage

# The sidebar's Reports popout: Monthly Review and the two reports.
REPORT_KEYS = ("monthly-review", "spending", "net-worth")


class ReportsPage(BasePage):
    def home_path(self, book) -> str:
        return f"{book.base_url}reports/"

    def spending_path(self, book) -> str:
        return f"{book.base_url}reports/spending/"

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def goto_spending(self, book, query: str = ""):
        self.goto(
            self.spending_path(book) + (f"?{query}" if query else ""),
            wait_for="[data-testid='spending-report']",
        )

    # ------------------------------------------------------------------
    # Date range picker
    # ------------------------------------------------------------------

    def date_range_label(self) -> str:
        trigger = self.page.locator("[data-testid='date-range-picker-trigger']")
        trigger.wait_for(timeout=10_000)
        return trigger.inner_text().strip()

    def type_date_range(self, start: str, end: str):
        """Type both ends of the range (DDMMYYYY); Enter on the end applies, which reloads the report."""
        self.page.locator("[data-testid='date-range-picker-trigger']").click()
        start_box = self.page.locator("[data-testid='date-range-start-text']")
        start_box.fill(start)
        start_box.press("Enter")
        end_box = self.page.locator("[data-testid='date-range-end-text']")
        end_box.fill(end)
        with self.page.expect_navigation():
            end_box.press("Enter")

    def typed_date_error(self, side: str, text: str) -> str:
        """Type an unparseable date into one side and return the error it shows."""
        self.page.locator("[data-testid='date-range-picker-trigger']").click()
        box = self.page.locator(f"[data-testid='date-range-{side}-text']")
        box.fill(text)
        box.press("Enter")
        return self.page.locator("[role='dialog'] [role='alert']").inner_text().strip()

    # ------------------------------------------------------------------
    # Income & Spending queries
    # ------------------------------------------------------------------

    def goal_spending_rows(self) -> list[str]:
        """The goal names listed under Goal spending on Income & Spending."""
        rows = self.page.locator("[data-testid='spending-goals'] tr.row-account td:first-child")
        return [rows.nth(i).inner_text().strip() for i in range(rows.count())]

    def has_summary(self) -> bool:
        return self.page.locator("[data-testid='spending-summary']").is_visible()

    def has_statement(self) -> bool:
        return self.page.locator("[data-testid='spending-statement']").is_visible()

    def has_export_btn(self) -> bool:
        return self.page.locator("[data-testid='export-csv-btn']").is_visible()
