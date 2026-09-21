"""Page Object Model for Categorize Mode (React-rendered)."""

from .base import BasePage

# The row the keyboard highlight is on. `data-active` is the contract; the
# ring/tint classes that draw it are not.
ACTIVE_ROW = "[data-nav-key][data-active='true']"


class CategorizePage(BasePage):
    def path(self, team_slug: str) -> str:
        return f"/a/{team_slug}/bankfeed/categorize/"

    def goto(self, team_slug: str):
        """Navigate to categorize mode and wait for the first card to render."""
        self.page.goto(self.url(self.path(team_slug)))
        self.page.wait_for_selector("input[placeholder='Search accounts...']", timeout=15_000)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @property
    def search_box(self):
        return self.page.locator("input[placeholder='Search accounts...']")

    def current_card_title(self) -> str:
        """The payee on the card at the top of the stack (an editable field, not a heading)."""
        return self.payee_field.input_value().strip()

    @property
    def payee_field(self):
        return self.page.locator("[data-testid='categorize-payee']")

    @property
    def description_field(self):
        return self.page.locator("[data-testid='categorize-description']")

    def current_card_description(self) -> str:
        return self.description_field.input_value().strip()

    def details_are_dirty(self) -> bool:
        return self.page.locator("[data-testid='categorize-details-dirty']").count() > 0

    def active_row_name(self) -> str | None:
        """The name on the highlighted row, or None when nothing is highlighted."""
        row = self.page.locator(ACTIVE_ROW)
        if row.count() == 0:
            return None
        return row.first.inner_text().strip().splitlines()[0]

    def suggestion_notes(self) -> list[str]:
        """The 'N transactions with this payee...' line under each suggestion."""
        rows = self.page.locator("[data-testid='category-suggestion']")
        return [rows.nth(i).inner_text().strip().splitlines()[1] for i in range(rows.count())]

    def has_keyboard_hint(self) -> bool:
        return self.page.locator("kbd.kbd-xs", has_text="esc").is_visible()

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
        self.payee_field.fill(text)
        # The payee combobox opens its suggestion list on focus and closes on a
        # pointer press outside it — clicking the next field is how a user
        # leaves it. Escape would do it too, but Escape on an edited field
        # reverts the draft, which is the opposite of what a caller wants here.
        self.description_field.click()

    def edit_description(self, text: str):
        self.description_field.fill(text)

    def revert_details(self):
        self.page.locator("[data-testid='categorize-details-revert']").click()

    def wait_for_suggestions(self):
        self.page.wait_for_selector("[data-testid='category-suggestions']", timeout=10_000)
