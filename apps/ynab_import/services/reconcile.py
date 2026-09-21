"""
The import's integrity gate.

Measured on the sample export: 2,788 of 3,016 category-months derived from the
Register match the Plan's `Activity` to the cent, and every one of the 228 that do
not falls into one of three explainable buckets -- YNAB's credit-card payment
envelopes (Plan-only), `Inflow: Ready to Assign` (Register-only) and the export's
own partial month. That makes the comparison a real assertion rather than a soft
heuristic, so it runs after every import and gates the "your data is in" screen.

Three checks, all pure:

* `activity` -- every row of the Register reached the category the Plan says it did.
* `available` -- replaying KB's own rollover over the budgets this import writes
  reproduces YNAB's `Available` column (see `build.budget_amount`, D2).
* `balances` -- each account's imported lines add up to the balance the Register
  ends on.
"""

import collections
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .analyse import CREDIT_CARD_GROUP, KIND_EXPENSE, Analysis
from .build import ASSET, ImportPlan, budget_amount, category_key

ZERO = Decimal("0")

# How many examples a failing check carries back to the UI. Enough to recognise the
# problem, not enough to be a data dump.
SAMPLE_SIZE = 10


@dataclass
class Check:
    name: str
    label: str
    passed: bool
    checked: int
    mismatched: int
    detail: str = ""
    samples: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "passed": self.passed,
            "checked": self.checked,
            "mismatched": self.mismatched,
            "detail": self.detail,
            "samples": self.samples,
        }


@dataclass
class Reconciliation:
    checks: list[Check]
    # The export's own month, reported separately: the Plan is a snapshot taken
    # part-way through it while the Register already carries the whole month.
    export_month: date | None = None

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    def as_dict(self) -> dict:
        return {
            "passed": self.passed,
            "export_month": self.export_month.isoformat() if self.export_month else None,
            "checks": [check.as_dict() for check in self.checks],
        }


def reconcile(analysis: Analysis, plan: ImportPlan) -> Reconciliation:
    export_month = max((row.month for row in analysis.plan), default=None)
    return Reconciliation(
        checks=[
            check_activity(analysis, plan, export_month),
            check_available(analysis, plan.choices),
            check_balances(analysis, plan),
        ],
        export_month=export_month,
    )


def check_activity(analysis: Analysis, plan: ImportPlan, export_month: date | None) -> Check:
    """
    Every category shows the same activity in Koala Budget as it did in YNAB.

    Derived from the lines this import will write, not from the rows they came from,
    so it catches a transaction dropped on the way in, one posted to the wrong
    category, and one posted on the wrong side -- each of which would otherwise be
    invisible until the user noticed a figure they did not recognise.

    Three buckets are excluded because they are not comparisons at all: YNAB's
    credit-card payment envelopes never appear in the register, income carries the
    single category `Ready to Assign`, and the export's own month is a snapshot taken
    part-way through it.
    """
    lines: dict[tuple, Decimal] = collections.defaultdict(lambda: ZERO)
    for entry in plan.entries:
        month = entry.entry_date.replace(day=1)
        for line in entry.lines:
            lines[(line.account, month)] += line.dr - line.cr

    by_category: dict[tuple[str, str], list] = collections.defaultdict(list)
    for row in analysis.plan:
        by_category[row.key].append(row)

    mismatches = []
    checked = explained = 0
    for (group, name), account in plan.category_keys.items():
        for row in by_category.get((group, name), ()):
            if group == CREDIT_CARD_GROUP or (export_month is not None and row.month >= export_month):
                continue
            checked += 1
            # A categorised transfer's activity is money YNAB counted against this
            # category while moving it between two of the user's own accounts. KB
            # cannot post that to a category without misstating net worth (D6) -- it
            # becomes a goal allocation, or nothing -- so it is subtracted here rather
            # than silently failing the gate, and counted, so the summary can say how
            # many months were affected.
            moved = plan.transfer_activity.get((group, name, row.month), ZERO)
            explained += bool(moved)
            # KB's actual for an expense is `dr - cr`, the negative of the way YNAB
            # signs the same spending.
            got = lines.get((account, row.month), ZERO)
            if got != -(row.activity - moved):
                mismatches.append(
                    f"{group}: {name} in {row.month:%b %Y} -- we make it {got}, YNAB's plan says {-row.activity}"
                )

    return Check(
        name="activity",
        label="Every transaction reached the right category",
        passed=not mismatches,
        checked=checked,
        mismatched=len(mismatches),
        detail=(
            f"{checked - len(mismatches)} of {checked} category-months match YNAB to the cent"
            + (f" ({explained} of them after setting aside money moved between your own accounts)" if explained else "")
            if checked
            else "No completed months to check"
        ),
        samples=sorted(mismatches)[:SAMPLE_SIZE],
    )


