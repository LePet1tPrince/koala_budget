"""Base Page Object with helpers shared by all pages."""

from playwright.sync_api import Page


class BasePage:
    def __init__(self, page: Page, base_url: str):
        self.page = page
        self.base_url = base_url.rstrip("/")

    def url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def goto(self, path: str, wait_for: str | None = None):
        self.page.goto(self.url(path), wait_until="domcontentloaded")
        if wait_for:
            try:
                self.page.wait_for_selector(wait_for, timeout=10_000)
            except Exception:
                # Emit diagnostic info so failures are easier to understand
                print(f"\n[BasePage.goto] URL after nav: {self.page.url}")
                print(f"[BasePage.goto] Page title: {self.page.title()}")
                print(f"[BasePage.goto] Waiting for: {wait_for}")
                print(f"[BasePage.goto] Page content (first 2000 chars):\n{self.page.content()[:2000]}")
                raise
