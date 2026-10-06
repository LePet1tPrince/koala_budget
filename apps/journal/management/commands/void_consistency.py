"""
Check (and optionally fix) that every bank row's void flag matches its entry.

The invariant `apps.journal.services.voiding` keeps: a bank transaction linked
to a journal entry is void exactly when the entry is. Bulk writes skip the
models' enforcement, so this is the way to look for drift.
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.bank_feed.models import BankTransaction
from apps.books.models import Book
from apps.journal.models import JournalEntry
from apps.journal.services.voiding import inconsistent_rows


class Command(BaseCommand):
    help = "Report bank transactions whose void state disagrees with their journal entry's; --fix brings them in line."

    def add_arguments(self, parser):
        parser.add_argument("--book", help="Book slug to check (default: every book)")
        parser.add_argument(
            "--fix",
            action="store_true",
            help="Set each row's flag from its entry (the entry is the truth for a linked row)",
        )

    def handle(self, *args, book=None, fix=False, **options):
        books = Book.objects.filter(slug=book) if book else None
        if book and not books.exists():
            raise CommandError(f"No book with slug {book!r}.")

        rows = inconsistent_rows()
        if books is not None:
            rows = rows.filter(book__in=books)
        bad = list(rows.values_list("pk", "book_id", "is_void", "journal_entry__status"))
        if not bad:
            self.stdout.write(self.style.SUCCESS("Every bank transaction agrees with its entry."))
            return

        for pk, book_id, is_void, status in bad:
            self.stdout.write(f"book {book_id}: bank transaction {pk} is_void={is_void}, entry status={status}")

        if not fix:
            raise CommandError(f"{len(bad)} bank transaction(s) out of step. Re-run with --fix to correct them.")

        now = timezone.now()
        ids = [pk for pk, *_ in bad]
        voided = BankTransaction.objects.filter(pk__in=ids, journal_entry__status=JournalEntry.STATUS_VOID).update(
            is_void=True, voided_at=now
        )
        restored = (
            BankTransaction.objects.filter(pk__in=ids)
            .exclude(journal_entry__status=JournalEntry.STATUS_VOID)
            .update(is_void=False, voided_at=None)
        )
        self.stdout.write(self.style.SUCCESS(f"Fixed: {voided} voided, {restored} restored."))