def check_available(analysis: Analysis, choices=None) -> Check:
    """
    KB's rollover, replayed over the budgets this import writes, reproduces YNAB.

    KB carries a negative `Available` forward while YNAB resets it to zero, so
    importing the `Assigned` column verbatim would leave most categories deeply in
    the red. `build.budget_amount` adds back the money YNAB took from Ready to
    Assign to cover each overspend, and this check is the proof that it lands on
    YNAB's own figure rather than near it.
    """
    kinds = {}
    for facts in analysis.categories:
        kind = facts.kind
        if choices is not None:
            choice = choices.categories.get(category_key(facts.group, facts.name))
            if choice is not None:
                kind = choice.kind
        kinds[(facts.group, facts.name)] = kind

    by_category: dict[tuple[str, str], list] = collections.defaultdict(list)
    for row in analysis.plan:
        by_category[row.key].append(row)

    mismatches = []
    checked = 0
    for key, rows in by_category.items():
        if key[0] == CREDIT_CARD_GROUP or kinds.get(key) != KIND_EXPENSE:
            # Goals and investment activity are not budget categories in KB, so there
            # is no Available of theirs to compare.
            continue

        running = ZERO
        previous = None
        for row in sorted(rows, key=lambda r: r.month):
            # KB's own formula, verbatim: Budget - Actual + Available(previous), where
            # KB's Actual for an expense is the negative of YNAB's Activity.
            running = budget_amount(row.assigned, previous) + row.activity + running
            previous = row.available
            checked += 1
            if running != row.available:
                mismatches.append(
                    f"{key[0]}: {key[1]} in {row.month:%b %Y} -- we make it {running}, YNAB says {row.available}"
                )

    return Check(
        name="available",
        label="Every category's Available matches YNAB",
        passed=not mismatches,
        checked=checked,
        mismatched=len(mismatches),
        detail=f"{checked - len(mismatches)} of {checked} category-months match",
        samples=sorted(mismatches)[:SAMPLE_SIZE],
    )


def check_balances(analysis: Analysis, plan: ImportPlan) -> Check:
    """
    Each account ends on the balance the Register ends on.

    Derived from the planned lines rather than from the rows they came from, so it
    catches a row posted to the wrong side as well as a row never posted at all.
    """
    types = {account.key: account.account_type for account in plan.accounts}
    names = {account.key: account.name for account in plan.accounts}

    totals: dict[tuple[str, str], Decimal] = collections.defaultdict(lambda: ZERO)
    for entry in plan.entries:
        for line in entry.lines:
            if types.get(line.account) in (ASSET, "liability"):
                totals[line.account] += line.dr - line.cr
    for opening in plan.openings:
        totals[opening.account] += opening.amount if types.get(opening.account) == ASSET else -opening.amount

    expected: dict[tuple[str, str], Decimal] = {}
    for facts in analysis.accounts:
        key = plan.account_keys.get(facts.name)
        if key is not None:
            expected[key] = expected.get(key, ZERO) + facts.closing_balance

    mismatches = []
    for key, want in expected.items():
        got = totals.get(key, ZERO)
        if got != want:
            mismatches.append(f"{names.get(key, key[1])} -- we make it {got}, your export ends on {want}")

    return Check(
        name="balances",
        label="Every account ends on the balance YNAB shows",
        passed=not mismatches,
        checked=len(expected),
        mismatched=len(mismatches),
        detail=f"{len(expected) - len(mismatches)} of {len(expected)} accounts match",
        samples=sorted(mismatches)[:SAMPLE_SIZE],
    )
