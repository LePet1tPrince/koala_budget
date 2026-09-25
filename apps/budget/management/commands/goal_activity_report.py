"""
List every journal line posted to a goal account, per set of books.

Goals now count those lines as spending (docs/goals-envelopes-plan.md §5): each
one lowers the goal's `left` and raises Unassigned by the same amount. Some may be
transfers to savings that were miscategorized to a goal; run this before and
after the release to review them.
"""

import csv

from django.core.management.base import BaseCommand

from apps.books.models import Book
from apps.budget.models import Goal
from apps.budget.services import GoalService


class Command(BaseCommand):
    help = "List every line on a goal account (date, amount, payee, counter account), per set of books."

    def add_arguments(self, parser):
        parser.add_argument("--team", help="Only this team's books (slug).")
        parser.add_argument("--csv", action="store_true", help="Write CSV to stdout instead of a readable listing.")

    def handle(self, *args, team=None, csv=False, **options):
        books = Book.objects.select_related("team").order_by("team__slug", "sort_order", "slug")
        if team:
            books = books.filter(team__slug=team)

        writer = None
        if csv:
            writer = _csv_writer(self.stdout)
            writer.writerow(["team", "book", "goal", "date", "amount", "payee", "counter_account", "memo", "entry_id"])

        total_lines = 0
        for book in books:
            service = GoalService(book)
            goals = Goal.objects.filter(book=book, account__isnull=False).order_by("name")
            book_rows = [(goal, line) for goal in goals for line in service.spending_lines(goal)]
            if not book_rows:
                continue
            total_lines += len(book_rows)
            if writer:
                for goal, line in book_rows:
                    writer.writerow(
                        [
                            book.team.slug,
                            book.slug,
                            goal.name,
                            line["date"].isoformat(),
                            f"{line['amount']:.2f}",
                            line["payee"],
                            line["counter"],
                            line["memo"],
                            line["entry_id"],
                        ]
                    )
                continue
            self.stdout.write(
                self.style.MIGRATE_HEADING(f"{book.team.name} › {book.name} ({book.team.slug}/{book.slug})")
            )
            for goal, line in book_rows:
                self.stdout.write(
                    f"  {goal.name:<24} {line['date'].isoformat()}  {line['amount']:>12.2f}  "
                    f"{line['payee'] or '-':<24} {line['counter'] or '-'}"
                )
        if not writer:
            self.stdout.write(f"{total_lines} line(s) on goal accounts.")


def _csv_writer(stream):
    return csv.writer(stream, lineterminator="\n")
