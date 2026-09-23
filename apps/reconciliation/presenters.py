"""
What the reconciliation page and API are told, all in STATEMENT sign.

One place builds every payload, so the start form, the workspace, the tick
responses and the history list cannot disagree about a number or its sign.
"""

import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Prefetch
from django.urls import reverse

from apps.accounts.models import Account
from apps.bank_feed.models import BankTransaction
from apps.journal.models import JournalLine

from .models import Reconciliation
from .services import candidates, diagnose, integrity
from .services.session import last_completed
from .services.signs import account_type, is_liability, is_reconcilable, to_statement

#: The uncategorized callout lists this many rows; the count and total cover them all.
UNCATEGORIZED_SAMPLE = 20


def money(value) -> str:
    return f"{Decimal(value):.2f}"


def month_end(day: date) -> date:
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def default_statement_date(account, today=None) -> date:
    """Month-end after the last statement; with none, the end of last month."""
    latest = last_completed(account)
    if latest is not None:
        return month_end(month_end(latest.statement_date) + timedelta(days=1))
    today = today or date.today()
    return today.replace(day=1) - timedelta(days=1)


def account_payload(account) -> dict:
    return {
        "id": account.id,
        "name": account.name,
        "type": account_type(account),
        "is_liability": is_liability(account),
        "has_feed": account.has_feed,
    }


def _user_label(user):
    if user is None:
        return None
    return user.get_full_name() or user.get_username()


def statement_payload(rec, intact=None) -> dict:
    """The header of a statement, without its lines."""
    account = rec.account
    payload = {
        "id": rec.id,
        "status": rec.status,
        "statement_date": rec.statement_date.isoformat(),
        "statement_balance": money(to_statement(account, rec.statement_balance)),
        "adjustment_amount": money(to_statement(account, rec.adjustment_amount)),
        "completed_at": rec.completed_at.isoformat() if rec.completed_at else None,
        "completed_by": _user_label(rec.completed_by),
        "undone_at": rec.undone_at.isoformat() if rec.undone_at else None,
        "intact": intact,
        "url": reverse("reconciliation:statement", args=[account.team.slug, rec.id]),
    }
    if rec.cleared_total is not None:
        payload["cleared_total"] = money(to_statement(account, rec.cleared_total))
        payload["opening_balance"] = money(to_statement(account, rec.opening_balance or 0))
    return payload


def history_payload(account) -> list[dict]:
    recs = list(
        Reconciliation.objects.filter(account=account)
        .exclude(status=Reconciliation.STATUS_DRAFT)
        .select_related("account", "account__team", "completed_by")
    )
    intact = integrity.intact_map(recs)
    return [statement_payload(rec, intact.get(rec.id)) for rec in recs]


def _category_label(line) -> str:
    others = [other for other in line.journal_entry.lines.all() if other.id != line.id]
    if len(others) == 1:
        return others[0].account.name
    if len(others) > 1:
        return f"Split ({len(others)})"
    return ""


def _with_entry_lines(queryset):
    return queryset.prefetch_related(
        Prefetch("journal_entry__lines", queryset=JournalLine.objects.select_related("account"))
    )


def line_payload(account, line, *, ticked, feed_entry_ids, statement_date) -> dict:
    entry = line.journal_entry
    return {
        "id": line.id,
        "entry_id": entry.id,
        "date": entry.entry_date.isoformat(),
        "payee": entry.payee.name if entry.payee_id else "",
        "description": entry.description,
        "category": _category_label(line),
        "amount": money(candidates.line_statement_amount(account, line)),
        "ticked": ticked,
        "has_feed_row": entry.id in feed_entry_ids,
        "source": entry.source,
        "after_statement": entry.entry_date > statement_date,
    }


def _feed_entry_ids(account, entry_ids) -> set:
    return set(
        BankTransaction.objects.filter(account=account, journal_entry_id__in=entry_ids).values_list(
            "journal_entry_id", flat=True
        )
    )


def _uncategorized(rec) -> tuple[dict, list]:
    account = rec.account
    rows = list(candidates.uncategorized_rows(rec))
    amounts = [candidates.feed_row_statement_amount(account, row) for row in rows]
    sample = [
        {
            "id": row.id,
            "date": row.posted_date.isoformat(),
            "description": row.merchant_name or row.description,
            "amount": money(amount),
        }
        for row, amount in zip(rows[:UNCATEGORIZED_SAMPLE], amounts, strict=False)
    ]
    diag_rows = [
        diagnose.Row(id=row.id, date=row.posted_date, amount=amount, ticked=False, label=row.description)
        for row, amount in zip(rows, amounts, strict=True)
    ]
    payload = {
        "count": len(rows),
        "total": money(sum(amounts, Decimal("0"))),
        "rows": sample,
        "categorize_url": reverse("bank_feed:categorize_mode", args=[account.team.slug]) + f"?account={account.id}",
    }
    return payload, diag_rows


