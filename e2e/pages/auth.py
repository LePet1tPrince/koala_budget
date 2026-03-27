"""Page Object Models for authentication pages."""

from .base import BasePage


class LoginPage(BasePage):
    PATH = "/accounts/login/"

    def goto(self):
        super().goto(self.PATH)

    def login(self, email: str, password: str):
        self.page.locator("[name='login']").fill(email)
        self.page.locator("[name='password']").fill(password)
        self.page.locator("[data-testid='login-btn']").click()

    def is_showing_error(self) -> bool:
        """Returns True if an authentication error message is visible."""
        return self.page.locator(".errorlist, [data-testid='login-error']").is_visible()

    def current_path(self) -> str:
        from urllib.parse import urlparse

        return urlparse(self.page.url).path
