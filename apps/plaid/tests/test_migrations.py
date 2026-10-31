"""plaid.0009 encrypts existing access tokens, and its reverse restores the plaintext."""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [("plaid", "0008_plaiditem_status")]
AFTER = [("plaid", "0009_encrypt_access_token")]


class EncryptTokensMigrationTest(TransactionTestCase):
    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())

    def raw(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT access_token FROM plaid_plaiditem")
            return [row[0] for row in cursor.fetchall()]

    def test_forward_and_back(self):
        old = self.migrate(BEFORE)
        Team = old.get_model("teams", "Team")
        Book = old.get_model("books", "Book")
        PlaidItem = old.get_model("plaid", "PlaidItem")
        team = Team.objects.create(name="T", slug="t")
        book = Book.objects.create(team=team, name="Personal", slug="personal")
        PlaidItem.objects.create(book=book, plaid_item_id="i", access_token="access-plain", institution_name="B")

        self.migrate(AFTER)
        (stored,) = self.raw()
        self.assertTrue(stored.startswith("fernet:"))

        self.migrate(BEFORE)
        self.assertEqual(self.raw(), ["access-plain"])