def _drift_payload(account) -> dict | None:
    found = integrity.drift(account)
    if found.amount == 0:
        return None
    return {
        "amount": money(to_statement(account, found.amount)),
        "since": found.since.statement_date.isoformat() if found.since else None,
        "lines": [
            {
                "id": line.id,
                "date": line.journal_entry.entry_date.isoformat(),
                "label": (line.journal_entry.payee.name if line.journal_entry.payee_id else "")
                or line.journal_entry.description,
                "amount": money(candidates.line_statement_amount(account, line)),
                "statement_date": line.reconciliation.statement_date.isoformat(),
                "reason": (
                    "undone"
                    if line.reconciliation.status == Reconciliation.STATUS_UNDONE
                    else ("voided" if line.journal_entry.status == "void" else "unreconciled")
                ),
            }
            for line in found.lines
        ],
    }


def draft_numbers(rec, *, include_later=False) -> dict:
    """Summary, hints and (optionally) lines for a draft -- what every tick response carries."""
    account = rec.account
    lines = list(_with_entry_lines(candidates.visible_lines(rec, include_later=include_later)))
    current = candidates.summary(rec)
    numbers = current.as_statement(account)
    uncategorized, uncategorized_rows = _uncategorized(rec)
    rows = [
        diagnose.Row(
            id=line.id,
            date=line.journal_entry.entry_date,
            amount=candidates.line_statement_amount(account, line),
            ticked=line.reconciliation_id == rec.id,
            label=(line.journal_entry.payee.name if line.journal_entry.payee_id else "")
            or line.journal_entry.description,
        )
        for line in lines
    ]
    hints = diagnose.diagnose(rows, numbers["difference"], rec.statement_date, uncategorized_rows)
    return {
        "summary": {key: (value if key == "ticked_count" else money(value)) for key, value in numbers.items()},
        "hints": [hint.as_dict() for hint in hints],
        "uncategorized": uncategorized,
        "lines": lines,
    }


def draft_payload(rec, *, include_later=False) -> dict:
    """Everything the workspace needs to render a draft."""
    account = rec.account
    numbers = draft_numbers(rec, include_later=include_later)
    lines = numbers.pop("lines")
    feed_ids = _feed_entry_ids(account, [line.journal_entry_id for line in lines])
    previous = last_completed(account)
    return {
        **statement_payload(rec),
        **numbers,
        "account": account_payload(account),
        "include_later": include_later,
        "lines": [
            line_payload(
                account,
                line,
                ticked=line.reconciliation_id == rec.id,
                feed_entry_ids=feed_ids,
                statement_date=rec.statement_date,
            )
            for line in lines
        ],
        "drift": _drift_payload(account),
        "previous": statement_payload(previous) if previous else None,
    }


def completed_payload(rec) -> dict:
    """A finished (or undone) statement and every line it locked."""
    account = rec.account
    lines = list(
        _with_entry_lines(
            rec.lines.select_related("journal_entry", "journal_entry__payee").order_by(
                "journal_entry__entry_date", "pk"
            )
        )
    )
    feed_ids = _feed_entry_ids(account, [line.journal_entry_id for line in lines])
    moved = {line.id for line in integrity.moved_lines(rec)} if rec.is_completed else set()
    payload = {
        **statement_payload(rec, integrity.is_intact(rec) if rec.is_completed else None),
        "account": account_payload(account),
        "lines": [
            {
                **line_payload(account, line, ticked=True, feed_entry_ids=feed_ids, statement_date=rec.statement_date),
                "moved": line.id in moved,
            }
            for line in lines
        ],
    }
    return payload


def accounts_payload(team) -> list[dict]:
    """Every reconcilable account with its balances, last statement and open draft."""
    accounts = [
        account
        for account in Account.objects.filter(team=team)
        .select_related("account_group")
        .with_balance()
        .with_reconciled_balance()
        .order_by("account_group__account_type", "account_group__sort_order", "sort_order", "name")
        if is_reconcilable(account)
    ]
    completed = {}
    for rec in Reconciliation.objects.filter(team=team, status=Reconciliation.STATUS_COMPLETED).order_by(
        "account_id", "-statement_date", "-id"
    ):
        completed.setdefault(rec.account_id, rec)
    intact = integrity.intact_map(list(completed.values()))
    drafts = {
        rec.account_id: rec
        for rec in Reconciliation.objects.filter(team=team, status=Reconciliation.STATUS_DRAFT).select_related(
            "account"
        )
    }
    result = []
    for account in accounts:
        last = completed.get(account.id)
        draft = drafts.get(account.id)
        if last is not None:
            last.account = account
        if draft is not None:
            draft.account = account
        result.append(
            {
                **account_payload(account),
                "balance": money(to_statement(account, account._balance)),
                "reconciled_balance": money(to_statement(account, account._reconciled_balance)),
                "last_statement": statement_payload(last, intact.get(last.id)) if last else None,
                "draft": statement_payload(draft) if draft else None,
                "url": reverse("reconciliation:account", args=[team.slug, account.id]),
            }
        )
    return result
