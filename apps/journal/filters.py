"""
Column sorting, filtering and facet values for the Transactions list.

The transactions table filters and sorts server-side against the whole ledger
-- the client only ever holds the pages it has scrolled through, so filtering
the loaded rows would silently hide everything below the fold.  That means the
column definitions have to live in one place: the list endpoint orders and
filters by them, and the facets endpoint reads the same fields to build each
column's list of selectable values.

A displayed column is not always a model field.  The debit account, the credit
account and the amount are all derived from the entry's two lines, so each gets
a scalar subquery annotation that reproduces exactly what
``TransactionRowSerializer`` shows -- including the $0.00 entry, where both
lines carry ``dr_amount == cr_amount == 0`` and the debit/credit split falls
back to line order.  A column's annotations are applied only when that column
is sorted, filtered or faceted, so an unfiltered list pays for none of them.

Three columns are **hierarchical**: dates nest year -> month -> day, and the
two account columns nest account type -> account group -> account.  Ticking a
branch has to mean "everything under it" rather than expanding to a list of
leaves, or selecting three years would put a thousand values in the query
string.  So a branch is its own filter value -- ``2025``, ``2025-03``,
``t:income``, ``g:12`` -- and the column's value strategy turns it back into
the right ``Q``.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db.models import Count, DecimalField, IntegerField, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils.dateparse import parse_date

from apps.accounts.models import ACCOUNT_TYPE_CHOICES, Account

from .models import JournalEntry, JournalLine

# The two lines of an entry, ordered so that the first is the one the
# serializer reports as the debit (resp. credit) side.  ``pk`` breaks the tie
# in opposite directions so a $0.00 entry -- where every amount is zero --
# still resolves to two different lines.
#
# Known limitation, deliberate: for a **split** -- an entry with several lines
# on one side -- these resolve to the largest leg, so sorting by an account
# column sorts a split by its biggest leg and filtering by an account matches a
# split only when that account *is* its biggest leg.  A $50.40 household leg on
# a $160.00-groceries split will not match a "Household Goods" filter.
#
# This is not an oversight.  Matching any line on the side means an ``Exists``
# subquery per selected value, and the facet counts then stop summing to the row
# count -- one split would be counted under several accounts, so the numbers in
# the column menu would no longer describe what ticking a value shows.  That is
# a bigger change than the one that made splits visible at all, and strictly
# better than the previous behaviour, where a split appeared under no filter
# because it was not in the list.
_DEBIT_LINE = JournalLine.objects.filter(journal_entry=OuterRef("pk")).order_by("-dr_amount", "pk")
_CREDIT_LINE = JournalLine.objects.filter(journal_entry=OuterRef("pk")).order_by("dr_amount", "-pk")

# Number of lines on the entry, as a scalar subquery rather than a
# ``Count("lines")`` aggregate: an aggregate forces a GROUP BY on the whole
# query, which the facet counts then have to group *again*.
_LINE_COUNT = (
    JournalLine.objects.filter(journal_entry=OuterRef("pk")).order_by().values("journal_entry").annotate(n=Count("pk"))
)

#: Annotations every transaction query needs, whatever is being filtered.
BASE_ANNOTATIONS = {"line_count": Subquery(_LINE_COUNT.values("n"), output_field=IntegerField())}

#: Prefix of the per-column filter query params, e.g. ``?f_payee=Amazon``.
FILTER_PARAM_PREFIX = "f_"

#: Ledgers can hold more distinct descriptions than anyone will scroll; a flat
#: facet list caps out and says so, and the search box narrows server-side.
FACET_LIMIT = 500

_ACCOUNT_TYPE_LABELS = dict(ACCOUNT_TYPE_CHOICES)


def _parse_decimal(raw: str):
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError, TypeError):
        return None


def _node(value, label, count, *, full=None, children=None) -> dict:
    """One selectable value, as the client's filter menu reads it."""
    node = {"value": value, "label": label, "count": count}
    if full is not None and full != label:
        # What the applied-filter chip says, when the tree label only makes
        # sense under its parent ("Mar" -> "Mar 2025").
        node["full"] = full
    if children is not None:
        node["children"] = children
    return node


