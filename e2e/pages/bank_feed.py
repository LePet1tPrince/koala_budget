"""Page Object Model for the Bank Feed page (React-rendered)."""

from .base import BasePage


class BankFeedPage(BasePage):
    def path(self, team_slug: str) -> str:
        return f"/a/{team_slug}/bankfeed/"

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def goto(self, team_slug: str):
        """Navigate to the bank feed page and wait for the React app to mount."""
        console_msgs = []
        failed_urls = []
        self.page.on("console", lambda msg: console_msgs.append(f"[{msg.type}] {msg.text}"))
        self.page.on("requestfailed", lambda req: failed_urls.append(f"{req.failure} {req.url}"))

        self.page.goto(self.url(self.path(team_slug)))
        # Wait until at least one account card or the line-app container is visible
        try:
            self.page.wait_for_selector("#line-app", timeout=15_000)
        except Exception:
            print(f"\n[BankFeedPage] Page HTML snippet:\n{self.page.content()[:3000]}")
            print("\n[BankFeedPage] Console messages:\n" + "\n".join(console_msgs[-20:]))
            print("\n[BankFeedPage] Failed requests:\n" + "\n".join(failed_urls))
            raise

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_account_card_count(self) -> int:
        return self.page.locator("[data-testid^='account-card-']").count()

    def has_account_card(self, account_id: int) -> bool:
        return self.page.locator(f"[data-testid='account-card-{account_id}']").is_visible()

    def is_filter_visible(self) -> bool:
        return self.page.locator("[data-testid='quick-filters-btn']").is_visible()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def click_account_card(self, account_id: int):
        """Select an account card to load its bank feed."""
        self.page.locator(f"[data-testid='account-card-{account_id}']").click()
        # After clicking, the filter toggles and table should appear
        self.page.wait_for_selector("[data-testid='quick-filters-btn']", timeout=10_000)

    def click_add_transaction(self):
        """Click the add-transaction button to open the edit modal."""
        self.page.locator("[data-testid='add-transaction-btn']").click()
        self.page.wait_for_selector("[data-testid='edit-transaction-modal']", timeout=5_000)

    def close_modal(self):
        self.page.locator("[data-testid='modal-cancel-btn']").click()

    def click_filter(self, mode: str):
        """Click a filter toggle. mode is one of: to-review, reconciled, uncategorized, archived.

        "archived" is a standalone toggle button; the others live inside the
        "Quick Filters" dropdown menu and require opening it first.
        """
        if mode == "archived":
            self.page.locator("[data-testid='filter-archived']").click()
        else:
            self.page.locator("[data-testid='quick-filters-btn']").click()
            self.page.locator(f"[data-testid='filter-{mode}']").click()
            self.page.keyboard.press("Escape")
        self.page.wait_for_timeout(300)

    # ------------------------------------------------------------------
    # Table rows
    #
    # MaterialTable renders a plain <table>; these read it positionally rather
    # than by testid so the same assertions hold once the table is rewritten.
    # ------------------------------------------------------------------

    def wait_for_table(self):
        self.page.wait_for_selector("table tbody tr", timeout=10_000)

    def row_descriptions(self) -> list[str]:
        """Visible rows' description text, which the tests use as row identity."""
        self.page.wait_for_timeout(300)  # let the client-side filter settle
        rows = self.page.locator("table tbody tr")
        out = []
        for i in range(rows.count()):
            text = rows.nth(i).inner_text()
            if text.strip():
                out.append(text)
        return out

    def visible_row_count(self) -> int:
        return len(self.row_descriptions())

    def has_row_matching(self, needle: str) -> bool:
        return any(needle in text for text in self.row_descriptions())

    def open_quick_filters(self):
        self.page.locator("[data-testid='quick-filters-btn']").click()
        self.page.wait_for_selector("[data-testid='filter-to-review']", timeout=5_000)

    def close_quick_filters(self):
        self.page.keyboard.press("Escape")
        self.page.wait_for_timeout(200)

    def quick_filters_disabled(self) -> bool:
        return self.page.locator("[data-testid='quick-filters-btn']").is_disabled()

    # ------------------------------------------------------------------
    # Selection + batch action bar
    #
    # The bar carries no testids, so it is addressed the way a user sees it:
    # by the accessible name of each button. That keeps these assertions
    # valid across the MUI → daisyUI rewrite, which changes the markup but
    # not the labels.
    # ------------------------------------------------------------------

    def select_row(self, transaction_id: int):
        self.page.locator(f"[data-testid='feed-row-{transaction_id}'] input[type=checkbox]").check()
        self.page.wait_for_timeout(300)

    def deselect_row(self, transaction_id: int):
        self.page.locator(f"[data-testid='feed-row-{transaction_id}'] input[type=checkbox]").uncheck()
        self.page.wait_for_timeout(300)

    def select_all_rows(self):
        self.page.locator("[data-testid='select-all']").check()
        self.page.wait_for_timeout(300)

    def batch_button(self, name: str):
        """A button in the batch action bar, by its visible label."""
        return self.page.get_by_role("button", name=name, exact=True)

    def batch_buttons(self) -> list[str]:
        """Labels of every enabled-or-disabled button the bar is showing."""
        candidates = ["Bulk Edit", "Archive", "Unarchive", "Delete", "Reconcile", "Unreconcile", "Duplicate", "Export"]
        return [name for name in candidates if self.batch_button(name).count() and self.batch_button(name).is_visible()]

    def batch_bar_text(self) -> str:
        """The bar's summary strip — selection count and the In/Out/Net and reconciled figures."""
        return self.page.get_by_text("selected", exact=False).last.locator("xpath=ancestor::*[3]").inner_text()

    # ------------------------------------------------------------------
    # Transfer duplicate review
    # ------------------------------------------------------------------

    def transfer_review_button(self):
        return self.page.locator("[data-testid='transfer-review-button']")

    def open_transfer_review(self):
        self.transfer_review_button().click()
        self.page.get_by_text("Possible duplicate transfers").wait_for(timeout=5_000)

    def transfer_suggestion_count(self) -> int:
        return self.page.locator("[data-testid^='transfer-suggestion-']").count()

    def transfer_suggestion_containing(self, needle: str):
        """The one suggestion card whose text contains `needle`.

        Several pairs can share an account, so a button label alone is ambiguous
        across the modal — scope to the card first.
        """
        return self.page.locator("[data-testid^='transfer-suggestion-']").filter(has_text=needle).first

    def transfer_archive_button(self, account_name: str):
        return self.page.get_by_role("button", name=f"Duplicate — archive {account_name}", exact=True)

    def transfer_dismiss_button(self):
        return self.page.get_by_role("button", name="Not a duplicate", exact=True)
