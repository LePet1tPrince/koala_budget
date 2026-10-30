"""EncryptedTextField: secrets at rest are ciphertext; reads give the plaintext back."""

from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.test import TestCase, override_settings

from apps.plaid.models import PlaidItem
from apps.teams.models import Team
from apps.utils import fields


def raw_token(item):
    with connection.cursor() as cursor:
        cursor.execute("SELECT access_token FROM plaid_plaiditem WHERE id = %s", [item.pk])
        return cursor.fetchone()[0]


class EncryptedTextFieldTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.book = Team.objects.create(name="T", slug="t").default_book

    def make(self, token="access-production-abc"):
        return PlaidItem.objects.create(
            book=self.book, plaid_item_id=f"item-{token}", access_token=token, institution_name="Bank"
        )

    def test_stored_encrypted_and_read_back(self):
        item = self.make()
        stored = raw_token(item)
        self.assertTrue(stored.startswith(fields.PREFIX))
        self.assertNotIn("access-production-abc", stored)
        self.assertEqual(PlaidItem.objects.get(pk=item.pk).access_token, "access-production-abc")

    def test_resaving_does_not_encrypt_twice(self):
        item = self.make()
        item = PlaidItem.objects.get(pk=item.pk)
        item.save()
        self.assertEqual(PlaidItem.objects.get(pk=item.pk).access_token, "access-production-abc")

    def test_legacy_plaintext_still_reads(self):
        item = self.make()
        with connection.cursor() as cursor:
            cursor.execute("UPDATE plaid_plaiditem SET access_token = 'access-legacy' WHERE id = %s", [item.pk])
        self.assertEqual(PlaidItem.objects.get(pk=item.pk).access_token, "access-legacy")

    def test_keys_rotate(self):
        old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
        with override_settings(FIELD_ENCRYPTION_KEY=old):
            item = self.make()
        with override_settings(FIELD_ENCRYPTION_KEY=f"{new},{old}"):
            item = PlaidItem.objects.get(pk=item.pk)
            self.assertEqual(item.access_token, "access-production-abc")
            item.save()
        with override_settings(FIELD_ENCRYPTION_KEY=new):
            self.assertEqual(PlaidItem.objects.get(pk=item.pk).access_token, "access-production-abc")

    def test_a_wrong_key_fails_loudly(self):
        """Falling back to the ciphertext would send it to Plaid as if it were the token."""
        item = self.make()
        with (
            override_settings(FIELD_ENCRYPTION_KEY=Fernet.generate_key().decode()),
            self.assertRaises(ImproperlyConfigured),
        ):
            PlaidItem.objects.get(pk=item.pk)