# ---------------------------------------------------------------------------
# Value strategies
# ---------------------------------------------------------------------------
# Each column has one.  It owns both halves of a column's behaviour: turning
# the selected values back into a queryset filter, and listing what there is to
# select.  Keeping the two together is what stops a new value form being
# offered by the menu that the filter then doesn't understand.


class FlatValues:
    """The default: a column's values are the stored values, listed flat."""

    hierarchical = False

    def annotations(self, column) -> dict:
        return dict(column.annotations)

    def filter_q(self, column, raw_values, team):
        if column.parse is None:
            values = list(raw_values)
        else:
            values = [parsed for parsed in (column.parse(v) for v in raw_values) if parsed is not None]
        if not values:
            # Every selected value was unparseable; filtering on an empty set
            # would blank the table, so treat it as no filter at all.
            return None
        return Q(**{f"{column.field}__in": values})

    def facets(self, column, queryset, query, team) -> dict:
        rows = queryset
        if query:
            rows = rows.filter(**{f"{column.field}__icontains": query})

        order = f"{'-' if column.facet_descending else ''}{column.field}"
        grouped = rows.order_by().values(column.field).annotate(count=Count("pk", distinct=True)).order_by(order)

        values = []
        for row in grouped[: FACET_LIMIT + 1]:
            raw = row[column.field]
            wire = "" if raw is None else str(raw)
            values.append(_node(wire, column.label_for(wire), row["count"]))

        return {"values": values[:FACET_LIMIT], "truncated": len(values) > FACET_LIMIT}


class DateTree:
    """
    Year -> month -> day, where a year or a month is itself a filter value.

    Entry dates are the one column where the natural grouping is obvious and
    the flat list is longest: a two-year ledger has ~500 distinct dates, which
    is a scroll, while it has two years.
    """

    hierarchical = True

    YEAR = re.compile(r"^\d{4}$")
    MONTH = re.compile(r"^(\d{4})-(\d{2})$")
    MONTH_NAMES = [
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ]

    def annotations(self, column) -> dict:
        return dict(column.annotations)

    def filter_q(self, column, raw_values, team):
        combined = Q()
        for raw in raw_values:
            if self.YEAR.match(raw):
                combined |= Q(**{f"{column.field}__year": int(raw)})
            elif month := self.MONTH.match(raw):
                combined |= Q(
                    **{
                        f"{column.field}__year": int(month.group(1)),
                        f"{column.field}__month": int(month.group(2)),
                    }
                )
            elif exact := parse_date(raw):
                combined |= Q(**{column.field: exact})
        return combined or None

    def facets(self, column, queryset, query, team) -> dict:
        grouped = queryset.order_by().values(column.field).annotate(count=Count("pk", distinct=True))

        years: dict[int, dict] = {}
        for row in grouped:
            day = row[column.field]
            if day is None:
                continue
            iso = day.isoformat()
            if query and query.lower() not in iso:
                continue
            year = years.setdefault(day.year, {"count": 0, "months": {}})
            month = year["months"].setdefault(day.month, {"count": 0, "days": []})
            year["count"] += row["count"]
            month["count"] += row["count"]
            month["days"].append((day, row["count"]))

        # Newest first at every level, matching the table's default order.
        values = []
        for year_number in sorted(years, reverse=True):
            year = years[year_number]
            months = []
            for month_number in sorted(year["months"], reverse=True):
                month = year["months"][month_number]
                name = self.MONTH_NAMES[month_number - 1]
                days = [
                    _node(day.isoformat(), str(day.day), count, full=day.isoformat())
                    for day, count in sorted(month["days"], key=lambda pair: pair[0], reverse=True)
                ]
                months.append(
                    _node(
                        f"{year_number:04d}-{month_number:02d}",
                        name,
                        month["count"],
                        full=f"{name} {year_number}",
                        children=days,
                    )
                )
            values.append(_node(str(year_number), str(year_number), year["count"], children=months))

        return {"values": values, "truncated": False}


