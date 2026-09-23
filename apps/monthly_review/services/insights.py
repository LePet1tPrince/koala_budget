"""
The deterministic insight engine (docs/monthly-review-plan.md §6).

Pure and read-only: `generate(review)` reads the already-assembled review
dict (built by `services/review.py`) and turns its raw facts into plain-English
`Insight` objects. No database access here, no LLM -- every insight is a
Python rule over numbers the review already computed, which is what makes this
module fully unit-testable with a hand-built dict.

Copy rules (see §6): plain sentences, no jargon, no exclamation marks; always
name the comparison; every warning names the next action; thresholds are
module constants, never inline literals.
"""

from dataclasses import dataclass
from decimal import Decimal

from django.utils.translation import gettext as _

from apps.web.templatetags.currency_tags import currency

from .health import BALANCE_GAP, NO_TRANSACTIONS, STALE_ACCOUNT, STATEMENT_DUE, UNCATEGORIZED, UNRECONCILED

INCOME_DOWN_THRESHOLD = Decimal("0.10")  # 10%
TOP_TRANSACTIONS_SHARE_THRESHOLD = Decimal("0.50")  # 50%
BIGGEST_TRANSACTIONS_SAMPLE = 10


@dataclass(frozen=True)
class Insight:
    kind: str  # "no_transactions" | "overspent" | "income_down" | ...
    severity: str  # "good" | "info" | "warn" | "bad"
    step: int  # which step surfaces it
    title: str  # one line, already interpolated
    body: str = ""  # one or two sentences
    url: str = ""  # where to act on it
    metric: Decimal | None = None
    delta: Decimal | None = None
    lines: tuple = ()  # one plain sentence per account, for a card that covers several


def _money(amount) -> str:
    return currency(amount)


def _default_baseline(review) -> dict | None:
    default_id = review.get("default_baseline")
    baselines = review.get("baselines") or {}
    return baselines.get(default_id) if default_id else None


def generate(review: dict) -> list:
    insights = []
    insights.extend(_step1_health(review))
    insights.extend(_step2_glance(review))
    insights.extend(_step3_income(review))
    insights.extend(_step4_budget(review))
    insights.extend(_step5_biggest(review))
    insights.extend(_step6_breakdown(review))
    insights.extend(_step7_saving(review))
    insights.extend(_step8_net_worth(review))
    return insights


# Step 1 -- is this month's data trustworthy? ------------------------------


def _step1_health(review) -> list:
    health = review["health"]
    if health["all_clear"]:
        return [
            Insight(
                kind="all_clear",
                severity="good",
                step=1,
                title=_("Everything's accounted for."),
            )
        ]

    out = []
    no_transactions = []
    uncategorized = []
    reconciliation = []  # UNRECONCILED and BALANCE_GAP: both say the reconciled balance is off
    statements_due = []
    for flag in health["flags"]:
        account_name = flag["account"].name
        url = flag.get("url", "")
        kind = flag["kind"]
        if kind == NO_TRANSACTIONS:
            no_transactions.append(flag)
        elif kind == STALE_ACCOUNT:
            out.append(
                Insight(
                    kind=kind,
                    severity="warn",
                    step=1,
                    title=_("%(account)s hasn't had a transaction in %(days)d days.")
                    % {"account": account_name, "days": flag["days"]},
                    body=_("Check whether the feed is still syncing. Fix in Inbox."),
                    url=url,
                )
            )
        elif kind == UNCATEGORIZED:
            uncategorized.append(flag)
        elif kind in (UNRECONCILED, BALANCE_GAP):
            reconciliation.append(flag)
        elif kind == STATEMENT_DUE:
            statements_due.append(flag)

    if no_transactions:
        out.insert(0, _no_transactions_card(no_transactions))
    if uncategorized:
        out.append(_uncategorized_card(uncategorized))
    if reconciliation:
        out.append(_reconciliation_card(reconciliation))
    if statements_due:
        out.append(_statement_due_card(statements_due))
    return out


def _no_transactions_card(flags) -> Insight:
    """One card for every account with no transactions this month, a line per account."""
    return Insight(
        kind=NO_TRANSACTIONS,
        severity="bad",
        step=1,
        title=_("%(accounts)d account(s) have no transactions this month.") % {"accounts": len(flags)},
        body=_("Did an import get missed? Fix in Inbox."),
        url=flags[0].get("url", ""),
        metric=Decimal(len(flags)),
        lines=tuple(f["account"].name for f in flags),
    )


def _uncategorized_card(flags) -> Insight:
    """One card for every account with uncategorized transactions, a line per account."""
    total = sum(f["count"] for f in flags)
    return Insight(
        kind=UNCATEGORIZED,
        severity="warn",
        step=1,
        title=_("%(count)d uncategorized transaction(s) across %(accounts)d account(s).")
        % {"count": total, "accounts": len(flags)},
        body=_("Fix in Inbox."),
        url=flags[0].get("url", ""),
        metric=Decimal(total),
        lines=tuple(
            _("%(account)s: %(count)d uncategorized") % {"account": f["account"].name, "count": f["count"]}
            for f in flags
        ),
    )


