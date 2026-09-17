"""
Remove the fabricated bank transactions that team bootstrap used to seed.

Until the sample-transaction seed was removed from ``apply_template``, every new
team was created with 18 months of invented ``BankTransaction`` rows. This command
cleans those up for teams created before that change.

It is deliberately a management command and not a data migration: these rows are
user-visible financial records, and deleting them should be a deliberate act with
a dry run available, not something a deploy does silently.

Only rows that are unmistakably seed data are eligible:

* ``source`` is ``system`` (what the seeder set),
* the row is not categorized (no ``journal_entry``) -- if the user categorized it,
  it is now part of their books and is left alone,
* the description matches one the seeder used.

Usage::

    python manage.py purge_sample_transactions              # dry run, prints counts
    python manage.py purge_sample_transactions --delete     # actually delete
    python manage.py purge_sample_transactions --team slug  # limit to one team
"""

from django.core.management.base import BaseCommand
from django.db.models import Count

from apps.bank_feed.models import BankTransaction
from apps.teams.models import Team

# The descriptions the old PERSONAL_BUDGET_TEMPLATE["sample_transactions"] used.
SEEDED_DESCRIPTIONS = ["Grocery Store", "Salary Pay", "Cell Phone"]


class Command(BaseCommand):
    help = "Delete bank transactions left behind by the old team-bootstrap sample data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--delete",
            action="store_true",
            help="Actually delete. Without this flag the command only reports what it would delete.",
        )
        parser.add_argument(
            "--team",
            dest="team_slug",
            help="Limit to a single team slug. Default: all teams.",
        )

    def handle(self, *args, **options):
        queryset = BankTransaction.objects.filter(
            source=BankTransaction.SOURCE_SYSTEM,
            journal_entry__isnull=True,
            description__in=SEEDED_DESCRIPTIONS,
        )

        if team_slug := options.get("team_slug"):
            try:
                team = Team.objects.get(slug=team_slug)
            except Team.DoesNotExist:
                self.stderr.write(self.style.ERROR(f"No team with slug {team_slug!r}."))
                return
            queryset = queryset.filter(team=team)

        per_team = queryset.values("team__slug").annotate(n=Count("id")).order_by("-n")
        total = sum(row["n"] for row in per_team)

        if not total:
            self.stdout.write("No seeded sample transactions found.")
            return

        for row in per_team:
            self.stdout.write(f"  {row['team__slug']}: {row['n']}")

        if not options["delete"]:
            self.stdout.write(
                self.style.WARNING(f"Would delete {total} transaction(s) across {len(per_team)} team(s).")
            )
            self.stdout.write("Re-run with --delete to apply.")
            return

        deleted, _ = queryset.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} row(s)."))
