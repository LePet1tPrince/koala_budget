"""
Column sorting, filtering and facet values for the Transactions list.

The transactions table filters and sorts server-side against the whole ledger
-- the client only ever holds the pages it has scrolled through, so filtering
the loaded rows would silently hide everything below the fold.  That means the
column definitions have to live in one place: the list endpoint orders and
filters by them, and the facets endpoint reads the same fields to build each
column's list of unique values.

A displayed column is not always a model field.  The debit account, the credit
account and the amount are all derived from the entry's two lines, so each gets
a scalar subquery annotation that reproduces exactly what
``TransactionRowSerializer`` shows -- including the $0.00 entry, where both
lines carry ``dr_amount == cr_amount == 0`` and the debit/credit split falls
back to line order.
"""

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.db.models import Count, DecimalField, IntegerField, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils.dateparse import parse_date

from .models import JournalEntry, JournalLine

# The two lines of an entry, ordered so that the first is the one the
# serializer reports as the debit (resp. credit) side.  ``pk`` breaks the tie
# in opposite directions so a $0.00 entry -- where every amount is zero --
# still resolves to two different lines.
_DEBIT_LINE = JournalLine.objects.filter(journal_entry=OuterRef("pk")).order_by("-dr_amount", "pk")
_CREDIT_LINE = JournalLine.objects.filter(journal_entry=OuterRef("pk")).order_by("dr_amount", "-pk")

# Number of lines on the entry, as a scalar subquery rather than a
# ``Count("lines")`` aggregate: an aggregate forces a GROUP BY on the whole
# query, which the facet counts then have to group *again*.
_LINE_COUNT = (
    JournalLine.objects.filter(journal_entry=OuterRef("pk")).order_by().values("journal_entry").annotate(n=Count("pk"))
)

#: Annotations every transaction query needs, keyed by annotation name.
TRANSACTION_ANNOTATIONS = {
    "line_count": Subquery(_LINE_COUNT.values("n"), output_field=IntegerField()),
    "payee_name": Coalesce("payee__name", Value("")),
    "debit_account_name": Coalesce(
        Subquery(_DEBIT_LINE.values("account__name")[:1]),
        Value(""),
    ),
    "credit_account_name": Coalesce(
        Subquery(_CREDIT_LINE.values("account__name")[:1]),
        Value(""),
    ),
    "amount_value": Coalesce(
        Subquery(_DEBIT_LINE.values("dr_amount")[:1], output_field=DecimalField(max_digits=15, decimal_places=2)),
        Value(Decimal("0")),
        output_field=DecimalField(max_digits=15, decimal_places=2),
    ),
}


def _parse_decimal(raw: str):
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError, TypeError):
        return None


@dataclass(frozen=True)
class Column:
    """One filterable/sortable column of the transactions table."""

    key: str
    #: ORM field or annotation the column reads.
    field: str
    #: Wire kind, so the client knows how to render a facet value.
    kind: str = "text"
    #: Turns a query-param string into the value the ORM filters on.  Returning
    #: ``None`` drops the value rather than erroring -- a stale bookmark with a
    #: since-deleted payee should show an unfiltered column, not a 400.
    parse: Callable[[str], object] | None = None
    #: ``value`` -> display label, for columns whose stored value is a code.
    labels: dict | None = None
    #: Facet values are listed newest/largest first where that reads better.
    facet_descending: bool = False

    def to_wire(self, value) -> str:
        """Serialize a DB value into the string the client sends back as a filter."""
        return "" if value is None else str(value)

    def label_for(self, wire_value: str) -> str:
        if self.labels is not None:
            return self.labels.get(wire_value, wire_value)
        return wire_value


COLUMNS: dict[str, Column] = {
    "date": Column(key="date", field="entry_date", kind="date", parse=parse_date, facet_descending=True),
    "payee": Column(key="payee", field="payee_name"),
    "description": Column(key="description", field="description"),
    "debit_account": Column(key="debit_account", field="debit_account_name"),
    "credit_account": Column(key="credit_account", field="credit_account_name"),
    "amount": Column(key="amount", field="amount_value", kind="money", parse=_parse_decimal, facet_descending=True),
    "source": Column(key="source", field="source", kind="choice", labels=dict(JournalEntry.SOURCE_CHOICES)),
    "status": Column(key="status", field="status", kind="choice", labels=dict(JournalEntry.STATUS_CHOICES)),
}

#: Prefix of the per-column filter query params, e.g. ``?f_payee=Amazon``.
FILTER_PARAM_PREFIX = "f_"

#: Ledgers can hold more distinct descriptions than anyone will scroll; the
#: facet list caps out and says so, and the search box narrows server-side.
FACET_LIMIT = 500


def apply_column_filters(queryset, params, *, exclude: str | None = None):
    """
    Narrow ``queryset`` by every column filter in ``params``.

    ``exclude`` skips one column's own filter, which is what the facets
    endpoint needs: a column's value list has to keep showing the values the
    user has *not* ticked, or unticking one would be impossible.
    """
    for key, column in COLUMNS.items():
        if key == exclude:
            continue
        raw_values = params.getlist(f"{FILTER_PARAM_PREFIX}{key}")
        if not raw_values:
            continue
        if column.parse is None:
            values = raw_values
        else:
            values = [parsed for parsed in (column.parse(v) for v in raw_values) if parsed is not None]
        if not values:
            # Every selected value was unparseable; filtering on an empty set
            # would blank the table, so treat it as no filter at all.
            continue
        queryset = queryset.filter(**{f"{column.field}__in": values})
    return queryset


def apply_ordering(queryset, params):
    """
    Order by the requested column, falling back to the default newest-first.

    ``pk`` always breaks the tie: without it, rows sharing a sort value can
    shuffle between pages and the infinite scroll shows a row twice.
    """
    sort = (params.get("sort") or "").strip()
    direction = (params.get("dir") or "asc").strip().lower()
    column = COLUMNS.get(sort)
    if column is None:
        return queryset.order_by("-entry_date", "-created_at", "-pk")
    prefix = "-" if direction == "desc" else ""
    return queryset.order_by(f"{prefix}{column.field}", "-entry_date", "-pk")


def facet_values(queryset, column: Column, *, query: str = "") -> dict:
    """
    The distinct values of ``column`` across ``queryset``, with row counts.

    ``queryset`` is expected to already carry ``TRANSACTION_ANNOTATIONS`` and
    every *other* column's filter, so the counts describe what ticking a value
    would actually show.
    """
    rows = queryset
    if query:
        rows = rows.filter(**{f"{column.field}__icontains": query})

    order = f"{'-' if column.facet_descending else ''}{column.field}"
    grouped = rows.order_by().values(column.field).annotate(count=Count("pk", distinct=True)).order_by(order)

    values = []
    for row in grouped[: FACET_LIMIT + 1]:
        wire = column.to_wire(row[column.field])
        values.append({"value": wire, "label": column.label_for(wire), "count": row["count"]})

    truncated = len(values) > FACET_LIMIT
    return {"column": column.key, "values": values[:FACET_LIMIT], "truncated": truncated}