def _reconciliation_card(flags) -> Insight:
    """
    One card for every account whose reconciled balance is off, a line per account:
    the unreconciled count when there are unreconciled feed transactions, the gap
    alone when there are none (e.g. a manual journal entry touching the account).
    """
    lines = []
    for f in flags:
        values = {"account": f["account"].name, "gap": _money(f["gap"])}
        if f["kind"] == UNRECONCILED:
            values["count"] = f["count"]
            line = _("%(account)s: %(count)d unreconciled, off by %(gap)s") % values
        else:
            line = _("%(account)s: balance doesn't match the reconciled balance, off by %(gap)s") % values
        lines.append(line)
    count = sum(f.get("count", 0) for f in flags)
    return Insight(
        kind="reconciliation",
        severity="warn",
        step=1,
        title=_("%(accounts)d account(s) not fully reconciled.") % {"accounts": len(flags)},
        body=(_("%(count)d unreconciled transaction(s). Fix in Inbox.") % {"count": count})
        if count
        else _("Fix in Inbox."),
        url=flags[0].get("url", ""),
        metric=Decimal(count),
        lines=tuple(lines),
    )


def _statement_due_card(flags) -> Insight:
    """
    One card for every account whose statement is overdue, a line per account.
    It links to that account's reconcile page when there is one, the hub otherwise.
    """
    lines = []
    for f in flags:
        last = f.get("last_statement_date")
        if last:
            lines.append(
                _("%(account)s: last reconciled %(date)s") % {"account": f["account"].name, "date": last.isoformat()}
            )
        else:
            lines.append(_("%(account)s: never reconciled against a statement") % {"account": f["account"].name})
    return Insight(
        kind=STATEMENT_DUE,
        severity="warn",
        step=1,
        title=_("%(accounts)d account(s) due for a statement check.") % {"accounts": len(flags)},
        body=_("Check each against your latest statement."),
        url=flags[0].get("url", "") if len(flags) == 1 else flags[0].get("hub_url", ""),
        metric=Decimal(len(flags)),
        lines=tuple(lines),
    )


# Step 2 -- the month at a glance -------------------------------------------


def _step2_glance(review) -> list:
    net = review["current"]["net"]
    baseline = _default_baseline(review)
    severity = "good" if net >= 0 else "bad"

    if net >= 0:
        title = _("You came out %(amount)s ahead this month.") % {"amount": _money(net)}
    else:
        title = _("You spent %(amount)s more than you brought in this month.") % {"amount": _money(abs(net))}

    body = ""
    delta = None
    if baseline is not None:
        baseline_net = baseline["avgs"]["net"]
        delta = net - baseline_net
        body = _("That's %(delta)s %(direction)s %(against)s of %(avg)s.") % {
            "delta": _money(abs(delta)),
            "direction": _("more than") if delta >= 0 else _("less than"),
            "against": baseline["against"],
            "avg": _money(baseline_net),
        }

    return [Insight(kind="net_vs_baseline", severity=severity, step=2, title=title, body=body, metric=net, delta=delta)]


# Step 3 -- where the money came from ---------------------------------------


def _step3_income(review) -> list:
    out = []
    baseline = _default_baseline(review)
    if baseline is None:
        return out

    current_income = review["current"]["income"]
    baseline_income = baseline["avgs"]["income"]
    if baseline_income > 0:
        drop = (baseline_income - current_income) / baseline_income
        if drop > INCOME_DOWN_THRESHOLD:
            out.append(
                Insight(
                    kind="income_down",
                    severity="warn",
                    step=3,
                    title=_("Income was down %(pct).0f%% from %(against)s.")
                    % {"pct": drop * 100, "against": baseline["against"]},
                    body=_("%(current)s versus %(avg)s.")
                    % {
                        "current": _money(current_income),
                        "avg": _money(baseline_income),
                    },
                    metric=current_income,
                    delta=current_income - baseline_income,
                )
            )

    # A stream that paid nothing this month is deliberately not flagged: irregular
    # income (a side gig, a quarterly payout) skips months routinely.
    for row in baseline["streams"]:
        if row["new"]:
            out.append(
                Insight(
                    kind="stream_new",
                    severity="info",
                    step=3,
                    title=_("New this month: %(payee)s brought in %(amount)s.")
                    % {"payee": row["payee"], "amount": _money(row["amount"])},
                    metric=row["amount"],
                )
            )
    return out


# Step 4 -- what blew through the budget -------------------------------------


