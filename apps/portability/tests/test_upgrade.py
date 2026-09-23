"""
The format_version upgrade chain (§3.7, §7 Phase 1).

Version 2 added statements. A version-1 archive must still import -- without
statements, which it never carried -- and anything older than version 1 is
refused by name.
"""

from django.test import SimpleTestCase

from apps.portability.services import upgrade
from apps.portability.services.schema import FORMAT_VERSION, DocumentError


class UpgradeChainTests(SimpleTestCase):
    def test_current_version_is_a_no_op(self):
        tables = {"accounts": []}
        result = upgrade.upgrade_to_current(tables, from_version=FORMAT_VERSION)
        self.assertIs(result, tables)

    def test_version_zero_is_refused(self):
        with self.assertRaises(DocumentError) as ctx:
            upgrade.upgrade_to_current({}, from_version=0)
        self.assertIn("format version 0", str(ctx.exception))

    def test_chain_covers_every_version_since_1(self):
        # A reviewer's tripwire: bumping FORMAT_VERSION without a step here
        # would refuse every export made before the bump.
        self.assertEqual(sorted(upgrade.CHAIN), list(range(1, FORMAT_VERSION)))

    def test_v1_gains_an_empty_statement_table_and_unlinked_lines(self):
        tables = {"accounts": [], "journal_rows": [{"entry_id": 1}], "budget_rows": [], "reconciliations": []}
        result = upgrade.upgrade_to_current(tables, from_version=1)
        self.assertEqual(result["reconciliations"], [])
        self.assertIsNone(result["journal_rows"][0]["reconciliation_id"])
