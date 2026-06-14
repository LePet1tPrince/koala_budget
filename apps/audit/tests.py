"""
Tests for the audit app.
Covers the JournalEntry/JournalLine audit signals and the team-scoped audit API.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_EXPENSE, Account, AccountGroup, Payee
from apps.audit.models import AuditEvent, AuditLog
from apps.audit.utils import set_current_user
from apps.journal.models import JournalEntry, JournalLine
from apps.teams.context import current_team
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser


class AuditLogSignalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.user = CustomUser.objects.create_user(username="auditor", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

        cls.asset_group = AccountGroup.objects.create(
            team=cls.team, name="Bank Accounts", account_type=ACCOUNT_TYPE_ASSET
        )
        cls.expense_group = AccountGroup.objects.create(
            team=cls.team, name="Expenses", account_type=ACCOUNT_TYPE_EXPENSE
        )
        cls.bank_account = Account.objects.create(team=cls.team, name="Checking", account_group=cls.asset_group)
        cls.groceries = Account.objects.create(team=cls.team, name="Groceries", account_group=cls.expense_group)
        cls.dining = Account.objects.create(team=cls.team, name="Dining Out", account_group=cls.expense_group)
        cls.payee = Payee.objects.create(team=cls.team, name="Test Store")

    def setUp(self):
        # Signals attribute records to the thread-local user; reset between tests.
        set_current_user(None)

    def tearDown(self):
        set_current_user(None)

    def test_journal_entry_create_logs_audit(self):
        entry = JournalEntry.objects.create(team=self.team, entry_date=date(2025, 12, 17), description="Test entry")
        logs = AuditLog.objects.filter(journal_entry_id=entry.pk, source_model="JournalEntry")
        self.assertEqual(logs.count(), 1)
        log = logs.first()
        self.assertEqual(log.action, AuditLog.ACTION_CREATE)
        self.assertEqual(log.changes["snapshot"]["description"], "Test entry")

    def test_journal_entry_update_logs_diff(self):
        entry = JournalEntry.objects.create(team=self.team, entry_date=date(2025, 12, 17), description="Original")
        entry.description = "Updated"
        entry.save()

        update_log = AuditLog.objects.filter(
            journal_entry_id=entry.pk, source_model="JournalEntry", action=AuditLog.ACTION_UPDATE
        ).first()
        self.assertIsNotNone(update_log)
        self.assertEqual(update_log.changes["description"]["before"], "Original")
        self.assertEqual(update_log.changes["description"]["after"], "Updated")

    def test_journal_entry_update_without_change_logs_nothing(self):
        entry = JournalEntry.objects.create(team=self.team, entry_date=date(2025, 12, 17), description="Same")
        AuditLog.objects.filter(journal_entry_id=entry.pk).delete()
        entry.save()  # no field changed
        self.assertEqual(AuditLog.objects.filter(journal_entry_id=entry.pk).count(), 0)

    def test_journal_entry_delete_logs_audit(self):
        entry = JournalEntry.objects.create(team=self.team, entry_date=date(2025, 12, 17), description="To delete")
        entry_pk = entry.pk
        entry.delete()
        delete_log = AuditLog.objects.filter(
            journal_entry_id=entry_pk, source_model="JournalEntry", action=AuditLog.ACTION_DELETE
        ).first()
        self.assertIsNotNone(delete_log)
        self.assertEqual(delete_log.changes["snapshot"]["description"], "To delete")

    def test_journal_line_category_change_frozen_snapshot(self):
        entry = JournalEntry.objects.create(team=self.team, entry_date=date(2025, 12, 17), description="Expense")
        line = JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.groceries, cr_amount=Decimal("50.00")
        )

        # Re-categorize the line, then rename the *old* account.
        line.account = self.dining
        line.save()
        self.groceries.name = "RENAMED Groceries"
        self.groceries.save()

        update_log = AuditLog.objects.filter(
            source_model="JournalLine", action=AuditLog.ACTION_UPDATE, object_id=line.pk
        ).first()
        self.assertIsNotNone(update_log)
        # The frozen snapshot must preserve the account name at the time of the change.
        self.assertEqual(update_log.changes["account"]["before"]["name"], "Groceries")
        self.assertEqual(update_log.changes["account"]["after"]["name"], "Dining Out")

    def test_signal_attributes_user(self):
        set_current_user(self.user)
        entry = JournalEntry.objects.create(team=self.team, entry_date=date(2025, 12, 17), description="Attributed")
        log = AuditLog.objects.filter(journal_entry_id=entry.pk).first()
        self.assertEqual(log.user, self.user)


class AuditEventAPITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Team One", slug="team-one")
        cls.user = CustomUser.objects.create_user(username="member1", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

        cls.other_team = Team.objects.create(name="Team Two", slug="team-two")
        cls.other_user = CustomUser.objects.create_user(username="member2", password="testpass123")
        cls.other_team.members.add(cls.other_user, through_defaults={"role": ROLE_ADMIN})

        cls.event = AuditEvent.objects.create(team=cls.team, user=cls.user, event_type=AuditEvent.BULK_EDIT)
        cls.other_event = AuditEvent.objects.create(
            team=cls.other_team, user=cls.other_user, event_type=AuditEvent.BULK_DELETE
        )

    def setUp(self):
        set_current_user(None)
        self.client = APIClient()

    def test_team_isolation(self):
        self.client.force_authenticate(user=self.user)
        with current_team(self.team):
            response = self.client.get(f"/a/{self.team.slug}/audit/api/events/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = {row["id"] for row in response.data["results"]}
        self.assertIn(self.event.id, returned_ids)
        self.assertNotIn(self.other_event.id, returned_ids)

    def test_event_type_filter(self):
        AuditEvent.objects.create(team=self.team, user=self.user, event_type=AuditEvent.BULK_ARCHIVE)
        self.client.force_authenticate(user=self.user)
        with current_team(self.team):
            response = self.client.get(f"/a/{self.team.slug}/audit/api/events/", {"event_type": AuditEvent.BULK_EDIT})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        event_types = {row["event_type"] for row in response.data["results"]}
        self.assertEqual(event_types, {AuditEvent.BULK_EDIT})

    def test_non_member_cannot_access(self):
        self.client.force_authenticate(user=self.other_user)
        with current_team(self.team):
            response = self.client.get(f"/a/{self.team.slug}/audit/api/events/")
        self.assertIn(response.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))


class JournalEntryAuditEndpointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Audit Team", slug="audit-team")
        cls.user = CustomUser.objects.create_user(username="je-auditor", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})
        cls.asset_group = AccountGroup.objects.create(
            team=cls.team, name="Bank Accounts", account_type=ACCOUNT_TYPE_ASSET
        )
        cls.bank_account = Account.objects.create(team=cls.team, name="Checking", account_group=cls.asset_group)

    def setUp(self):
        # Clear any thread-local user leaked from a prior test (audit signals read it).
        set_current_user(None)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_audit_endpoint_returns_history(self):
        with current_team(self.team):
            entry = JournalEntry.objects.create(team=self.team, entry_date=date(2025, 12, 17), description="Original")
            entry.description = "Updated"
            entry.save()

            response = self.client.get(f"/a/{self.team.slug}/journal/api/journal-entries/{entry.id}/audit/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        actions = [row["action"] for row in response.data]
        self.assertIn(AuditLog.ACTION_CREATE, actions)
        self.assertIn(AuditLog.ACTION_UPDATE, actions)
