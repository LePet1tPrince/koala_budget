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
        return self.page.locator("h3.font-bold").first.inner_text().strip()

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

    def wait_for_suggestions(self):
        self.page.wait_for_selector("[data-testid='category-suggestions']", timeout=10_000)
