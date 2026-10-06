"""
The Inbox table as one queryset: filter, count, sort and page bank rows on the server.

The Inbox used to fetch every row of an account and filter, count, sort and page
them in the browser. Across every account that is the whole book on every visit,
so the table is now a window onto one `BankTransaction` queryset and the client
asks for one page at a time (plan: `docs/unified-bank-feed-plan.md` §2.1).

`FeedParams.parse()` is the one place a request's query string is read; the list,
`selection/` and `locate/` endpoints all build their queryset through `filtered()`
and `ordered()` here, so a row is on page 3 of the list exactly when `locate/`
says it is, and "select all matching" selects exactly the rows the list counted.

The filter semantics are the ones the client applied before (`LineTable.jsx`),
so moving them here changes no row's membership:

- **view**: `active` rows are not void, `voided` rows are.
- **to_review / reconciled**: whether the row's own account line is reconciled.
  Mutually exclusive, as the menu makes them.
- **uncategorized**: no journal entry. A split has an entry, so it is categorized.
- **transfers**: the row is one leg of a possible duplicate transfer.
"""

from dataclasses import dataclass
from datetime import date

from django.db.models import (
    Case,
    CharField,
    Count,
    DecimalField,
    Exists,
    F,
    OuterRef,
    Q,
    Subquery,
    Value,
    When,
)
from django.db.models.functions import Coalesce, Lower
from django.utils.dateparse import parse_date
from rest_framework.exceptions import ValidationError

from apps.journal.models import JournalLine
from apps.reconciliation.models import Reconciliation

from ..models import BankTransaction

#: Page sizes the Inbox offers. A request for any other is refused, not clamped:
#: a page that silently came back a different size would page wrongly.
PAGE_SIZES = (10, 25, 50, 100, 200)
#: Categorize Mode reads this endpoint without a page size; it gets what it always got.
DEFAULT_PAGE_SIZE = 200
#: Most rows one request may name or select: each write is a per-row save with its
#: audit signals, so this bounds a request's time.
MAX_IDS = 1000

VIEW_ACTIVE = "active"
VIEW_VOIDED = "voided"

SORT_KEYS = ("date", "account", "payee", "category", "inflow", "outflow", "description")
SPLIT_SORT_LABEL = "Split"


@dataclass(frozen=True)
class FeedParams:
    """What one Inbox request asks for, parsed and checked."""

    accounts: tuple = ()  # empty = every feed account
    view: str | None = None  # None = both (the old client filtered for itself)
    to_review: bool = False
    reconciled: bool = False
    uncategorized: bool = False
    transfers: bool = False
    start_date: date | None = None
    end_date: date | None = None
    sort: str | None = None
    descending: bool = False
    ids: tuple = ()
    page_size: int = DEFAULT_PAGE_SIZE

    @classmethod
    def parse(cls, params):
        """Read a request's query params. Raises DRF `ValidationError` (a 400) on nonsense."""
        errors = {}

        def flag(name):
            return params.get(name) in ("1", "true")

        def int_list(name):
            raw = (params.get(name) or "").strip()
            if not raw:
                return ()
            try:
                return tuple(int(part) for part in raw.split(",") if part.strip())
            except ValueError:
                errors[name] = f"{name} must be a comma-separated list of ids."
                return ()

        def a_date(name):
            raw = params.get(name)
            if not raw:
                return None
            parsed = parse_date(raw)
            if parsed is None:
                errors[name] = f"{name} must be a date (YYYY-MM-DD)."
            return parsed

        view = params.get("view") or None
        if view not in (None, VIEW_ACTIVE, VIEW_VOIDED):
            errors["view"] = f"view must be '{VIEW_ACTIVE}' or '{VIEW_VOIDED}'."

        to_review, reconciled = flag("to_review"), flag("reconciled")
        if to_review and reconciled:
            errors["reconciled"] = "to_review and reconciled cannot both be set."

        sort = params.get("sort") or None
        if sort is not None and sort not in SORT_KEYS:
            errors["sort"] = f"sort must be one of: {', '.join(SORT_KEYS)}."
        direction = params.get("dir") or "asc"
        if direction not in ("asc", "desc"):
            errors["dir"] = "dir must be 'asc' or 'desc'."

        page_size = DEFAULT_PAGE_SIZE
        if params.get("page_size"):
            try:
                page_size = int(params["page_size"])
            except ValueError:
                page_size = None
            if page_size not in PAGE_SIZES:
                errors["page_size"] = f"page_size must be one of: {', '.join(map(str, PAGE_SIZES))}."

        accounts = int_list("account")
        ids = int_list("ids")
        if len(ids) > MAX_IDS:
            errors["ids"] = f"At most {MAX_IDS} ids."

        parsed = cls(
            accounts=accounts,
            view=view,
            to_review=to_review,
            reconciled=reconciled,
            uncategorized=flag("uncategorized"),
            transfers=flag("transfers"),
            start_date=a_date("start_date"),
            end_date=a_date("end_date"),
            sort=sort,
            descending=direction == "desc",
            ids=ids,
            page_size=page_size or DEFAULT_PAGE_SIZE,
        )
        if errors:
            raise ValidationError(errors)
        return parsed


