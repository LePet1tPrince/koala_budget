"""
Re-runnable proof of the measured claims in docs/ynab-import-plan.md.

Reads the sample export in docs/reference/ and re-derives every figure the plan
asserts, so a claim can be re-checked against a different export rather than
trusted. Pure stdlib, no Django -- run it directly:

    python docs/reference/checks/verify_ynab_assumptions.py

Exits non-zero if any claim fails.
"""

import collections
import csv
import glob
import os
import re
import sys
from datetime import datetime
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
REFERENCE = os.path.dirname(HERE)
ZERO = Decimal(0)


def money(value: str) -> Decimal:
    """YNAB writes the currency symbol *after* the number: `134.32$`, `-130.18$`."""
    return Decimal(value.replace("$", "").replace(",", "") or "0")


def load(pattern: str) -> list[dict]:
    matches = glob.glob(os.path.join(REFERENCE, pattern))
    if not matches:
        sys.exit(f"no file matching {pattern!r} in {REFERENCE}")
    with open(matches[0], encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def register() -> list[dict]:
    rows = load("*Register.csv")
    for index, row in enumerate(rows):
        row["_i"] = index
        row["_net"] = money(row["Inflow"]) - money(row["Outflow"])
        row["_d"] = datetime.strptime(row["Date"], "%d-%m-%Y").date()
        row["_m"] = row["_d"].replace(day=1)
    return rows


def plan() -> list[dict]:
    rows = load("*Plan.csv")
    for row in rows:
        row["_m"] = datetime.strptime(row["Month"], "%b %Y").date()
        row["_assigned"] = money(row["Assigned"])
        row["_activity"] = money(row["Activity"])
        row["_available"] = money(row["Available"])
    return rows


CHECKS = []


def check(name):
    def register_check(fn):
        CHECKS.append((name, fn))
        return fn

    return register_check


@check("transfer legs pair exactly (plan: 839 pairs, 0 unmatched)")
def transfers(reg, _plan):
    legs = [r for r in reg if r["Payee"].startswith("Transfer : ")]
    for row in legs:
        row["_other"] = row["Payee"][len("Transfer : ") :]

    index = collections.defaultdict(list)
    for row in legs:
        index[(row["Account"], row["_other"], row["_d"], abs(row["_net"]))].append(row)

    used, pairs = set(), 0
    for row in legs:
        if row["_i"] in used:
            continue
        key = (row["_other"], row["Account"], row["_d"], abs(row["_net"]))
        mates = [m for m in index.get(key, []) if m["_i"] not in used and m["_net"] == -row["_net"]]
        if mates:
            used.update({row["_i"], mates[0]["_i"]})
            pairs += 1

    unmatched = len(legs) - pairs * 2
    return unmatched == 0, f"{len(legs)} legs -> {pairs} pairs, {unmatched} unmatched"


@check("split legs group by walking (i/n) in file order")
def splits(reg, _plan):
    pattern = re.compile(r"^Split \((\d+)/(\d+)\)")
    legs = [r for r in reg if pattern.match(r["Memo"])]
    for row in legs:
        match = pattern.match(row["Memo"])
        row["_si"], row["_sn"] = int(match.group(1)), int(match.group(2))

    open_groups, groups = {}, []
    for row in sorted(legs, key=lambda r: r["_i"]):
        key = (row["Account"], row["_d"], row["_sn"])
        if row["_si"] == 1:
            open_groups[key] = [row]
        elif key in open_groups and len(open_groups[key]) == row["_si"] - 1:
            open_groups[key].append(row)
        else:
            return False, f"orphan split leg at row {row['_i']}: {row['Memo']!r}"
        if len(open_groups.get(key, [])) == row["_sn"]:
            groups.append(open_groups.pop(key))

    complete = not open_groups
    return complete, f"{len(legs)} legs -> {len(groups)} groups, {len(open_groups)} incomplete"


@check("credit cards are exactly the Plan's Credit Card Payments categories")
def credit_cards(reg, pln):
    named = {r["Category"] for r in pln if r["Category Group"] == "Credit Card Payments"}
    accounts = {r["Account"] for r in reg}

    running, peak = collections.defaultdict(lambda: ZERO), collections.defaultdict(lambda: Decimal("-1e18"))
    for row in sorted(reg, key=lambda r: (r["Account"], r["_d"], r["_i"])):
        running[row["Account"]] += row["_net"]
        peak[row["Account"]] = max(peak[row["Account"]], running[row["Account"]])

    never_positive = {a for a in accounts if peak[a] <= 0}
    return named <= accounts and never_positive <= named, (
        f"{len(named)} named, all real accounts={named <= accounts}, "
        f"never-positive accounts not in the list={sorted(never_positive - named)}"
    )


@check("a categorised Starting Balance row marks an account on-budget")
def on_budget(reg, _plan):
    categorised, starting = collections.defaultdict(bool), {}
    for row in reg:
        if row["Category Group/Category"]:
            categorised[row["Account"]] = True
        if row["Payee"] == "Starting Balance":
            starting[row["Account"]] = bool(row["Category Group/Category"])

    disagree = [a for a, flagged in starting.items() if flagged != categorised[a]]
    accounts = {r["Account"] for r in reg}
    budget = sum(1 for a in accounts if categorised[a])
    return not disagree, f"{budget} on-budget, {len(accounts) - budget} tracking, disagreements={disagree}"


@check("the Plan orders groups and categories identically in every month")
def ordering(_reg, pln):
    per_month = collections.defaultdict(list)
    for row in pln:
        per_month[row["Month"]].append(row["Category Group/Category"])
    distinct = {tuple(v) for v in per_month.values()}
    return len(distinct) == 1, f"{len(per_month)} months, {len(distinct)} distinct orderings"


@check("YNAB always resets a negative Available to 0 at the month boundary")
def ynab_resets(_reg, pln):
    by_category = collections.defaultdict(dict)
    for row in pln:
        by_category[(row["Category Group"], row["Category"])][row["_m"]] = row
    months = sorted({r["_m"] for r in pln})

    carried = reset = 0
    for cells in by_category.values():
        for previous, current in zip(months, months[1:], strict=False):
            before, after = cells.get(previous), cells.get(current)
            if not before or not after or before["_available"] >= 0:
                continue
            base = after["_assigned"] + after["_activity"]
            if after["_available"] == base + before["_available"]:
                carried += 1
            elif after["_available"] == base:
                reset += 1

    return carried == 0 and reset > 0, f"{reset} reset to 0, {carried} carried forward"


@check("D2: `Assigned + max(0, -PrevAvailable)` reproduces YNAB Available under KB's rollover")
def topup(_reg, pln):
    by_category = collections.defaultdict(dict)
    for row in pln:
        if row["Category Group"] == "Credit Card Payments":
            continue  # discarded by D3
        by_category[(row["Category Group"], row["Category"])][row["_m"]] = row
    months = sorted({r["_m"] for r in pln})

    compared = mismatched = topped = 0
    for cells in by_category.values():
        kb, previous = ZERO, None
        for month in months:
            row = cells.get(month)
            if row is None:
                continue
            top_up = max(ZERO, -previous) if previous is not None else ZERO
            topped += bool(top_up)
            # KB's rule, verbatim: Budget - Actual + Available(prev), carrying negatives.
            kb = (row["_assigned"] + top_up) + row["_activity"] + kb
            compared += 1
            mismatched += kb != row["_available"]
            previous = row["_available"]

    return mismatched == 0, f"{compared} category-months, {mismatched} mismatched, {topped} needed a top-up"


@check("register activity reconciles to Plan Activity in every fully elapsed month")
def reconcile(reg, pln):
    export_month = max(r["_m"] for r in pln)

    derived = collections.defaultdict(lambda: ZERO)
    for row in reg:
        if row["Category"]:
            derived[(row["_m"], row["Category Group"], row["Category"])] += row["_net"]
    stated = {(r["_m"], r["Category Group"], r["Category"]): r["_activity"] for r in pln}

    mismatched = []
    for key in set(derived) | set(stated):
        month, group, _ = key
        if month >= export_month or group in ("Credit Card Payments", "Inflow"):
            continue  # structural buckets, see section 2
        if derived.get(key, ZERO) != stated.get(key, ZERO):
            mismatched.append(key)

    return not mismatched, f"{len(mismatched)} mismatched cells before {export_month} (excluding structural buckets)"


def main() -> int:
    reg, pln = register(), plan()
    print(f"register: {len(reg)} rows   plan: {len(pln)} rows\n")

    failures = 0
    for name, fn in CHECKS:
        passed, detail = fn(reg, pln)
        failures += not passed
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}\n         {detail}")

    print(f"\n{len(CHECKS) - failures}/{len(CHECKS)} claims hold")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
