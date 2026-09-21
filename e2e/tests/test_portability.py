"""
E2E: export a team, import it into a second team, and see the same net worth.

NOTE: requires the Vite dev server (`make start-bg`) alongside the Django
live server, same as the other React-mounted pages.

This is the plan's headline end-to-end check (docs/export-import-plan.md §7
Phase 5): a user's whole browser-driven path, not just the services
underneath it -- the real download, the real upload, the real confirmation
typing, the real polling screen.
"""

from decimal import Decimal

import pytest
from playwright.sync_api import Page

from apps.teams.helpers import create_default_team_for_user
from e2e.factories import AssetAccountFactory, IncomeAccountFactory, JournalEntryFactory, JournalLineFactory
from e2e.pages.portability import PortabilityPage


@pytest.fixture
def funded_team(team):
    """The `team` fixture's team, given one asset account and a deposit -- a nonzero, checkable net worth."""
    asset = AssetAccountFactory(team=team, name="E2E Chequing", has_feed=False)
    income = IncomeAccountFactory(team=team, name="E2E Paycheck")
    entry = JournalEntryFactory(team=team, description="Paycheck", status="posted")
    JournalLineFactory(team=team, journal_entry=entry, account=asset, dr_amount=Decimal("1234.56"))
    JournalLineFactory(team=team, journal_entry=entry, account=income, cr_amount=Decimal("1234.56"))
    return team


@pytest.mark.django_db(transaction=True)
def test_export_then_import_into_a_second_team_matches_net_worth(
    requires_vite, authenticated_page: Page, live_server, user, funded_team
):
    source_team = funded_team
    dest_team = create_default_team_for_user(user, team_name="E2E Destination")

    portability = PortabilityPage(authenticated_page, live_server.url)

    # Export the source team.
    portability.goto_home(source_team.slug)
    with authenticated_page.expect_download() as download_info:
        authenticated_page.locator("[data-testid='export-button']").click()
    download = download_info.value
    export_path = download.path()
    assert export_path, "the export did not produce a downloadable file"

    # Read the source team's net worth off its own dashboard before touching
    # the destination, so the comparison is against what was actually shown,
    # not just what the export claims.
    authenticated_page.goto(f"{live_server.url}/a/{source_team.slug}/")
    authenticated_page.wait_for_selector("[data-testid='metric-net-worth']")
    source_net_worth = authenticated_page.locator("[data-testid='metric-net-worth']").inner_text()

    # Import into the destination team.
    portability.goto_home(dest_team.slug)
    portability.start_import()
    portability.upload_file(str(export_path))
    portability.confirm(dest_team.name)
    portability.wait_for_done()

    counts_text = portability.result_counts_text()
    assert "1" in counts_text  # one account carried across (at minimum)

    authenticated_page.goto(f"{live_server.url}/a/{dest_team.slug}/")
    authenticated_page.wait_for_selector("[data-testid='metric-net-worth']")
    dest_net_worth = authenticated_page.locator("[data-testid='metric-net-worth']").inner_text()

    assert dest_net_worth == source_net_worth