class AccountTree:
    """
    Account type -> account group -> account, for the debit/credit columns.

    The shape comes from the chart of accounts rather than from the
    transactions, so only the per-account counts need the ledger query -- one
    grouped column instead of four.  Accounts come back in ``Account``'s own
    ordering, which is the drag-and-drop board order, so the menu matches the
    order the user arranged their accounts in.
    """

    hierarchical = True

    TYPE_ORDER = [value for value, _ in ACCOUNT_TYPE_CHOICES]

    def __init__(self, id_field, line):
        self.id_field = id_field
        self.line = line

    def annotations(self, column) -> dict:
        return {**column.annotations, self.id_field: Subquery(self.line.values("account_id")[:1])}

    def filter_q(self, column, raw_values, team):
        account_ids, group_ids, types = [], [], []
        for raw in raw_values:
            prefix, _, rest = raw.partition(":")
            # partition on the FIRST colon only -- an account may be named
            # "Rent: main flat" and must survive the round trip.
            if prefix == "a" and rest.isdigit():
                account_ids.append(int(rest))
            elif prefix == "g" and rest.isdigit():
                group_ids.append(int(rest))
            elif prefix == "t" and rest in _ACCOUNT_TYPE_LABELS:
                types.append(rest)

        scoped = Account.objects.filter(team=team)
        combined = Q()
        if account_ids:
            combined |= Q(**{f"{self.id_field}__in": account_ids})
        if group_ids:
            combined |= Q(**{f"{self.id_field}__in": scoped.filter(account_group_id__in=group_ids).values("pk")})
        if types:
            combined |= Q(**{f"{self.id_field}__in": scoped.filter(account_group__account_type__in=types).values("pk")})
        return combined or None

    def facets(self, column, queryset, query, team) -> dict:
        counts = dict(
            queryset.order_by().values_list(self.id_field).annotate(count=Count("pk", distinct=True)).order_by()
        )
        counts.pop(None, None)
        if not counts:
            return {"values": [], "truncated": False}

        accounts = (
            Account.objects.filter(team=team, pk__in=list(counts))
            .select_related("account_group")
            .order_by(*Account._meta.ordering)
        )

        types: dict[str, dict] = {}
        for account in accounts:
            if query and query.lower() not in account.name.lower():
                continue
            group = account.account_group
            bucket = types.setdefault(group.account_type, {"count": 0, "groups": {}})
            groups = bucket["groups"].setdefault(group.pk, {"name": group.name, "count": 0, "accounts": []})
            count = counts[account.pk]
            bucket["count"] += count
            groups["count"] += count
            groups["accounts"].append(_node(f"a:{account.pk}", account.name, count))

        values = []
        for account_type in sorted(types, key=self._type_position):
            bucket = types[account_type]
            label = _ACCOUNT_TYPE_LABELS.get(account_type, account_type)
            groups = [
                _node(f"g:{group_id}", group["name"], group["count"], children=group["accounts"])
                for group_id, group in bucket["groups"].items()
            ]
            values.append(_node(f"t:{account_type}", label, bucket["count"], children=groups))

        return {"values": values, "truncated": False}

    def _type_position(self, account_type):
        try:
            return self.TYPE_ORDER.index(account_type)
        except ValueError:
            return len(self.TYPE_ORDER)


@dataclass(frozen=True)
class Column:
    """One filterable/sortable column of the transactions table."""

    key: str
    #: ORM field or annotation the column sorts by, and (for flat columns) filters on.
    field: str
    #: Wire kind, so the client knows how to render a value.
    kind: str = "text"
    #: Turns a query-param string into the value the ORM filters on.  Returning
    #: ``None`` drops the value rather than erroring -- a stale bookmark with a
    #: since-deleted payee should show an unfiltered column, not a 400.
    parse: Any = None
    #: ``value`` -> display label, for columns whose stored value is a code.
    labels: dict | None = None
    #: Facet values are listed newest/largest first where that reads better.
    facet_descending: bool = False
    #: Annotations this column needs, applied only when it is in play.
    annotations: dict = field(default_factory=dict)
    #: How the column's values are filtered and listed.
    values: Any = field(default_factory=FlatValues)

    def label_for(self, wire_value: str) -> str:
        if self.labels is not None:
            return self.labels.get(wire_value, wire_value)
        return wire_value


