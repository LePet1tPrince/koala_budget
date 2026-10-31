"""
E2E tests for categorization rules (docs/categorization-rules-plan.md).

NOTE: Unrun when written (the E2E suite shares ports and a database with other
work in that environment). They need the Vite dev server like every React page:
`make start-bg`, then `make test-e2e ARGS="e2e/tests/test_categorization_rules.py"`.

Covers creating a rule on the rules page with its live preview, applying it to
the Inbox, reordering/disabling/deleting, and the "Always categorize
transactions like this" offer in categorize mode.
"""

import pytest
from playwright.sync_api import Page

from apps.bank_feed.models import BankTransaction
from apps.categorization.models import CategorizationRule
from e2e.factories import AccountFactory, AccountGroupFactory, AssetAccountFactory, feed_transaction
from e2e.pages.categorize import CategorizePage
from e2e.pages.rules import RuleEditor, RulesPage


@pytest.fixture
def rules_fixture(team):
    """One feed account, a findable category and three uncategorized rows (two alike)."""
    group = AccountGroupFactory(team=team)
    account = AssetAccountFactory(team=team, account_group=group, has_feed=True)
    expense_group = AccountGroupFactory(team=team)
    coffee = AccountFactory(team=team, account_group=expense_group, name="Zed Coffee")
    rows = [
        feed_transaction(team, account, description="SQ *BLUE BOTTLE 4417", merchant_name="Blue Bottle"),
        feed_transaction(team, account, description="SQ *BLUE BOTTLE 9920", merchant_name="Blue Bottle"),
        feed_transaction(team, account, description="TIM HORTONS 12", merchant_name="Tim Hortons"),
    ]
    return {"account": account, "coffee": coffee, "rows": rows}


def category_name(row):
    row.refresh_from_db()
    if row.journal_entry_id is None:
        return None
    lines = [line for line in row.journal_entry.lines.all() if line.account_id != row.account_id]
    return lines[0].account.name if len(lines) == 1 else None


@pytest.mark.django_db(transaction=True)
def test_a_rule_previews_and_categorizes_the_inbox(requires_vite, authenticated_page: Page, live_server, rules_fixture):
    page = RulesPage(authenticated_page, live_server.url)
    page.goto(rules_fixture["account"].book)

    editor = page.new_rule()
    editor.set_description("words", "blue bottle")
    editor.choose_category("Zed Coffee")
    editor.wait_for_preview("Matches 2")
    editor.save()

    assert page.rule_names() == ["blue bottle → Zed Coffee"]
    blue = rules_fixture["rows"][:2]
    assert [category_name(row) for row in blue] == ["Zed Coffee", "Zed Coffee"]
    assert category_name(rules_fixture["rows"][2]) is None


@pytest.mark.django_db(transaction=True)
def test_rules_reorder_disable_and_delete(requires_vite, authenticated_page: Page, live_server, rules_fixture):
    book = rules_fixture["account"].book
    for name in ("First", "Second"):
        CategorizationRule.objects.create(
            book=book, name=name, description_match="contains", description_value=name, category=rules_fixture["coffee"]
        )
    page = RulesPage(authenticated_page, live_server.url)
    page.goto(book)

    page.move_down("First")
    assert page.rule_names() == ["Second", "First"]
    assert list(CategorizationRule.objects.filter(book=book).in_order().values_list("name", flat=True)) == [
        "Second",
        "First",
    ]

    page.toggle("Second")
    authenticated_page.wait_for_timeout(300)
    assert not CategorizationRule.objects.get(book=book, name="Second").is_enabled

    page.delete("First")
    assert page.rule_names() == ["Second"]


@pytest.mark.django_db(transaction=True)
def test_test_and_apply_an_existing_rule(requires_vite, authenticated_page: Page, live_server, rules_fixture):
    book = rules_fixture["account"].book
    CategorizationRule.objects.create(
        book=book, name="Timmies", payee_match="equals", payee_value="Tim Hortons", category=rules_fixture["coffee"]
    )
    page = RulesPage(authenticated_page, live_server.url)
    page.goto(book)

    page.test_and_apply("Timmies")

    assert category_name(rules_fixture["rows"][2]) == "Zed Coffee"


@pytest.mark.django_db(transaction=True)
def test_categorize_mode_offers_a_rule_after_filing_a_card(
    requires_vite, authenticated_page: Page, live_server, rules_fixture
):
    categorize = CategorizePage(authenticated_page, live_server.url)
    categorize.goto(rules_fixture["account"].book)

    categorize.search("zed coffee")
    categorize.press("Enter")
    # The other "Blue Bottle" card makes the similar-transactions dialog ask first.
    just_this = authenticated_page.get_by_role("button", name="Just this one")
    if just_this.is_visible():
        just_this.click()

    authenticated_page.locator("[data-testid='rule-offer-create']").click()
    editor = RuleEditor(authenticated_page).wait()
    assert editor.field("rule-payee-value").input_value() == "Blue Bottle"
    editor.wait_for_preview("Matches 1")
    editor.save()

    authenticated_page.locator("[data-testid='rule-notice']").wait_for(timeout=10_000)
    rule = CategorizationRule.objects.get(book=rules_fixture["account"].book)
    assert rule.payee_value == "Blue Bottle"
    assert rule.mode == "auto"
    remaining = BankTransaction.objects.filter(book=rules_fixture["account"].book, journal_entry__isnull=True)
    assert [row.merchant_name for row in remaining] == ["Tim Hortons"]
