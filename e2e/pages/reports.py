"""Page Object Model for the Reports section (Django-template rendered)."""

from playwright.sync_api import Page

from .base import BasePage


class ReportsPage(BasePage):
    def home_path(self, team_slug: str) -> str:
        return f"/a/{team_slug}/reports/"

    def income_statement_path(self, team_slug: str) -> str:
        return f"/a/{team_slug}/reports/income-statement/"

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def goto_home(self, team_slug: str):
        self.goto(
            self.home_path(team_slug),
            wait_for="[data-testid='report-link-income-statement']",
        )

    def goto_income_statement(self, team_slug: str):
        self.goto(self.income_statement_path(team_slug))
        # The page always renders (summary only shows when there's data)
        self.page.wait_for_selector("section.app-card", timeout=10_000)

    # ------------------------------------------------------------------
    # Reports home queries
    # ------------------------------------------------------------------

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
