"""Base Page Object with helpers shared by all pages."""

from playwright.sync_api import Page


class BasePage:
    def __init__(self, page: Page, base_url: str):
        self.page = page
        self.base_url = base_url.rstrip("/")

    def url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def goto(self, path: str, wait_for: str | None = None):
        self.page.goto(self.url(path))
        if wait_for:
            self.page.wait_for_selector(wait_for, timeout=10_000)
