"""Page Object Model for the Reports section (Django-template rendered)."""

from .base import BasePage


class ReportsPage(BasePage):
    def home_path(self, book) -> str:
        return f"{book.base_url}reports/"

    def income_statement_path(self, book) -> str:
        return f"{book.base_url}reports/income-statement/"

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def goto_home(self, book):
        self.goto(
            self.home_path(book),
            wait_for="[data-testid='report-link-income-statement']",
        )

    def goto_income_statement(self, book):
        self.goto(self.income_statement_path(book))
        # The page always renders (summary only shows when there's data)
        self.page.wait_for_selector("section.app-card", timeout=10_000)

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
    # Reports home queries
    # ------------------------------------------------------------------

    def goal_spending_rows(self) -> list[str]:
        """The goal names listed under Goal spending on the income statement."""
        rows = self.page.locator("[data-testid='goal-spending-table'] tr.row-account td:first-child")
        return [rows.nth(i).inner_text().strip() for i in range(rows.count())]

    def has_income_statement_link(self) -> bool:
        return self.page.locator("[data-testid='report-link-income-statement']").is_visible()

    def has_balance_sheet_link(self) -> bool:
        return self.page.locator("[data-testid='report-link-balance-sheet']").is_visible()

    def has_net_worth_trend_link(self) -> bool:
        return self.page.locator("[data-testid='report-link-net-worth-trend']").is_visible()

    # ------------------------------------------------------------------
    # Income statement queries
    # ------------------------------------------------------------------

    def has_summary(self) -> bool:
        return self.page.locator("[data-testid='income-statement-summary']").is_visible()

    def has_income_table(self) -> bool:
        return self.page.locator("[data-testid='income-table']").is_visible()

    def has_expenses_table(self) -> bool:
        return self.page.locator("[data-testid='expenses-table']").is_visible()

    def has_export_btn(self) -> bool:
        return self.page.locator("[data-testid='export-csv-btn']").is_visible()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def click_income_statement(self):
        self.page.locator("[data-testid='report-link-income-statement']").click()
        self.page.wait_for_selector("section.app-card", timeout=10_000)

    def click_export_csv(self):
        self.page.locator("[data-testid='export-csv-btn']").click()
