"""
Check each book's budget entries (apps.budget.ledger).

For every book: each budget entry is dated the first, posted, and made of bucket
lines balanced by exactly one Unassigned line; and `ledger_unassigned` (cumulative
bucket balances) agrees with `compute_unassigned` (the month-by-month walk of
availables) for every month from the book's first activity through this month.
`--fix` rebalances the Unassigned line of every budget entry of a book that fails,
then checks it again.
"""

from django.core.management.base import BaseCommand

from apps.books.models import Book
from apps.budget import ledger


class Command(BaseCommand):
    help = "Check (and with --fix, rebalance) each book's budget entries."

    def add_arguments(self, parser):
        parser.add_argument("--team", help="Only this team's books (slug).")
        parser.add_argument("--book", help="Only books with this slug.")
        parser.add_argument("--fix", action="store_true", help="Rebalance the budget entries of a book that fails.")

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
                ledger.rebalance_book(current)
                result = ledger.check_book(current)
            label = f"{current.team.slug}/{current.slug}"
            if result.ok:
                self.stdout.write(f"OK    {label}: {result.months_checked} months match")
                continue
            failed += 1
            self.stdout.write(self.style.ERROR(f"FAIL  {label}"))
            for month, problem in result.entry_problems:
                self.stdout.write(f"      {month:%Y-%m} entry: {problem}")
            for month, expected, actual in result.unassigned_mismatches:
                self.stdout.write(
                    f"      {month:%Y-%m} Unassigned: {expected.amount} "
                    f"(income due {expected.income_due}, envelopes {expected.envelopes}, goals {expected.goals}), "
                    f"by bucket balances {actual.amount} "
                    f"(income due {actual.income_due}, envelopes {actual.envelopes}, goals {actual.goals})"
                )
        if failed:
            self.stdout.write(self.style.ERROR(f"{failed} book(s) failed."))
        else:
            self.stdout.write(self.style.SUCCESS("Every book's budget entries check out."))