# --- annotations ----------------------------------------------------------


def _own_line(**extra):
    """The row's own account line on its entry (the line the bank reported)."""
    return JournalLine.objects.filter(
        journal_entry_id=OuterRef("journal_entry_id"), account_id=OuterRef("account_id"), **extra
    )


def with_reconciled(queryset):
    """`row_reconciled`: the row's own account line is reconciled (what the lock icon shows)."""
    return queryset.annotate(row_reconciled=Exists(_own_line(is_reconciled=True)))


def _line_count():
    return Subquery(
        JournalLine.objects.filter(journal_entry_id=OuterRef("journal_entry_id"))
        .order_by()
        .values("journal_entry_id")
        .annotate(n=Count("id"))
        .values("n")[:1]
    )


def _other_line_account_name():
    return Subquery(
        JournalLine.objects.filter(journal_entry_id=OuterRef("journal_entry_id"))
        .exclude(account_id=OuterRef("account_id"))
        .order_by("pk")
        .values("account__name")[:1]
    )


def _primary_account_name():
    """A split mirror's category reads as the split's own account (its primary row's)."""
    return Subquery(
        BankTransaction.objects.filter(journal_entry_id=OuterRef("journal_entry_id"), is_transfer_mirror=False)
        .order_by("pk")
        .values("account__name")[:1]
    )


def _category_sort():
    """The category cell as text, for sorting: matches what `bank_transaction_to_feed_row` shows."""
    return Lower(
        Case(
            When(journal_entry__isnull=True, then=Value("")),
            When(Q(is_transfer_mirror=True) & Q(_lines__gt=2), then=Coalesce(_primary_account_name(), Value(""))),
            When(_lines__gt=2, then=Value(SPLIT_SORT_LABEL)),
            default=Coalesce(_other_line_account_name(), Value("")),
            output_field=CharField(),
        )
    )


_MONEY = DecimalField(max_digits=12, decimal_places=2)

SORT_EXPRESSIONS = {
    "date": lambda: [F("posted_date")],
    "account": lambda: [
        F("account__account_group__account_type"),
        F("account__account_group__sort_order"),
        F("account__sort_order"),
        F("account__name"),
    ],
    "payee": lambda: [Lower(Coalesce("merchant_name", Value(""), output_field=CharField()))],
    "category": lambda: [F("_category_sort")],
    "inflow": lambda: [Case(When(amount__lt=0, then=-F("amount")), default=Value(0), output_field=_MONEY)],
    "outflow": lambda: [Case(When(amount__gt=0, then=F("amount")), default=Value(0), output_field=_MONEY)],
    "description": lambda: [Lower("description")],
}

#: The list's default order, and the tie-break under every explicit sort: newest
#: first, then the row id, so no row lands on two pages.
DEFAULT_ORDER = ("-posted_date", "-created_at", "-pk")


# --- the queryset ---------------------------------------------------------


def base_rows(book, params):
    """
    The rows the request's accounts cover, before any view or quick filter.

    With no account named, every account on a feed: an account hidden from the
    Inbox (`has_feed=False`) keeps its rows, but they are not in the Inbox.
    """
    rows = BankTransaction.objects.filter(book=book)
    if params.accounts:
        return rows.filter(account_id__in=params.accounts)
    return rows.filter(account__has_feed=True)


def filtered(book, params, *, transfer_ids=None):
    """
    `base_rows` narrowed by the view, quick filters, dates and ids.

    `transfer_ids` is the set of row ids in a possible-transfer pair; computed
    by the caller only when `params.transfers` is set (it is a book-wide pass).
    """
    rows = with_reconciled(base_rows(book, params))
    if params.view == VIEW_ACTIVE:
        rows = rows.filter(is_void=False)
    elif params.view == VIEW_VOIDED:
        rows = rows.filter(is_void=True)
    if params.to_review:
        rows = rows.filter(row_reconciled=False)
    elif params.reconciled:
        rows = rows.filter(row_reconciled=True)
    if params.uncategorized:
        rows = rows.filter(journal_entry__isnull=True)
        if params.view is None:
            # Categorize Mode's request: the same set the Inbox badge counts.
            rows = rows.filter(is_void=False)
    if params.transfers:
        rows = rows.filter(pk__in=transfer_ids or ())
    if params.start_date:
        rows = rows.filter(posted_date__gte=params.start_date)
    if params.end_date:
        rows = rows.filter(posted_date__lte=params.end_date)
    if params.ids:
        rows = rows.filter(pk__in=params.ids)
    return rows


