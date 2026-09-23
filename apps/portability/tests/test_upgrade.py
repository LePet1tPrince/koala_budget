"""
The (currently empty) format_version upgrade chain (§3.7, §7 Phase 1).

There is nothing to upgrade *from* yet -- format_version 1 is the only
version that has ever existed. What matters today is that the chain is
honest about that: it refuses rather than pretending, and the refusal names
the version it could not read.
"""

from django.test import SimpleTestCase

from apps.portability.services import upgrade
from apps.portability.services.schema import FORMAT_VERSION, DocumentError


class UpgradeChainTests(SimpleTestCase):
    def test_current_version_is_a_no_op(self):
        tables = {"accounts": []}
        result = upgrade.upgrade_to_current(tables, from_version=FORMAT_VERSION)
        self.assertIs(result, tables)

    def test_older_version_raises_since_the_chain_is_empty(self):
        with self.assertRaises(DocumentError) as ctx:
            upgrade.upgrade_to_current({}, from_version=0)
        self.assertIn("format version 0", str(ctx.exception))

    def test_chain_is_empty_at_v1(self):
        # A reviewer's tripwire: the day this stops being true, it should be
        # because a v2 shipped and added an entry on purpose, not by accident.
        self.assertEqual(upgrade.CHAIN, {})
