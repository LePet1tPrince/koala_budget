"""Page Object Model for Categorize Mode (React-rendered)."""

from .base import BasePage

# The row the keyboard highlight is on. `data-active` is the contract; the
# ring/tint classes that draw it are not.
ACTIVE_ROW = "[data-nav-key][data-active='true']"


class CategorizePage(BasePage):
    def path(self, book) -> str:
        return f"{book.base_url}bankfeed/categorize/"

    def goto(self, book, query: str = ""):
        """Navigate to categorize mode (optionally with a `?account=…&start=…&end=…` scope)
        and wait for the first card to render."""
        self.page.goto(self.url(self.path(book)) + query)
        self.page.wait_for_selector("[data-testid='categorize-search']", timeout=15_000)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @property
    def search_box(self):
        return self.page.locator("[data-testid='categorize-search']")

    def details_open(self) -> bool:
        return self.page.locator("[data-testid='categorize-details-editor']").count() > 0

    def open_details(self):
        """Open the payee/description editor on the top card (collapsed until asked for)."""
        if not self.details_open():
            self.page.locator("[data-testid='categorize-edit-details']").click()
            self.page.wait_for_selector("[data-testid='categorize-details-editor']")

    def current_card_title(self) -> str:
        """The payee on the card at the top of the stack: its field when the editor is open, else its heading."""
        if self.details_open():
            return self.payee_field.input_value().strip()
        return self.page.locator("[data-testid='categorize-card-payee']").inner_text().strip()

    @property
    def payee_field(self):
        return self.page.locator("[data-testid='categorize-payee']")

    @property
    def description_field(self):
        return self.page.locator("[data-testid='categorize-description']")

    def current_card_description(self) -> str:
        if self.details_open():
            return self.description_field.input_value().strip()
        return self.page.locator("[data-testid='categorize-card-description']").inner_text().strip()

    def details_are_dirty(self) -> bool:
        return self.page.locator("[data-testid='categorize-details-dirty']").count() > 0

    def active_row_name(self) -> str | None:
        """The name on the highlighted row, or None when nothing is highlighted."""
        row = self.page.locator(ACTIVE_ROW)
        if row.count() == 0:
            return None
        return row.first.inner_text().strip().splitlines()[0]

    def suggestion_notes(self) -> list[str]:
        """Why each suggestion chip is suggested ('N transactions with this payee...'), from its title."""
        rows = self.page.locator("[data-testid='category-suggestion']")
        return [rows.nth(i).get_attribute("title") for i in range(rows.count())]

    def remaining(self) -> int:
        """The queue length, from the "N remaining" line under the stack."""
        return int(self.page.locator("[data-testid='categorize-remaining']").inner_text().split()[0])

    @property
    def scope_account(self):
        return self.page.locator("[data-testid='categorize-scope-account']")

    def has_search_hint(self) -> bool:
        """The hints shown while searching (move/choose/clear) rather than the queue's keys."""
        return self.page.locator("[data-testid='categorize-key-hints']", has_text="choose").is_visible()

    def skip(self):
        self.page.locator("[data-testid='categorize-skip']").click()
        self.page.wait_for_timeout(400)

    def undo(self):
        self.page.locator("[data-testid='categorize-undo']").click()

    def chip_names(self) -> list[str]:
        """The shortcut chips (suggestions, then the most used categories), keys 1-9 in order."""
        chips = self.page.locator("[data-chip-index]")
        return [chips.nth(i).locator(".font-semibold").inner_text().strip() for i in range(chips.count())]

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def search(self, text: str):
        self.search_box.fill(text)
        self.page.wait_for_timeout(150)  # let the filtered list re-render

    def press(self, key: str):
        self.search_box.press(key)
        self.page.wait_for_timeout(150)

    def edit_payee(self, text: str):
        self.open_details()
        self.payee_field.fill(text)
        # The payee combobox opens its suggestion list on focus and closes on a
        # pointer press outside it — clicking the next field is how a user
        # leaves it. Escape would do it too, but Escape on an edited field
        # reverts the draft, which is the opposite of what a caller wants here.
        self.description_field.click()

    def edit_description(self, text: str):
        self.open_details()
        self.description_field.fill(text)

    def revert_details(self):
        self.page.locator("[data-testid='categorize-details-revert']").click()

    def listed_kinds(self) -> list[str]:
        """The kind of each category in the list below the suggestions, top to bottom, repeats collapsed."""
        self.page.wait_for_selector("[data-testid='category-row']", state="attached", timeout=10_000)
        kinds = self.page.locator("[data-testid='category-row']").evaluate_all("els => els.map(e => e.dataset.kind)")
        return [k for i, k in enumerate(kinds) if i == 0 or k != kinds[i - 1]]

    def listed_names(self) -> list[str]:
        rows = self.page.locator("[data-testid='category-row'] .font-medium")
        return [rows.nth(i).inner_text().strip() for i in range(rows.count())]

    def wait_for_suggestions(self):
        self.page.wait_for_selector("[data-testid='category-suggestions']", timeout=10_000)
