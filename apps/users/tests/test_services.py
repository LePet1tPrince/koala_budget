import io
import zipfile

from django.test import TestCase

from apps.journal.models import JournalLine
from apps.portability.tests.db_fixtures import build_db_fixture_team
from apps.teams.models import Membership, Team
from apps.teams.roles import ROLE_ADMIN, ROLE_MEMBER
from apps.users.models import CustomUser
from apps.users.services import delete_user_account, export_user_data


class ExportUserDataTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team, cls.user, cls.handles = build_db_fixture_team("Export Me", "export-me")
        cls.book = cls.team.default_book

    def test_the_archive_holds_the_profile_and_every_book(self):
        archive = zipfile.ZipFile(io.BytesIO(export_user_data(self.user).getvalue()))
        names = set(archive.namelist())
        self.assertTrue({"profile.json", "teams.csv", "books.csv"} <= names)
        prefix = f"team_{self.team.slug}/{self.book.slug}"
        for table in ("accounts", "journal_entries", "journal_lines", "budgets", "goals", "goal_allocations"):
            self.assertIn(f"{prefix}/{table}.csv", names)
        lines = archive.read(f"{prefix}/journal_lines.csv").decode().strip().splitlines()
        self.assertEqual(len(lines) - 1, JournalLine.objects.filter(book=self.book).count())

    def test_another_teams_books_are_not_included(self):
        other, _user, _handles = build_db_fixture_team("Not Mine", "not-mine")
        archive = zipfile.ZipFile(io.BytesIO(export_user_data(self.user).getvalue()))
        self.assertFalse(any(name.startswith(f"team_{other.slug}/") for name in archive.namelist()))


class DeleteUserAccountTest(TestCase):
    def test_a_shared_team_survives_and_an_admin_is_promoted(self):
        team, user, _handles = build_db_fixture_team("Shared", "shared")
        other = CustomUser.objects.create_user(username="shared-member", password="pass")
        team.members.add(other, through_defaults={"role": ROLE_MEMBER})
        lines_before = JournalLine.objects.filter(book=team.default_book).count()

        delete_user_account(user)

        self.assertTrue(Team.objects.filter(pk=team.pk).exists())
        self.assertEqual(Membership.objects.get(team=team, user=other).role, ROLE_ADMIN)
        self.assertEqual(JournalLine.objects.filter(book=team.default_book).count(), lines_before)
