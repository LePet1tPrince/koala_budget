"""Page Object Model for the Reports section (Django-template rendered)."""

from .base import BasePage

# Reports home and the sidebar's Reports popout list the same four reports.
REPORT_KEYS = ("monthly-review", "spending", "net-worth", "budget-goals")


class ReportsPage(BasePage):
    def home_path(self, book) -> str:
        return f"{book.base_url}reports/"

    def spending_path(self, book) -> str:
        return f"{book.base_url}reports/spending/"

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def goto_home(self, book):
        self.goto(
            self.home_path(book),
            wait_for="[data-testid='report-link-spending']",
        )

    def goto_spending(self, book, query: str = ""):
        self.goto(
            self.spending_path(book) + (f"?{query}" if query else ""),
            wait_for="[data-testid='spending-report']",
        )

    # ------------------------------------------------------------------
    # Reports home queries
    # ------------------------------------------------------------------

    def report_links(self) -> list[str]:
        """The keys of the reports linked from Reports home, in page order."""
        links = self.page.locator("[data-testid^='report-link-']")
        return [links.nth(i).get_attribute("data-testid").removeprefix("report-link-") for i in range(links.count())]

    def click_report(self, key: str):
        self.page.locator(f"[data-testid='report-link-{key}']").click()

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
