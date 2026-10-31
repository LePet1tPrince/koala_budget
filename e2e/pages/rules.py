"""Page Object Model for categorization rules: the rules page and the shared rule editor."""

from .base import BasePage


class RuleEditor:
    """The `RuleEditorModal` dialog, wherever it was opened from."""

    def __init__(self, page):
        self.page = page
        self.root = page.locator("[data-testid='rule-editor']")

    def wait(self):
        self.root.wait_for(state="visible", timeout=10_000)
        return self

    def field(self, testid):
        return self.root.locator(f"[data-testid='{testid}']")

    def set_description(self, kind: str, value: str):
        self.field("rule-description-match").select_option(kind)
        self.field("rule-description-value").fill(value)

    def set_payee(self, kind: str, value: str):
        self.field("rule-payee-match").select_option(kind)
        self.field("rule-payee-value").fill(value)

    def choose_category(self, name: str):
        combo = self.field("rule-category")
        combo.locator("input").fill(name)
        self.page.locator("[role='option']", has_text=name).first.click()

    def suggest_only(self):
        self.field("rule-mode-suggest").check()

    def preview_count_text(self) -> str:
        locator = self.field("rule-preview-count")
        locator.wait_for(state="visible", timeout=10_000)
        return locator.inner_text()

    def wait_for_preview(self, text: str):
        self.root.locator("[data-testid='rule-preview-count']", has_text=text).wait_for(timeout=10_000)

    def save(self):
        self.field("rule-save").click()
        self.root.wait_for(state="hidden", timeout=10_000)


class RulesPage(BasePage):
    def path(self, book) -> str:
        return f"{book.base_url}bankfeed/rules/"

    def goto(self, book):
        super().goto(self.path(book), wait_for="[data-testid='rules-page']")
        self.page.wait_for_selector("[data-testid='rules-list'], [data-testid='rules-empty']", timeout=10_000)

    def new_rule(self) -> RuleEditor:
        self.page.locator("[data-testid='rule-new']").click()
        return RuleEditor(self.page).wait()

    def rule_names(self) -> list[str]:
        return [
            n.strip() for n in self.page.locator("[data-testid='rule-row'] [data-testid='rule-name']").all_inner_texts()
        ]

    def row(self, name: str):
        return self.page.locator(
            "[data-testid='rule-row']", has=self.page.locator("[data-testid='rule-name']", has_text=name)
        )

    def move_down(self, name: str):
        self.row(name).locator("[data-testid='rule-move-down']").click()
        self.page.wait_for_timeout(300)

    def toggle(self, name: str):
        self.row(name).locator("[data-testid='rule-enabled']").click()

    def test_and_apply(self, name: str):
        self.row(name).locator("[data-testid='rule-test']").click()
        dialog = self.page.locator("[data-testid='rule-test-dialog']")
        dialog.locator("[data-testid='rule-test-result']").wait_for(timeout=10_000)
        dialog.locator("[data-testid='rule-apply']").click()
        self.page.locator("[data-testid='rules-toast']").wait_for(timeout=10_000)

    def delete(self, name: str):
        self.row(name).locator("[data-testid='rule-delete']").click()
        self.page.locator("[data-testid='rule-delete-confirm']").click()
        self.row(name).wait_for(state="detached", timeout=10_000)
