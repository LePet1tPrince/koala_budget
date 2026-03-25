"""
Shared pytest fixtures for E2E tests.

Key fixtures:
- user / team: isolated Django ORM objects (transactional_db for live_server compatibility)
- authenticated_page: Playwright Page already logged in as the test user
- team_page: alias for authenticated_page, used in tests that need a full team context
"""

import pytest
from django.contrib.auth import get_user_model
from playwright.sync_api import Page

from apps.teams.helpers import create_default_team_for_user

User = get_user_model()

# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------
# live_server requires transaction=True so the server thread can see committed
# data. All DB fixtures therefore depend on transactional_db, not db.


@pytest.fixture
def user(transactional_db):
    """A regular user with a known password."""
    return User.objects.create_user(
        username="e2e@example.com",
        email="e2e@example.com",
        password="testpass123",
    )


@pytest.fixture
def team(user):
    """A team with the test user as admin."""
    return create_default_team_for_user(user)


# ---------------------------------------------------------------------------
# Page fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def authenticated_page(page: Page, live_server, user, team) -> Page:
    """
    Returns a Playwright Page that is already logged in as the test user
    and has landed on the team home page.
    """
    page.goto(f"{live_server.url}/accounts/login/")
    page.locator("[name='login']").fill(user.email)
    page.locator("[name='password']").fill("testpass123")
    page.locator("[type='submit']").click()
    # Home view redirects authenticated users to /a/<team_slug>/
    page.wait_for_url(f"**/a/{team.slug}/**", timeout=10_000)
    return page


@pytest.fixture
def team_page(authenticated_page: Page) -> Page:
    """Alias used by tests that operate in the context of a team workspace."""
    return authenticated_page
