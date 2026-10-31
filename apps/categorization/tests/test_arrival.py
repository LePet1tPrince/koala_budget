"""Auto rules on arrival: a Plaid sync and a CSV upload. Plaid is mocked; it is never called."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from apps.audit.models import AuditEvent
from apps.bank_feed.models import BankTransaction
from apps.bank_feed.services.csv_upload import create_transactions
from apps.categorization.models import MODE_SUGGEST
from apps.plaid.models import PlaidAccount, PlaidItem
from apps.plaid.tasks import sync_plaid_transactions

from .base import RuleTestCase


class PlaidArrivalTest(RuleTestCase):
    def setUp(self):
        super().setUp()
        self.item = PlaidItem.objects.create(
            book=self.book, plaid_item_id="item-rules", access_token="token", institution_name="Bank", cursor="c0"
        )
        PlaidAccount.objects.create(
            book=self.book,
            item=self.item,
            account=self.chequing,
            plaid_account_id="acc-1",
            name="Chequing",
            subtype="checking",
            type="depository",
        )

    def tx(self, tx_id, name, amount="4.50", merchant=None):
        return {
            "transaction_id": tx_id,
            "account_id": "acc-1",
            "amount": Decimal(amount),
            "date": date(2026, 3, 4),
            "name": name,
            "merchant_name": merchant,
        }

    def sync(self, *added):
        page = {"added": list(added), "modified": [], "removed": [], "next_cursor": "c1", "has_more": False}
        with patch("apps.plaid.tasks.sync_transactions", side_effect=[page]):
            return sync_plaid_transactions(self.item.id)

    def test_an_auto_rule_files_new_rows(self):
        self.rule(name="Coffee shops")
        result = self.sync(self.tx("t1", "SQ *BLUE BOTTLE 4417"), self.tx("t2", "TIM HORTONS"))

        self.assertTrue(result["success"])
        coffee = BankTransaction.objects.get(plaid_transaction__plaid_transaction_id="t1")
        other = BankTransaction.objects.get(plaid_transaction__plaid_transaction_id="t2")
        self.assertEqual(self.category_of(coffee), self.coffee)
        self.assertIsNone(self.category_of(other))
        event = AuditEvent.objects.get(event_type=AuditEvent.AUTO_CATEGORIZED)
        self.assertEqual(event.metadata["trigger"], "plaid_sync")
        completed = AuditEvent.objects.get(event_type=AuditEvent.PLAID_SYNC_COMPLETED)
        self.assertEqual(completed.metadata["auto_categorized"], 1)

    def test_a_suggest_rule_leaves_new_rows_in_the_inbox(self):
        self.rule(mode=MODE_SUGGEST)
        self.sync(self.tx("t1", "SQ *BLUE BOTTLE 4417"))
        self.assertIsNone(self.category_of(BankTransaction.objects.get()))

    def test_a_refusal_never_fails_the_sync(self):
        self.rule()
        with patch("apps.categorization.apply.categorize_single", side_effect=ValueError("This period is locked.")):
            result = self.sync(self.tx("t1", "SQ *BLUE BOTTLE 4417"))
        self.assertTrue(result["success"])
        self.item.refresh_from_db()
        self.assertEqual(self.item.cursor, "c1")
        self.assertIsNone(self.category_of(BankTransaction.objects.get()))

    def test_even_an_unexpected_error_never_fails_the_sync(self):
        self.rule()
        with patch("apps.categorization.pipeline.auto_suggestions", side_effect=RuntimeError("boom")):
            result = self.sync(self.tx("t1", "SQ *BLUE BOTTLE 4417"))
        self.assertTrue(result["success"])
        self.assertEqual(BankTransaction.objects.count(), 1)


class CsvArrivalTest(RuleTestCase):
    def test_an_auto_rule_files_rows_the_wizard_left_uncategorized(self):
        self.rule()
        result = create_transactions(
            [
                {"date": date(2026, 3, 4), "description": "SQ *BLUE BOTTLE 4417", "amount": Decimal("4.50")},
                # The user mapped this one in the wizard: their choice stands.
                {
                    "date": date(2026, 3, 5),
                    "description": "SQ *BLUE BOTTLE 9920",
                    "amount": Decimal("5.50"),
                    "category_id": self.groceries.id,
                },
                {"date": date(2026, 3, 6), "description": "RENT", "amount": Decimal("900")},
            ],
            self.book,
            self.chequing.id,
        )
        self.assertEqual(result["created_count"], 3)
        self.assertEqual(result["rule_categorized_count"], 1)
        rows = {row.description: row for row in BankTransaction.objects.all()}
        self.assertEqual(self.category_of(rows["SQ *BLUE BOTTLE 4417"]), self.coffee)
        self.assertEqual(self.category_of(rows["SQ *BLUE BOTTLE 9920"]), self.groceries)
        self.assertIsNone(self.category_of(rows["RENT"]))

    def test_no_rules_no_change(self):
        result = create_transactions(
            [{"date": date(2026, 3, 4), "description": "SQ *BLUE BOTTLE", "amount": Decimal("4.50")}],
            self.book,
            self.chequing.id,
        )
        self.assertEqual(result["rule_categorized_count"], 0)
