"""
Check that each book's budget entries mirror its budget rows (apps.budget.ledger).

For every book: each month's budget entry against the month's `Budget` and
`GoalAllocation` rows, and `ledger_unassigned` (Unassigned read off the budget
buckets) against `compute_unassigned` (read off the rows) for every month from
the book's first activity through this month. `--fix` rebuilds every budget entry
of a book that fails, then checks it again.
"""

from django.core.management.base import BaseCommand

from apps.books.models import Book
from apps.budget import ledger


class Command(BaseCommand):
    help = "Check (and with --fix, rebuild) the budget entries that mirror each book's budget."

    def add_arguments(self, parser):
        parser.add_argument("--team", help="Only this team's books (slug).")
        parser.add_argument("--book", help="Only books with this slug.")
        parser.add_argument("--fix", action="store_true", help="Rebuild the budget entries of a book that fails.")

    def handle(self, *args, team=None, book=None, fix=False, **options):
        books = Book.objects.select_related("team").order_by("team__slug", "slug")
        if team:
            books = books.filter(team__slug=team)
        if book:
            books = books.filter(slug=book)

        failed = 0
        for current in books:
            result = ledger.check_book(current)
            if not result.ok and fix:
                ledger.sync_book(current)
                result = ledger.check_book(current)
            label = f"{current.team.slug}/{current.slug}"
            if result.ok:
                self.stdout.write(f"OK    {label}: {result.months_checked} months match")
                continue
            failed += 1
            self.stdout.write(self.style.ERROR(f"FAIL  {label}"))
            for month, claims, posted in result.bucket_mismatches:
                self.stdout.write(f"      {month:%Y-%m} entry: rows say {_fmt(claims)}, ledger has {_fmt(posted)}")
            for month, expected, actual in result.unassigned_mismatches:
                self.stdout.write(
                    f"      {month:%Y-%m} Unassigned: rows {expected.amount} "
                    f"(income due {expected.income_due}, envelopes {expected.envelopes}, goals {expected.goals}), "
                    f"ledger {actual.amount} "
                    f"(income due {actual.income_due}, envelopes {actual.envelopes}, goals {actual.goals})"
                )
        if failed:
            self.stdout.write(self.style.ERROR(f"{failed} book(s) failed."))
        else:
            self.stdout.write(self.style.SUCCESS("Every book's budget entries match its budget."))


def _fmt(amounts):
    return "{" + ", ".join(f"{k}: {v}" for k, v in sorted(amounts.items())) + "}"
