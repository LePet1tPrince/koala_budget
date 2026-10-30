"""Currency: nothing converts, so an account in another currency is flagged."""

from datetime import date
from decimal import Decimal

from django.test import override_settings

from apps.bank_feed.models import BankTransaction
from apps.bank_feed.serializers import bank_transaction_to_feed_row
from apps.plaid.models import PlaidTransaction, is_foreign_currency
from apps.plaid.services import account_currency

from .base import PlaidBookTestCase


class CurrencyTest(PlaidBookTestCase):
    def _row(self, code):
        bank_tx = BankTransaction.objects.create(
            book=self.book,
            account=self.checking,
            amount=Decimal("20.00"),
            posted_date=date(2026, 10, 1),
            description="Amazon.com",
            source=BankTransaction.SOURCE_PLAID,
        )
        PlaidTransaction.objects.create(
            book=self.book,
            plaid_transaction_id=f"tx-{code}",
            bank_transaction=bank_tx,
            plaid_account=self.plaid_checking,
            iso_currency_code=code,
        )
        return bank_transaction_to_feed_row(BankTransaction.objects.get(pk=bank_tx.pk))

    @override_settings(BASE_CURRENCY="CAD")
    def test_home_currency_is_not_flagged(self):
        row = self._row("CAD")
        self.assertEqual(row["currency"], "CAD")
        self.assertFalse(row["is_foreign_currency"])

    @override_settings(BASE_CURRENCY="CAD")
    def test_other_currency_is_flagged(self):
        row = self._row("USD")
        self.assertEqual(row["currency"], "USD")
        self.assertTrue(row["is_foreign_currency"])

    def test_unknown_currency_is_not_flagged(self):
        self.assertFalse(is_foreign_currency(None))
        self.assertFalse(is_foreign_currency(""))

    def test_account_currency_reads_the_balances(self):
        self.assertEqual(account_currency({"balances": {"iso_currency_code": "USD"}}), "USD")
        self.assertEqual(
            account_currency({"balances": {"iso_currency_code": None, "unofficial_currency_code": "BTC"}}), "BTC"
        )
        self.assertIsNone(account_currency({"balances": None}))
        self.assertIsNone(account_currency({}))
