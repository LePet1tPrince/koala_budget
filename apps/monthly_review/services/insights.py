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

from .health import BALANCE_GAP, NO_TRANSACTIONS, STALE_ACCOUNT, UNCATEGORIZED, UNRECONCILED

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
    for flag in health["flags"]:
        account_name = flag["account"].name
        url = flag.get("url", "")
        kind = flag["kind"]
        if kind == NO_TRANSACTIONS:
            out.append(
                Insight(
                    kind=kind,
                    severity="bad",
                    step=1,
                    title=_("%(account)s has no transactions this month.") % {"account": account_name},
                    body=_("Did an import get missed? Fix in Inbox."),
                    url=url,
                )
            )
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
            out.append(
                Insight(
                    kind=kind,
                    severity="warn",
                    step=1,
                    title=_("%(count)d uncategorized transaction(s) in %(account)s.")
                    % {"count": flag["count"], "account": account_name},
                    body=_("Fix in Inbox."),
                    url=url,
                    metric=Decimal(flag["count"]),
                )
            )
        elif kind == UNRECONCILED:
            out.append(
                Insight(
                    kind=kind,
                    severity="warn",
                    step=1,
                    title=_("%(count)d unreconciled transaction(s) in %(account)s.")
                    % {"count": flag["count"], "account": account_name},
                    body=_("The reconciled balance is off by %(gap)s. Fix in Inbox.") % {"gap": _money(flag["gap"])},
                    url=url,
                    delta=flag["gap"],
                )
            )
        elif kind == BALANCE_GAP:
            out.append(
                Insight(
                    kind=kind,
                    severity="warn",
                    step=1,
                    title=_("%(account)s's balance doesn't match its reconciled balance.") % {"account": account_name},
                    body=_("Off by %(gap)s.") % {"gap": _money(flag["gap"])},
                    url=url,
                    delta=flag["gap"],
                )
            )
    return out


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

    for row in baseline["streams"]:
        if not row["amount"] and row["avg"] > 0:
            out.append(
                Insight(
                    kind="stream_missing",
                    severity="bad",
                    step=3,
                    title=_("No income from %(payee)s this month.") % {"payee": row["payee"]},
                    body=_("It usually brings in about %(avg)s.") % {"avg": _money(row["avg"])},
                    metric=row["amount"],
                    delta=-row["avg"],
                )
            )
        elif row["new"]:
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

    for row in rows:
        if row["unbudgeted"] and row["spent"]:
            out.append(
                Insight(
                    kind="unbudgeted_spend",
                    severity="warn",
                    step=6,
                    title=_("%(category)s had spending but no budget.") % {"category": row["name"]},
                    body=_("Spent %(spent)s with nothing assigned.") % {"spent": _money(row["spent"])},
                    metric=row["spent"],
                )
            )

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

    series = net_worth["series"]
    if len(series) > 1:
        window_change = net_worth["now"]["net"] - series[0]["net"]
        out.append(
            Insight(
                kind="net_worth_window",
                severity="good" if window_change >= 0 else "bad",
                step=8,
                title=_("Net worth is %(direction)s %(amount)s since %(start)s.")
                % {
                    "direction": _("up") if window_change >= 0 else _("down"),
                    "amount": _money(abs(window_change)),
                    "start": series[0]["label"],
                },
                metric=net_worth["now"]["net"],
                delta=window_change,
            )
        )
    return out