COLUMNS: dict[str, Column] = {
    "date": Column(
        key="date",
        field="entry_date",
        kind="date",
        facet_descending=True,
        values=DateTree(),
    ),
    "payee": Column(
        key="payee",
        field="payee_name",
        annotations={"payee_name": Coalesce("payee__name", Value(""))},
    ),
    "description": Column(key="description", field="description"),
    "debit_account": Column(
        key="debit_account",
        field="debit_account_name",
        kind="account",
        annotations={"debit_account_name": Coalesce(Subquery(_DEBIT_LINE.values("account__name")[:1]), Value(""))},
        values=AccountTree("debit_account_id", _DEBIT_LINE),
    ),
    "credit_account": Column(
        key="credit_account",
        field="credit_account_name",
        kind="account",
        annotations={"credit_account_name": Coalesce(Subquery(_CREDIT_LINE.values("account__name")[:1]), Value(""))},
        values=AccountTree("credit_account_id", _CREDIT_LINE),
    ),
    "amount": Column(
        key="amount",
        field="amount_value",
        kind="money",
        parse=_parse_decimal,
        facet_descending=True,
        annotations={
            "amount_value": Coalesce(
                Subquery(
                    _DEBIT_LINE.values("dr_amount")[:1], output_field=DecimalField(max_digits=15, decimal_places=2)
                ),
                Value(Decimal("0")),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            )
        },
    ),
    "source": Column(key="source", field="source", kind="choice", labels=dict(JournalEntry.SOURCE_CHOICES)),
    "status": Column(key="status", field="status", kind="choice", labels=dict(JournalEntry.STATUS_CHOICES)),
}


def _param(key: str) -> str:
    return f"{FILTER_PARAM_PREFIX}{key}"


def columns_in_play(params, *, facet_column: str | None = None) -> set[str]:
    """
    The columns this request actually reads.

    Only these columns' annotations are applied: they are correlated
    subqueries, and an unfiltered list has no reason to pay for any of them.
    """
    keys = {key for key in COLUMNS if params.getlist(_param(key))}
    sort = (params.get("sort") or "").strip()
    if sort in COLUMNS:
        keys.add(sort)
    if facet_column in COLUMNS:
        keys.add(facet_column)
    return keys


def annotations_for(params, *, facet_column: str | None = None) -> dict:
    """``BASE_ANNOTATIONS`` plus whatever the columns in play need."""
    annotations = dict(BASE_ANNOTATIONS)
    for key in columns_in_play(params, facet_column=facet_column):
        column = COLUMNS[key]
        annotations.update(column.values.annotations(column))
    return annotations


def apply_column_filters(queryset, params, team, *, exclude: str | None = None):
    """
    Narrow ``queryset`` by every column filter in ``params``.

    ``exclude`` skips one column's own filter, which is what the facets
    endpoint needs: a column's value list has to keep showing the values the
    user has *not* ticked, or unticking one would be impossible.
    """
    for key, column in COLUMNS.items():
        if key == exclude:
            continue
        raw_values = params.getlist(_param(key))
        if not raw_values:
            continue
        condition = column.values.filter_q(column, raw_values, team)
        if condition is not None:
            queryset = queryset.filter(condition)
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


def facet_values(queryset, column: Column, team, *, query: str = "") -> dict:
    """
    The values of ``column`` on offer across ``queryset``, with row counts.

    ``queryset`` is expected to already carry the needed annotations and every
    *other* column's filter, so the counts describe what ticking a value would
    actually show.  Hierarchical columns come back as nested ``children``; a
    branch's count is the total of its leaves.
    """
    payload = column.values.facets(column, queryset, query, team)
    return {"column": column.key, "hierarchical": column.values.hierarchical, **payload}
