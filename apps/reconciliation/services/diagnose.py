"""
Why a statement does not balance -- the specific lines most likely to blame.

Pure: takes plain rows and returns plain hints, so every rule is a unit test.
All amounts are in STATEMENT sign, and `difference` is
`statement - (opening + ticked)`: ticking a line of amount `a` moves the
difference to `difference - a`.

Deliberately no subset-sum search: it is exponential, and on a real month it
produces confident wrong answers.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.utils.translation import gettext as _

MAX_HINTS = 5
DUPLICATE_WINDOW = timedelta(days=3)
CENT = Decimal("0.01")


@dataclass(frozen=True)
class Row:
    id: int
    date: date
    amount: Decimal
    ticked: bool
    label: str


@dataclass
class Hint:
    kind: str
    message: str
    line_ids: list = field(default_factory=list)
    # What one click on the hint does: "tick", "untick", or None (look, then decide).
    action: str | None = None
    # The lines the click acts on, when not every highlighted line (a duplicate
    # highlights both copies and unticks one).
    action_ids: list | None = None

    def as_dict(self):
        return {
            "kind": self.kind,
            "message": self.message,
            "line_ids": self.line_ids,
            "action": self.action,
            "action_ids": self.action_ids if self.action_ids is not None else self.line_ids,
        }


def money(amount: Decimal) -> str:
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):,.2f}"


def _describe(row: Row) -> str:
    return _("%(label)s, %(date)s, %(amount)s") % {
        "label": row.label or _("(no description)"),
        "date": f"{row.date:%b} {row.date.day}",
        "amount": money(row.amount),
    }


def _transpositions(amount: Decimal):
    """Every amount reachable from `amount` by swapping two adjacent digits (same sign)."""
    cents = str(int(abs(amount) / CENT))
    sign = -1 if amount < 0 else 1
    for i in range(len(cents) - 1):
        if cents[i] == cents[i + 1]:
            continue
        swapped = cents[:i] + cents[i + 1] + cents[i] + cents[i + 2 :]
        yield Decimal(sign * int(swapped)) * CENT


def diagnose(rows, difference: Decimal, statement_date: date, uncategorized=()) -> list[Hint]:
    """
    Up to `MAX_HINTS` hints, strongest first. `uncategorized` is a list of Rows for
    feed rows with no journal entry (never ticked).
    """
    if difference == 0:
        return []
    ticked = [r for r in rows if r.ticked]
    unticked = [r for r in rows if not r.ticked]
    hints: list[Hint] = []

    for row in unticked:
        if row.amount == difference:
            hints.append(Hint("missing_tick", _("Tick %(row)s?") % {"row": _describe(row)}, [row.id], "tick"))

    # A duplicate pair is one hint, not one "untick it?" per copy: the message
    # names both, highlights both, and the one-click fix unticks the later copy.
    in_duplicate = set()
    for i, a in enumerate(ticked):
        for b in ticked[i + 1 :]:
            if a.amount == b.amount == -difference and abs(a.date - b.date) <= DUPLICATE_WINDOW:
                if a.id in in_duplicate or b.id in in_duplicate:
                    continue
                in_duplicate.update((a.id, b.id))
                hints.append(
                    Hint(
                        "duplicate",
                        _("These two look like the same transaction: %(a)s and %(b)s. Untick one?")
                        % {"a": _describe(a), "b": _describe(b)},
                        [a.id, b.id],
                        "untick",
                        [b.id],
                    )
                )

    for row in ticked:
        if row.amount == -difference and row.id not in in_duplicate:
            hints.append(
                Hint(
                    "extra_tick",
                    _("%(row)s may not be on this statement. Untick it?") % {"row": _describe(row)},
                    [row.id],
                    "untick",
                )
            )

    for row in ticked:
        if row.amount * 2 == -difference:
            hints.append(
                Hint(
                    "wrong_sign",
                    _("%(row)s may be entered the wrong way round (money in instead of out, or the reverse).")
                    % {"row": _describe(row)},
                    [row.id],
                )
            )

    for row in ticked:
        for swapped in _transpositions(row.amount):
            if swapped - row.amount == difference:
                hints.append(
                    Hint(
                        "transposed",
                        _("Did the bank show %(bank)s where Koala has %(row)s? Two digits may be swapped.")
                        % {"bank": money(swapped), "row": _describe(row)},
                        [row.id],
                    )
                )
                break

    later = [r for r in ticked if r.date > statement_date]
    if later and sum((r.amount for r in later), Decimal("0")) == -difference:
        hints.append(
            Hint(
                "after_statement",
                _("%(n)d ticked transaction(s) are dated after the statement date. Untick them?") % {"n": len(later)},
                [r.id for r in later],
                "untick",
            )
        )

    uncategorized = list(uncategorized)
    single = [r for r in uncategorized if r.amount == difference]
    if single:
        hints.append(
            Hint(
                "uncategorized",
                _("%(row)s isn't categorized yet, so it can't be ticked. Categorize it first.")
                % {"row": _describe(single[0])},
            )
        )
    elif uncategorized and sum((r.amount for r in uncategorized), Decimal("0")) == difference:
        hints.append(
            Hint(
                "uncategorized",
                _("The %(n)d uncategorized transaction(s) add up to exactly the difference. Categorize them first.")
                % {"n": len(uncategorized)},
            )
        )

    return hints[:MAX_HINTS]
