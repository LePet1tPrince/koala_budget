"""
E2E tests for authentication flows.

Covers: login (valid/invalid), logout, and post-login redirect.
"""

import pytest
from playwright.sync_api import Page

from e2e.pages.auth import LoginPage


@pytest.mark.django_db(transaction=True)
def test_login_valid_credentials(page: Page, live_server, user, team):
    """User can log in with correct credentials and lands on the team home page."""
    login = LoginPage(page, live_server.url)
    login.goto()
    login.login(user.email, "testpass123")

    page.wait_for_url(f"**/a/{team.slug}/**", timeout=10_000)
    assert f"/a/{team.slug}/" in page.url


@pytest.mark.django_db(transaction=True)
def test_login_invalid_credentials(page: Page, live_server, user, team):
    """Wrong password shows an error and keeps the user on the login page."""
    login = LoginPage(page, live_server.url)
    login.goto()
    login.login(user.email, "wrongpassword")

    # allauth renders errors inside .errorlist
    page.wait_for_selector(".errorlist", timeout=5_000)
    assert login.is_showing_error()
    assert "/accounts/login/" in page.url


@pytest.mark.django_db(transaction=True)
def test_logout(authenticated_page: Page, live_server):
    """Logged-in user can log out and is redirected away from protected pages."""
    # allauth ACCOUNT_LOGOUT_ON_GET = True so GET /accounts/logout/ works directly
    authenticated_page.goto(f"{live_server.url}/accounts/logout/")
    # After logout the user should be back on the public home/landing page
    authenticated_page.wait_for_url(f"{live_server.url}/", timeout=10_000)
    assert authenticated_page.url == f"{live_server.url}/"
