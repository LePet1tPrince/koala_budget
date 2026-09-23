"""Page Object Model for the export/import page (apps.portability)."""

from .base import BasePage


class PortabilityPage(BasePage):
    def path(self, team_slug: str) -> str:
        return f"/a/{team_slug}/data/"

    def goto_home(self, team_slug: str):
        self.goto(self.path(team_slug), wait_for="[data-testid='export-button']")

    def export_url(self, team_slug: str) -> str:
        return f"/a/{team_slug}/data/export/"

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------

    def start_import(self):
        self.page.locator("[data-testid='start-import-button']").click()
        # The file input is deliberately `.hidden` -- the visible control is the
        # dropzone button that clicks it -- so waiting for the *input* to become
        # visible would never succeed. Wait for the dropzone the user actually
        # sees, and address the input itself as merely attached.
        self.page.wait_for_selector("[data-testid='upload-dropzone']")
        self.page.wait_for_selector("[data-testid='upload-input']", state="attached")

    def upload_file(self, path: str):
        self.page.locator("[data-testid='upload-input']").set_input_files(path)
        self.page.wait_for_selector("[data-testid='confirm-step']", timeout=15_000)

    def confirm(self, team_name: str):
        self.page.locator("[data-testid='confirm-team-name-input']").fill(team_name)
        self.page.locator("[data-testid='confirm-apply-button']").click()

    def wait_for_done(self, timeout: int = 30_000):
        self.page.wait_for_selector("[data-testid='apply-done']", timeout=timeout)

    def result_counts_text(self) -> str:
        return self.page.locator("[data-testid='apply-result-counts']").inner_text()
