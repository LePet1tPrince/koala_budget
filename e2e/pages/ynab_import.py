"""
Page Object Model for the YNAB import wizard.

One React app over six screens, so every test using this needs `requires_vite`.
The walk is deliberately expressed as "continue until the next screen appears"
rather than as a fixed sequence of clicks: the wizard's steps are allowed to grow,
and a POM that counted them would have to be rewritten when they do.
"""

import glob
import os

from .base import BasePage

REFERENCE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "docs",
    "reference",
)


def sample_export_paths() -> list[str]:
    """The sample YNAB export the plan document was measured against."""
    return sorted(glob.glob(os.path.join(REFERENCE, "*.csv")))


class YnabImportPage(BasePage):
    def path(self, team_slug: str) -> str:
        return f"/a/{team_slug}/ynab-import/"

    def goto_import(self, team_slug: str):
        self.goto(self.path(team_slug), wait_for="[data-testid='ynab-steps'], [data-testid='ynab-blocked']")

    # ------------------------------------------------------------------
    # Step 1 -- the files
    # ------------------------------------------------------------------

    def is_blocked(self) -> bool:
        return self.page.locator("[data-testid='ynab-blocked']").count() > 0

    def showing(self) -> str:
        """Which screen the page opened on -- what a returning user is shown."""
        for name in ("ynab-done", "ynab-failed", "ynab-running", "ynab-blocked", "ynab-dropzone"):
            if self.page.locator(f"[data-testid='{name}']").count():
                return name
        return ""

    def upload(self, paths: list[str], timeout: int = 60_000):
        self.page.locator("[data-testid='ynab-file-input']").set_input_files(paths)
        self.page.locator("[data-testid='ynab-upload-btn']").click()
        self.page.wait_for_selector("[data-testid='ynab-accounts-table']", timeout=timeout)

    def upload_error(self) -> str:
        return self.page.locator("[data-testid='ynab-error']").inner_text()

    def choose_files(self, paths: list[str]):
        """Pick the files without submitting them."""
        self.page.locator("[data-testid='ynab-file-input']").set_input_files(paths)

    def can_upload(self) -> bool:
        return self.page.locator("[data-testid='ynab-upload-btn']").is_enabled()

    # ------------------------------------------------------------------
    # Steps 2-4 -- the review screens
    # ------------------------------------------------------------------

    def account_rows(self) -> int:
        return self.page.locator("[data-testid='ynab-account-row']").count()

    def account_row(self, name: str):
        # By `data-account`, not by text: an account's name lives in an input's
        # value, which no text locator can see.
        return self.page.locator(f"[data-testid='ynab-account-row'][data-account='{name}']").first

    def account_type(self, name: str) -> str:
        return self.account_row(name).locator("select").input_value()

    def set_account_type(self, name: str, value: str):
        self.account_row(name).locator("select").select_option(value)

    def drop_account(self, name: str):
        self.account_row(name).locator("input[type='checkbox']").uncheck()

    def income_rows(self) -> int:
        return self.page.locator("[data-testid='ynab-income-row']").count()

    def income_row(self, payee: str):
        return self.page.locator(f"[data-testid='ynab-income-row'][data-payee='{payee}']").first

    def set_income_account(self, payee: str, name: str):
        field = self.income_row(payee).locator("input[type='text']")
        field.fill(name)

    def goal_cards(self) -> int:
        return self.page.locator("[data-testid='ynab-goal-card']").count()

    def goal_card(self, name: str):
        return self.page.locator(f"[data-testid='ynab-goal-card'][data-category='{name}']").first

    def set_goal_kind(self, name: str, value: str):
        self.goal_card(name).locator("select").select_option(value)

    def click_next(self):
        self.page.locator("[data-testid='ynab-next']").click()

    def click_back(self):
        self.page.locator("[data-testid='ynab-back']").click()

    def continue_to_preview(self, timeout: int = 60_000):
        """
        Click Continue until the review screen is up, whatever sits in between.

        Driven by what is on screen rather than by a step count: the wizard is
        allowed to grow a screen without this having to be rewritten. The review
        step replaces Continue with Import, so a missing Continue means we are
        there (or already loading it).
        """
        for _ in range(10):
            if self.page.locator("[data-testid='ynab-preview'], [data-testid='ynab-preview-loading']").count() > 0:
                break
            button = self.page.locator("[data-testid='ynab-next']")
            if button.count() == 0:
                break
            button.click()
            self.page.wait_for_timeout(200)
        self.page.wait_for_selector("[data-testid='ynab-reconciliation']", timeout=timeout)

    # ------------------------------------------------------------------
    # Step 5 -- the preview
    # ------------------------------------------------------------------

    def preview_text(self) -> str:
        return self.page.locator("[data-testid='ynab-preview']").inner_text()

    def checks(self) -> dict[str, str]:
        """Each reconciliation check's heading mapped to the detail under it."""
        rows = self.page.locator("[data-testid='ynab-reconciliation'] li")
        return {
            rows.nth(index).locator("div div").first.inner_text(): rows.nth(index).inner_text()
            for index in range(rows.count())
        }

    def chart_text(self) -> str:
        return self.page.locator("[data-testid='ynab-preview']").inner_text()

    # ------------------------------------------------------------------
    # Step 6 -- applying
    # ------------------------------------------------------------------

    def apply(self, timeout: int = 180_000):
        self.page.locator("[data-testid='ynab-apply']").click()
        self.page.wait_for_selector(
            "[data-testid='ynab-done'], [data-testid='ynab-failed']",
            timeout=timeout,
        )

    def succeeded(self) -> bool:
        return self.page.locator("[data-testid='ynab-done']").count() > 0

    def result_text(self) -> str:
        return self.page.locator("[data-testid='ynab-done']").inner_text()

    def go_to_dashboard(self):
        self.page.locator("[data-testid='ynab-go-home']").click()