def _step4_budget(review) -> list:
    budget = review["budget"]
    if not budget["overspent"] and not budget["over_assigned"]:
        return [
            Insight(
                kind="budget_clear",
                severity="good",
                step=4,
                title=_("Every category stayed inside its budget."),
            )
        ]

    out = []
    for row in budget["overspent"]:
        out.append(
            Insight(
                kind="overspent",
                severity="bad",
                step=4,
                title=_("%(category)s ended the month %(over)s in the red.")
                % {"category": row["category"].name, "over": _money(row["over"])},
                body=_("Spent %(spent)s against %(assigned)s assigned.")
                % {"spent": _money(row["spent"]), "assigned": _money(row["assigned"])},
                metric=row["spent"],
                delta=row["available"],
            )
        )
    for row in budget["over_assigned"]:
        out.append(
            Insight(
                kind="over_assigned",
                severity="warn",
                step=4,
                title=_("%(category)s went %(over)s over its assignment, covered by carry-over.")
                % {"category": row["category"].name, "over": _money(row["over"])},
                body=_("Spent %(spent)s against %(assigned)s assigned.")
                % {"spent": _money(row["spent"]), "assigned": _money(row["assigned"])},
                metric=row["spent"],
                delta=row["available"],
            )
        )
    return out


# Step 5 -- the biggest line items -------------------------------------------


def _step5_biggest(review) -> list:
    biggest = review["biggest"][:BIGGEST_TRANSACTIONS_SAMPLE]
    spend = review["current"]["spend"]
    if not biggest or not spend:
        return []

    top_total = sum((row["amount"] for row in biggest), Decimal("0"))
    share = top_total / spend
    if share > TOP_TRANSACTIONS_SHARE_THRESHOLD:
        return [
            Insight(
                kind="top_transactions_share",
                severity="info",
                step=5,
                title=_("Your %(count)d biggest transactions made up %(pct).0f%% of this month's spending.")
                % {"count": len(biggest), "pct": share * 100},
                metric=top_total,
            )
        ]
    return []


# Step 6 -- the whole breakdown -----------------------------------------------


def _step6_breakdown(review) -> list:
    out = []
    baseline = _default_baseline(review)

    rows = [
        {**category, "group": group["name"]} for group in review["budget"]["groups"] for category in group["categories"]
    ]

    # Spending in a category with no budget is deliberately not flagged: the
    # breakdown table already marks those rows "unbudgeted".

    if baseline is not None:
        cat_avg = baseline["cat_avg"]
        movers = [
            {"name": row["name"], "delta": row["spent"] - cat_avg[row["id"]]} for row in rows if row["id"] in cat_avg
        ]
        if movers:
            biggest_up = max(movers, key=lambda m: m["delta"])
            biggest_down = min(movers, key=lambda m: m["delta"])
            if biggest_up["delta"] > 0:
                out.append(
                    Insight(
                        kind="biggest_mover_up",
                        severity="info",
                        step=6,
                        title=_("%(category)s rose %(delta)s versus %(against)s.")
                        % {
                            "category": biggest_up["name"],
                            "delta": _money(biggest_up["delta"]),
                            "against": baseline["against"],
                        },
                        delta=biggest_up["delta"],
                    )
                )
            if biggest_down["delta"] < 0:
                out.append(
                    Insight(
                        kind="biggest_mover_down",
                        severity="info",
                        step=6,
                        title=_("%(category)s dropped %(delta)s versus %(against)s.")
                        % {
                            "category": biggest_down["name"],
                            "delta": _money(abs(biggest_down["delta"])),
                            "against": baseline["against"],
                        },
                        delta=biggest_down["delta"],
                    )
                )
    return out


# Step 7 -- what we put away ---------------------------------------------------


def _step7_saving(review) -> list:
    out = []
    current = review["current"]
    baseline = _default_baseline(review)

    if not current["saved"]:
        out.append(
            Insight(
                kind="nothing_saved",
                severity="warn",
                step=7,
                title=_("Nothing was saved toward a goal this month."),
            )
        )
    elif baseline is not None:
        rate_delta = current["savings_rate"] - baseline["avgs"]["savings_rate"]
        severity = "good" if rate_delta >= 0 else "warn"
        direction = _("up") if rate_delta >= 0 else _("down")
        out.append(
            Insight(
                kind="savings_rate_vs_baseline",
                severity=severity,
                step=7,
                title=_("Savings rate is %(direction)s %(pct).1f points versus %(against)s.")
                % {"direction": direction, "pct": abs(rate_delta), "against": baseline["against"]},
                metric=Decimal(str(current["savings_rate"])),
                delta=Decimal(str(rate_delta)),
            )
        )
    return out


# Step 8 -- what it all adds up to ---------------------------------------------


def _step8_net_worth(review) -> list:
    net_worth = review["net_worth"]
    out = []

    month_change = net_worth["now"]["net"] - net_worth["prev"]["net"]
    out.append(
        Insight(
            kind="net_worth_month",
            severity="good" if month_change >= 0 else "bad",
            step=8,
            title=_("Net worth %(direction)s %(amount)s this month.")
            % {"direction": _("rose") if month_change >= 0 else _("fell"), "amount": _money(abs(month_change))},
            metric=net_worth["now"]["net"],
            delta=month_change,
        )
    )

    # The change over the comparison window is stated on the page itself, which
    # follows the selected baseline -- an insight computed here could not.
    return out
