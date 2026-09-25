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
    def path(self, book) -> str:
        return f"{book.base_url}ynab-import/"

    def goto_import(self, book):
        self.goto(self.path(book), wait_for="[data-testid='ynab-steps'], [data-testid='ynab-blocked']")

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

    def _choose(self, chip, test_id: str, name: str):
        """
        Pick `name` from a row's chip menu, creating it there if the list lacks it.

        The menu is portaled out of the row, so it is found by its own testid.
        """
        chip.click()
        menu = self.page.locator(f"[data-testid='{test_id}-menu']")
        option = menu.get_by_role("option", name=name, exact=True)
        if option.count():
            option.click()
            return
        menu.locator(f"[data-testid='{test_id}-new']").click()
        menu.locator(f"[data-testid='{test_id}-new-form'] input").fill(name)
        menu.locator(f"[data-testid='{test_id}-new-form'] input").press("Enter")

    def account_group(self, name: str) -> str:
        return self.account_row(name).locator("[data-testid='ynab-account-group']").get_attribute("data-value")

    def set_account_group(self, name: str, group: str):
        chip = self.account_row(name).locator("[data-testid='ynab-account-group']")
        self._choose(chip, "ynab-account-group", group)

    def group_names(self, account_type: str) -> list[str]:
        """The groups listed at the top of the accounts screen for one type."""
        chips = self.page.locator(f"[data-testid='ynab-groups-{account_type}-chip']")
        return [chips.nth(i).get_attribute("data-name") for i in range(chips.count())]

    def add_group(self, account_type: str, name: str):
        """Add a group with the + at the top of the accounts screen."""
        bank = f"ynab-groups-{account_type}"
        self.page.locator(f"[data-testid='{bank}-add']").click()
        field = self.page.locator(f"[data-testid='{bank}-new-form'] input")
        field.fill(name)
        field.press("Enter")

    def income_account(self, payee: str) -> str:
        return self.income_row(payee).locator("[data-testid='ynab-income-account']").get_attribute("data-value")

    def set_income_account(self, payee: str, name: str):
        chip = self.income_row(payee).locator("[data-testid='ynab-income-account']")
        self._choose(chip, "ynab-income-account", name)

    def goal_cards(self) -> int:
        return self.page.locator("[data-testid='ynab-goal-card']").count()

    def goal_card(self, name: str):
        return self.page.locator(f"[data-testid='ynab-goal-card'][data-category='{name}']").first

    def set_goal_kind(self, name: str, value: str):
        self.goal_card(name).locator("select").select_option(value)

    def click_close(self):
        """The takeover's close button, in the title bar."""
        self.page.locator("[data-testid='takeover-close']").click()

    def leave_dialog_open(self) -> bool:
        return self.page.locator("[data-testid='ynab-leave-dialog'][open]").count() > 0

    def keep_going(self):
        self.page.locator("[data-testid='ynab-leave-cancel']").click()

    def leave_import(self):
        self.page.locator("[data-testid='ynab-leave-confirm']").click()

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