def ordered(rows, params):
    """Apply the requested sort, always ending on the default order's tie-break."""
    if params.sort is None:
        return rows.order_by(*DEFAULT_ORDER)
    if params.sort == "category":
        rows = rows.annotate(_lines=_line_count()).annotate(_category_sort=_category_sort())
    keys = [
        expr.desc(nulls_last=True) if params.descending else expr.asc(nulls_first=True)
        for expr in SORT_EXPRESSIONS[params.sort]()
    ]
    return rows.order_by(*keys, *DEFAULT_ORDER)


def order_expressions(params):
    """The ordering as expressions, for a window function (`locate`)."""
    from django.db.models.expressions import OrderBy

    tail = [OrderBy(F(name), descending=True) for name in ("posted_date", "created_at", "pk")]
    if params.sort is None:
        return tail
    head = [
        expr.desc(nulls_last=True) if params.descending else expr.asc(nulls_first=True)
        for expr in SORT_EXPRESSIONS[params.sort]()
    ]
    return [*head, *tail]


def counts(book, params):
    """
    The menu badges for the request's accounts, whatever else is filtered.

    Exactly what the client counted before: To review / Reconciled split the rows
    that are not void, Uncategorized counts non-void rows with no entry, Voided
    counts void rows. One aggregate query.
    """
    rows = with_reconciled(base_rows(book, params))
    active = Q(is_void=False)
    return rows.aggregate(
        to_review=Count("pk", filter=active & Q(row_reconciled=False)),
        reconciled=Count("pk", filter=active & Q(row_reconciled=True)),
        uncategorized=Count("pk", filter=active & Q(journal_entry__isnull=True)),
        voided=Count("pk", filter=Q(is_void=True)),
    )


def transfer_candidate_ids(book):
    """Ids of every row in a possible duplicate-transfer pair (the detector's book-wide pass)."""
    from .transfer_detection import find_transfer_candidates

    ids = set()
    for pair in find_transfer_candidates(book):
        ids.add(pair["outflow"].pk)
        ids.add(pair["inflow"].pk)
    return ids


# --- selection summaries --------------------------------------------------


def selection_rows(rows):
    """
    Every matching row as the batch bar reads it, without building feed rows.

    What `BatchActionBar` needs to decide which actions apply and to total the
    selection: no serializer, no prefetch, one query.
    """
    category = Subquery(
        JournalLine.objects.filter(journal_entry_id=OuterRef("journal_entry_id"))
        .exclude(account_id=OuterRef("account_id"))
        .order_by("pk")
        .values("account_id")[:1]
    )
    statement_date = Subquery(
        _own_line(is_reconciled=True, reconciliation__status=Reconciliation.STATUS_COMPLETED)
        .order_by("pk")
        .values("reconciliation__statement_date")[:1]
    )
    annotated = rows.annotate(_lines=_line_count(), _category_id=category, _statement_date=statement_date).values(
        "pk",
        "account_id",
        "amount",
        "is_void",
        "is_transfer_mirror",
        "journal_entry_id",
        "row_reconciled",
        "_lines",
        "_category_id",
        "_statement_date",
    )
    out = []
    for row in annotated:
        amount = row["amount"]
        split = (row["_lines"] or 0) > 2 and not row["is_transfer_mirror"]
        out.append(
            {
                "id": row["pk"],
                "account": {"id": row["account_id"]},
                "inflow": str(-amount if amount < 0 else 0),
                "outflow": str(amount if amount > 0 else 0),
                "is_void": row["is_void"],
                "is_reconciled": row["row_reconciled"],
                "is_transfer_mirror": row["is_transfer_mirror"],
                "is_split": split,
                "journal_entry_id": row["journal_entry_id"],
                # A split has no single category; the bar reads null as "not categorized"
                # exactly as it did when it read the full row.
                "category": {"id": row["_category_id"]} if row["journal_entry_id"] and not split else None,
                "reconciled_statement_date": row["_statement_date"],
            }
        )
    return out
