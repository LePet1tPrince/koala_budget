"""
Make every linked bank row's void flag equal its entry's status.

Before this, an entry stopped counting when it was void *or* when any bank row
linked to it was archived, and the two were set independently. Now there is one
state: an entry and its rows are void together. The fix, per entry:

1. a void row on a posted entry -> the entry is voided, and every row on it;
2. a void entry with a row that is not -> every row on it is voided.

Balance-neutral by construction: every entry touched already counted toward
nothing under the old rule. The migration checks that -- each account's balance
under the old rule before equals its balance under the new rule after -- and
aborts if not.
"""

from collections import defaultdict
from decimal import Decimal

from django.db import migrations
from django.db.models import Q, Sum
from django.utils import timezone

VOID = "void"


def _balances(JournalLine, excluded_entry_ids):
    sums = (
        JournalLine.objects.exclude(journal_entry_id__in=excluded_entry_ids)
        .values("account_id")
        .annotate(dr=Sum("dr_amount"), cr=Sum("cr_amount"))
    )
    out = defaultdict(Decimal)
    for row in sums:
        out[row["account_id"]] = (row["dr"] or Decimal("0")) - (row["cr"] or Decimal("0"))
    return {k: v for k, v in out.items() if v}


def forwards(apps, schema_editor):
    BankTransaction = apps.get_model("bank_feed", "BankTransaction")
    JournalEntry = apps.get_model("journal", "JournalEntry")
    JournalLine = apps.get_model("journal", "JournalLine")

    void_entry_ids = set(JournalEntry.objects.filter(status=VOID).values_list("id", flat=True))
    void_row_entry_ids = set(
        BankTransaction.objects.filter(is_void=True, journal_entry__isnull=False).values_list(
            "journal_entry_id", flat=True
        )
    )
    before = _balances(JournalLine, void_entry_ids | void_row_entry_ids)

    to_void = void_row_entry_ids - void_entry_ids
    now = timezone.now()
    entries = JournalEntry.objects.filter(id__in=to_void).update(status=VOID, updated_at=now)
    rows = (
        BankTransaction.objects.filter(journal_entry__status=VOID, is_void=False).update(
            is_void=True, voided_at=now, updated_at=now
        )
    )

    after = _balances(JournalLine, set(JournalEntry.objects.filter(status=VOID).values_list("id", flat=True)))
    if before != after:
        moved = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
        raise RuntimeError(f"Void consistency changed account balances (accounts {moved[:10]}); aborting.")

    reconciled = JournalLine.objects.filter(journal_entry_id__in=to_void, is_reconciled=True).count()
    if entries or rows:
        print(  # noqa: T201 - migration report
            f"\n  void consistency: {entries} entries voided, {rows} bank rows voided, "
            f"{reconciled} reconciled lines on newly voided entries (already excluded; no balance moved)"
        )

    stale = BankTransaction.objects.filter(
        Q(is_void=True) & ~Q(journal_entry__status=VOID), journal_entry__isnull=False
    ).count()
    if stale:
        raise RuntimeError(f"{stale} bank rows still disagree with their entry's status.")


class Migration(migrations.Migration):
    dependencies = [
        ("bank_feed", "0008_banktransaction_is_void"),
        ("journal", "0004_book_required"),
    ]

    # Reverse is a no-op: the statuses stay void, which the old rule also excluded.
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
