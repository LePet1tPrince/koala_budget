"""
Bender Dashboard v3 - House + Personal Finances
===============================================
Two-page (tabbed) single-file HTML dashboard.

  PAGE 1  House & Mortgage - month-over-month focused. Answers:
          "How much more equity than last month? How many months of
          amortization did we shave off THIS month? What did the extra
          payment actually buy us?"

  PAGE 2  Personal Finances - built from the YNAB Plan (budget) and
          Register (ledger) CSV exports. Focuses on the current month
          vs the trailing 12 months.

INPUTS
  Amroth Tracker.xlsx                         (Params / Loan Info)
  My Budget as of *- Plan.csv                 (YNAB budget export)
  My Budget as of *- Register.csv             (YNAB ledger export)

OUTPUT
  reviews/bender_review_<YYYY-MM>.html   one file per month, never overwritten
  reviews/index.html                     listing of every review in the folder

RUN
  python bender_dashboard_v3.py              pick the month from a menu
  python bender_dashboard_v3.py 2026-08      go straight to August 2026
  python bender_dashboard_v3.py "Aug 2026"   same thing
  python bender_dashboard_v3.py --latest     newest complete month, no prompt
  python bender_dashboard_v3.py --list       show every month in the data
  python bender_dashboard_v3.py --out=DIR    write somewhere else (dir or .html)

  The finance tab and the walkthrough always cover ONE complete month. The
  default is the last complete calendar month, because the month in progress
  is usually only part-budgeted. The House tab is unaffected - it always runs
  to the newest actual mortgage payment.

REQUIREMENTS: pip install openpyxl
"""

import os
import re
import sys
import csv
import json
import glob
import math
from datetime import date, datetime

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
TRACKER_FILE = os.path.join(SCRIPT_DIR, "Amroth Tracker.xlsx")
# One file per month under reviews/, so generating September never clobbers
# August. reviews/index.html lists them all and is rebuilt on every run.
OUTPUT_DIR   = os.path.join(SCRIPT_DIR, "reviews")

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTH_NUM = {n: i + 1 for i, n in enumerate(MONTH_NAMES)}

# YNAB category groups that represent real spending (vs. savings or
# credit-card payment shuffling).
SPEND_GROUPS  = {"Monthly", "Cumulative", "Tax Deductible", "Hidden Categories"}
SAVING_GROUPS = {"Savings"}
# Categories inside SAVING_GROUPS that are not actually money set aside.
SAVING_EXCLUDE = {"Investment Gain/Loss", "Savings Expenses"}
# The single category that carries the whole Amroth housing payment.
HOUSING_CATEGORIES = {"Amroth House", "Rent", "Hydro"}


# ---------------------------------------------------------------------------
# SMALL HELPERS
# ---------------------------------------------------------------------------

def as_date(v):
    if isinstance(v, datetime):
        return v.date()
    return v


def fmt_month(d):
    d = as_date(d)
    return MONTH_NAMES[d.month - 1] + " " + str(d.year)


def add_months(y, m, n):
    idx = y * 12 + (m - 1) + n
    return idx // 12, (idx % 12) + 1


def label_from_key(key):
    y, m = key.split("-")
    return MONTH_NAMES[int(m) - 1] + " " + y


def money(s):
    """Parse YNAB's '1,234.56$' / '-1,234.56$' money strings."""
    s = (s or "").replace("$", "").replace(",", "").strip()
    if not s:
        return 0.0
    neg = s.startswith("-")
    s = s.lstrip("-")
    try:
        v = float(s)
    except ValueError:
        return 0.0
    return -v if neg else v


def num(v, default=0.0):
    return float(v) if isinstance(v, (int, float)) else default


def remaining_months(balance, payment, annual_rate):
    """Months to pay `balance` down to zero at `payment`/mo. None = never."""
    if balance <= 0:
        return 0
    r = annual_rate / 12.0
    if r <= 0:
        return (balance / payment) if payment > 0 else None
    if payment <= balance * r:
        return None
    return -math.log(1 - balance * r / payment) / math.log(1 + r)


def amortized_payment(principal, annual_rate, years):
    r = annual_rate / 12.0
    n = years * 12
    if principal <= 0:
        return 0.0
    if r == 0:
        return principal / n
    return principal * r * (1 + r) ** n / ((1 + r) ** n - 1)


def find_csv(kind):
    hits = sorted(glob.glob(os.path.join(SCRIPT_DIR, "*- " + kind + ".csv")))
    if not hits:
        hits = sorted(glob.glob(os.path.join(SCRIPT_DIR, "*" + kind + "*.csv")))
    return hits[-1] if hits else None


# ---------------------------------------------------------------------------
# LOADERS - XLSX
# ---------------------------------------------------------------------------

def load_params(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["Params"]
    lk = {}
    for row in ws.iter_rows(values_only=True):
        if row[0] and row[1] is not None:
            lk[str(row[0]).strip()] = row[1]

    def g(key, default):
        try:
            return float(lk[key])
        except (KeyError, TypeError, ValueError):
            return default

    p = {
        "house_value":      g("House Value", 1_260_000),
        "bender_share":     g("Bender Ownership Share", 0.50),
        "rate":             g("Annual Interest Rate", 0.0394),
        "bender_payment":   g("Bender Monthly Payment", 2473.05),
        "martin_payment":   g("Martin Monthly Payment", 2798.53),
        "buyout_rate":      g("Buyout Rate (annual)", 0.0394),
        "buyout_amort_yrs": int(g("Buyout Amortization Yrs", 25)),
        "taxes":            g("Property Taxes", 450.0),
        "insurance":        g("Insurance", 166.67),
        "maintenance":      g("Maintenance Reserve", 333.33),
        "utilities":        g("Utilities", 250.0),
        "tenant_rent":      g("Basement Tenant Rent", 1695.0),
        "bender_rent":      g("Bender Gross Monthly Rent", 3000.0),
    }
    p["expenses"] = p["taxes"] + p["insurance"] + p["maintenance"] + p["utilities"]
    p["bender_half_value"] = p["house_value"] * p["bender_share"]
    return p


def load_loan_info(path, today):
    """Returns dict with the actual rows parsed into plain dicts."""
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["Loan Info"]
    raw = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] is None:
            break
        raw.append(row)

    def parse(r):
        return {
            "month_end":  as_date(r[0]),
            "pay_date":   as_date(r[1]),
            "start_bal":  num(r[2]),
            "payment":    num(r[3]),
            "base_prin":  num(r[4]),
            "interest":   num(r[5]),
            "end_bal":    num(r[6]),
            "b_start":    num(r[7]),
            "b_payment":  num(r[9]),
            "b_prin":     num(r[10]),
            "b_interest": num(r[11]),
            "b_extra":    num(r[12]),
            "b_transfer": num(r[13]),
            "b_end":      num(r[14]),
            "m_start":    num(r[15]),
            "m_end":      num(r[21]),
        }

    rows      = [parse(r) for r in raw]
    actual    = [r for r in rows if r["pay_date"] and r["pay_date"] <= today]
    projected = rows[len(actual):]
    return {"rows": rows, "actual": actual, "projected": projected}


# Which YNAB accounts hold the savings earmarked for buying the Martins out.
# This replaced the "Investments" tab that used to live in Amroth Tracker.xlsx
# (deleted Sep 2026) - the register carries the same balances, without the
# hand-typed drift the sheet had accumulated.
#
# "Emergency Fund (V-TFSA)" is deliberately NOT here. It is a TFSA, but it is
# the emergency fund, not buyout money, and the old sheet never counted it.
BUYOUT_SAVINGS_ACCOUNTS = {
    "Tim":    ["Timmy's TFSA", "Timmy's TFSA Trade", "T WS TFSA HISA"],
    "Vivian": ["Viv's TFSA"],
}
# Payees that move the balance without being a contribution of new money.
NON_CONTRIBUTION_PAYEES = ("investment gain/loss", "reconciliation balance adjustment")


def load_buyout_savings(reg, today):
    """Month-end TFSA balances per person, straight from the YNAB register.

    Returns the same shape the old Investments-sheet loader did, so
    compute_house() is unchanged. Balances run from the first month either
    account saw activity through the current month; anything dated after
    today (YNAB carries future scheduled transactions) is ignored.
    """
    empty = {"tim": 0.0, "vivian": 0.0, "combined": 0.0,
             "last_label": None, "months": [], "by_label": {}, "accounts": {}}
    owner = {}
    for person, accounts in BUYOUT_SAVINGS_ACCOUNTS.items():
        for a in accounts:
            owner[a] = person
    cutoff = today.isoformat()

    moves = [t for t in reg if t["account"] in owner and t["date"] <= cutoff]
    if not moves:
        return empty

    by_month = {}
    for t in moves:
        person = owner[t["account"]]
        b = by_month.setdefault(t["key"], {"Tim": 0.0, "Vivian": 0.0,
                                           "Tim_c": 0.0, "Vivian_c": 0.0})
        b[person] += t["amount"]
        if t["amount"] > 0 and (t["payee"] or "").strip().lower() not in NON_CONTRIBUTION_PAYEES:
            b[person + "_c"] += t["amount"]

    first, last = min(by_month), max("%d-%02d" % (today.year, today.month), max(by_month))
    y, m = int(first[:4]), int(first[5:])
    ly, lm = int(last[:4]), int(last[5:])

    tim = viv = 0.0
    months, by_label, last_label = [], {}, None
    while (y, m) <= (ly, lm):
        key = "%d-%02d" % (y, m)
        b = by_month.get(key, {})
        tim += b.get("Tim", 0.0)
        viv += b.get("Vivian", 0.0)
        label = label_from_key(key)
        # "+ 0.0" turns a rounded -0.0 back into 0.0 - these accounts were
        # drained to fund the down payment and sat at nil through late 2025,
        # which otherwise renders as "-$0"
        row = {"label": label, "key": key,
               "tim": round(tim, 2) + 0.0, "viv": round(viv, 2) + 0.0,
               "combined": round(tim + viv, 2) + 0.0,
               "tim_contrib": round(b.get("Tim_c", 0.0), 2),
               "viv_contrib": round(b.get("Vivian_c", 0.0), 2),
               "has_data": True}
        months.append(row)
        by_label[label] = row
        last_label = label
        y, m = add_months(y, m, 1)

    # per-account closing balances, so the dashboard can show the breakdown
    accounts = {}
    for t in moves:
        accounts[t["account"]] = round(accounts.get(t["account"], 0.0) + t["amount"], 2)

    return {"tim": round(tim, 2) + 0.0, "vivian": round(viv, 2) + 0.0,
            "combined": round(tim + viv, 2) + 0.0, "last_label": last_label,
            "months": months, "by_label": by_label, "accounts": accounts}


# ---------------------------------------------------------------------------
# LOADERS - YNAB CSV
# ---------------------------------------------------------------------------

def load_ynab_plan(path):
    """[{month_key, group, category, assigned, activity, available}]"""
    out = []
    if not path or not os.path.exists(path):
        return out
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for x in csv.DictReader(fh):
            mlabel = (x.get("Month") or "").strip()
            parts = mlabel.split()
            if len(parts) != 2 or parts[0] not in MONTH_NUM:
                continue
            out.append({
                "key":      parts[1] + "-" + ("%02d" % MONTH_NUM[parts[0]]),
                "group":    (x.get("Category Group") or "").strip(),
                "category": (x.get("Category") or "").strip(),
                "assigned": money(x.get("Assigned")),
                "activity": money(x.get("Activity")),
                "available": money(x.get("Available")),
            })
    return out


def load_ynab_register(path):
    """[{key, date, account, payee, group, category, memo, amount}]
    amount is signed: inflow positive, outflow negative."""
    out = []
    if not path or not os.path.exists(path):
        return out
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for x in csv.DictReader(fh):
            d = (x.get("Date") or "").strip()
            m = re.match(r"^(\d{2})-(\d{2})-(\d{4})$", d)
            if not m:
                continue
            dd, mm, yy = m.groups()
            payee = (x.get("Payee") or "").strip()
            out.append({
                "key":      yy + "-" + mm,
                "date":     yy + "-" + mm + "-" + dd,
                "account":  (x.get("Account") or "").strip(),
                "payee":    payee,
                "group":    (x.get("Category Group") or "").strip(),
                "category": (x.get("Category") or "").strip(),
                "memo":     (x.get("Memo") or "").strip(),
                "amount":   money(x.get("Inflow")) - money(x.get("Outflow")),
                "transfer": payee.startswith("Transfer :") or payee.startswith("Transfer:"),
            })
    return out


# ---------------------------------------------------------------------------
# HOUSE / MORTGAGE MATH
# ---------------------------------------------------------------------------

def compute_house(p, loan, inv):
    """Everything the House page needs, with month-over-month deltas."""
    actual = loan["actual"]
    if not actual:
        raise SystemExit("Loan Info has no actual rows (no pay_date <= today).")

    rate = p["rate"]
    r_m  = rate / 12.0
    half = p["bender_half_value"]

    # per-month series, with a no-extras baseline running alongside
    base_bal   = actual[0]["b_start"]
    base_cum_i = 0.0
    cum_i = 0.0
    cum_extra = 0.0
    cum_transfer = 0.0
    series = []
    for row in actual:
        cum_i        += row["b_interest"]
        cum_extra    += row["b_extra"]
        cum_transfer += row["b_transfer"] / 2.0

        # The tracker charges interest on an actual-day-count basis, so the
        # implied annual rate wobbles (3.60%-4.23% across recent months) around
        # the 3.94% in Params. Running the no-extras baseline on a flat rate/12
        # would bank that difference as fake "saving", so the baseline is
        # charged the same effective rate the real month was charged.
        r_eff = (row["b_interest"] / row["b_start"]) if row["b_start"] else r_m
        b_int = base_bal * r_eff
        base_cum_i += b_int
        base_bal = max(0.0, base_bal - (row["b_payment"] - b_int))

        rem      = remaining_months(row["b_end"], row["b_payment"], rate)
        base_rem = remaining_months(base_bal, row["b_payment"], rate)
        # What the extra principal bought THIS month: where the balance would
        # have landed on the scheduled payment alone, versus where it actually
        # landed. Both sides go through the same closed form, so the rate
        # convention cancels and a month with no extra reads exactly 0.00.
        sched_only = row["b_start"] + row["b_interest"] - row["b_payment"]
        rem_sched  = remaining_months(sched_only, row["b_payment"], rate)
        shaved = (None if (rem is None or rem_sched is None)
                  else round(rem_sched - rem, 2))
        label = fmt_month(row["month_end"])
        # payoff point as "months since year 0", so the chart can plot a date
        # on a numeric axis and format the ticks back into Mon YYYY
        idx0 = row["month_end"].year * 12 + (row["month_end"].month - 1)
        payoff_idx      = None if rem is None else round(idx0 + rem, 3)
        base_payoff_idx = None if base_rem is None else round(idx0 + base_rem, 3)
        tf = inv["by_label"].get(label, {})
        series.append({
            "label":      label,
            "key":        "%d-%02d" % (row["month_end"].year, row["month_end"].month),
            "b_end":      round(row["b_end"], 2),
            "m_end":      round(row["m_end"], 2),
            "total_end":  round(row["end_bal"], 2),
            "equity":     round(half - row["b_end"], 2),
            "equity_pct": round((half - row["b_end"]) / half * 100, 2),
            "b_interest": round(row["b_interest"], 2),
            "b_prin":     round(row["b_prin"], 2),
            "b_extra":    round(row["b_extra"], 2),
            "b_transfer": round(row["b_transfer"] / 2.0, 2),
            "principal_total": round(row["b_prin"] + row["b_extra"] + row["b_transfer"] / 2.0, 2),
            "cum_interest": round(cum_i, 2),
            "cum_extra":    round(cum_extra, 2),
            "cum_transfer": round(cum_transfer, 2),
            "base_bal":     round(base_bal, 2),
            "base_equity":  round(half - base_bal, 2),
            "base_cum_interest": round(base_cum_i, 2),
            "shaved":           shaved,
            "payoff_idx":       payoff_idx,
            "base_payoff_idx":  base_payoff_idx,
            "remaining":        None if rem is None else int(math.ceil(rem)),
            "remaining_exact":  None if rem is None else round(rem, 3),
            "base_remaining":       None if base_rem is None else int(math.ceil(base_rem)),
            "base_remaining_exact": None if base_rem is None else round(base_rem, 3),
            "tfsa":           tf.get("combined") if tf.get("has_data") else None,
        })

    cur  = series[-1]
    prev = series[-2] if len(series) > 1 else None

    def d(field):
        if prev is None:
            return 0.0
        a, b = cur.get(field), prev.get(field)
        if a is None or b is None:
            return 0.0
        return round(a - b, 2)

    # Amortization shaved. Each month that passes naturally removes one
    # month of remaining term; anything beyond that is what the extra
    # principal actually bought.
    rem_now  = cur["remaining"]
    rem_prev = prev["remaining"] if prev else None
    ex_now   = cur["remaining_exact"]
    ex_prev  = prev["remaining_exact"] if prev else None
    shaved_mom = cur["shaved"]
    shaved_total = None
    if ex_now is not None and cur["base_remaining_exact"] is not None:
        shaved_total = round(cur["base_remaining_exact"] - ex_now, 1)
    shaved_total_prev = None
    if prev and prev["remaining_exact"] is not None and prev["base_remaining_exact"] is not None:
        shaved_total_prev = round(prev["base_remaining_exact"] - prev["remaining_exact"], 1)

    def payoff_from(row, field):
        if row is None or row[field] is None:
            return None
        y, m = add_months(int(row["key"][:4]), int(row["key"][5:]), row[field])
        return MONTH_NAMES[m - 1] + " " + str(y)

    payoff_earlier = None
    if rem_now is not None and rem_prev is not None:
        payoff_earlier = rem_prev - rem_now - 1

    interest_saved      = round(cur["base_cum_interest"] - cur["cum_interest"], 2)
    interest_saved_prev = round(prev["base_cum_interest"] - prev["cum_interest"], 2) if prev else 0.0

    # Buyout snapshot at current balances
    martin_share    = p["house_value"] * (1 - p["bender_share"])
    total_financing = cur["b_end"] + martin_share
    new_mortgage    = min(total_financing, p["house_value"] * 0.80)
    cash_at_closing = max(0.0, total_financing - new_mortgage)
    martin_payout   = martin_share - cur["m_end"]
    new_payment     = amortized_payment(new_mortgage, p["buyout_rate"], p["buyout_amort_yrs"])
    net_after = new_payment + p["expenses"] - p["tenant_rent"]
    net_now   = (p["bender_payment"] + p["expenses"] / 2.0 - p["tenant_rent"] / 2.0
                 + p["bender_rent"] * (1 - p["bender_share"]))

    with_tfsa = [x for x in series if x["tfsa"] is not None]
    tfsa_label      = with_tfsa[-1]["label"] if with_tfsa else None
    tfsa_prev_label = with_tfsa[-2]["label"] if len(with_tfsa) > 1 else None
    tfsa_now  = with_tfsa[-1]["tfsa"] if with_tfsa else inv["combined"]
    tfsa_prev = with_tfsa[-2]["tfsa"] if len(with_tfsa) > 1 else 0.0

    buyout = {
        "martin_share":    round(martin_share, 2),
        "b_end":           cur["b_end"],
        "total_financing": round(total_financing, 2),
        "new_mortgage":    round(new_mortgage, 2),
        "cash_at_closing": round(cash_at_closing, 2),
        "martin_payout":   round(martin_payout, 2),
        "new_payment":     round(new_payment, 2),
        "net_after":       round(net_after, 2),
        "net_now":         round(net_now, 2),
        "net_change":      round(net_after - net_now, 2),
        "expenses":        round(p["expenses"], 2),
        "tenant_rent":     round(p["tenant_rent"], 2),
        "buyout_rate_pct": round(p["buyout_rate"] * 100, 2),
        "amort_yrs":       p["buyout_amort_yrs"],
    }
    return {
        "cur_label":  cur["label"],
        "prev_label": prev["label"] if prev else None,
        "months_elapsed": len(series),
        "house_value": p["house_value"],
        "half_value":  round(half, 2),
        "equity":       cur["equity"],
        "equity_prev":  prev["equity"] if prev else 0.0,
        "equity_delta": d("equity"),
        "equity_pct":   cur["equity_pct"],
        "equity_pct_prev": prev["equity_pct"] if prev else 0.0,
        "b_end":        cur["b_end"],
        "b_end_prev":   prev["b_end"] if prev else None,
        "all_in":       round(cur["b_end"] + martin_share, 2),
        "all_in_prev":  round(prev["b_end"] + martin_share, 2) if prev else None,
        "b_end_delta":  d("b_end"),
        "m_end":        cur["m_end"],
        "total_end":    cur["total_end"],
        "total_delta":  d("total_end"),
        "principal_total":      cur["principal_total"],
        "principal_total_prev": prev["principal_total"] if prev else 0.0,
        "principal_delta":      d("principal_total"),
        "base_prin":      cur["b_prin"],
        "base_prin_prev": prev["b_prin"] if prev else None,
        "total_end_prev": prev["total_end"] if prev else None,
        "extra":      cur["b_extra"],
        "extra_prev": prev["b_extra"] if prev else 0.0,
        "transfer":   cur["b_transfer"],
        "interest_month":       cur["b_interest"],
        "interest_month_prev":  prev["b_interest"] if prev else 0.0,
        "interest_month_delta": d("b_interest"),
        "cum_extra":    cur["cum_extra"],
        "cum_transfer": cur["cum_transfer"],
        "remaining":      rem_now,
        "remaining_prev": rem_prev,
        "shaved_mom":       shaved_mom,
        "shaved_total":     shaved_total,
        "shaved_total_prev": shaved_total_prev,
        "payoff_earlier": payoff_earlier,
        "payoff":      payoff_from(cur, "remaining"),
        "payoff_prev": payoff_from(prev, "remaining"),
        "payoff_base": payoff_from(cur, "base_remaining"),
        "interest_saved":       interest_saved,
        "interest_saved_prev":  interest_saved_prev,
        "interest_saved_delta": round(interest_saved - interest_saved_prev, 2),
        "tfsa":       round(tfsa_now, 2),
        "tfsa_prev":  round(tfsa_prev, 2),
        "tfsa_label":      tfsa_label,
        "tfsa_prev_label": tfsa_prev_label,
        "tfsa_delta": round(tfsa_now - tfsa_prev, 2),
        "tim":        round(inv["tim"], 2),
        "vivian":     round(inv["vivian"], 2),
        "buyout":     buyout,
        "series":     series,
        "history":    list(reversed(series)),
    }


# ---------------------------------------------------------------------------
# PERSONAL FINANCE MATH (YNAB)
# ---------------------------------------------------------------------------

DEBT_PAT  = re.compile(r"credit card|visa|mastercard|amex|loan|line of credit", re.I)
CASH_PAT  = re.compile(r"chequing|checking|paycheck|cash|savings \(|^cash$", re.I)
# Cash-equivalents and YNAB working accounts whose names match nothing above.
# Without these they fall into "Other", which is how a -$134 drift on the
# clearing account ended up rendering as a negative band on the net worth
# chart. They are all cash, claims on cash, or money in transit.
#   Reconcile account   YNAB clearing account - pension deposits land and leave
#   CC Rewards (TG)     credit-card cash-back balance
#   Tax Payments (EQ)   EQ savings earmarked for tax
#   BBC A/R             receivable owed to the business
#   Bender Books (TG)   business clearing account
#   Glebeholme Expenses old property expense account
CASH_LIKE_PAT = re.compile(r"reconcile|rewards|tax payments|a/r|bender books|glebeholme", re.I)
INVEST_PAT = re.compile(r"tfsa|rrsp|fhsa|invest|resp|gic|trade|hisa|emergency", re.I)
PENSION_PAT = re.compile(r"pension", re.I)
EQUITY_PAT = re.compile(r"equity", re.I)


def account_bucket(name):
    if EQUITY_PAT.search(name):
        return "House equity"
    if DEBT_PAT.search(name):
        return "Credit cards"
    if PENSION_PAT.search(name):
        return "Pensions"
    if INVEST_PAT.search(name):
        return "Investments & savings"
    if CASH_PAT.search(name) or CASH_LIKE_PAT.search(name):
        return "Cash & chequing"
    return "Other"


def month_range(end_key, n):
    y, m = int(end_key[:4]), int(end_key[5:])
    keys = []
    for i in range(n - 1, -1, -1):
        yy, mm = add_months(y, m, -i)
        keys.append("%d-%02d" % (yy, mm))
    return keys


# Comparison windows offered on the Personal Finances tab.
#   id, button label, short label used in column headers / card copy, months
WINDOW_DEFS = [
    ("3m",  "Last 3 months",  "3-mo",  3),
    ("12m", "Last 12 months", "12-mo", 12),
    ("5y",  "Last 5 years",   "5-yr",  60),
]
DEFAULT_WINDOW = "12m"


def blank_month():
    return {"income": 0.0, "spend": 0.0, "housing": 0.0, "saved": 0.0,
            "assigned": 0.0, "spend_ex_housing": 0.0, "net": 0.0,
            "savings_rate": 0.0}


def build_months(plan, reg):
    """Per-month roll-ups. Window-independent, so this runs once."""
    months = {}
    for row in plan:
        b = months.setdefault(row["key"], blank_month())
        g, c = row["group"], row["category"]
        if g in SPEND_GROUPS:
            b["spend"]    += -row["activity"]
            b["assigned"] += row["assigned"]
            if c in HOUSING_CATEGORIES:
                b["housing"] += -row["activity"]
        elif g in SAVING_GROUPS and c not in SAVING_EXCLUDE:
            b["saved"] += -row["activity"]
    for t in reg:
        if t["category"] == "Ready to Assign":
            months.setdefault(t["key"], blank_month())["income"] += t["amount"]

    for b in months.values():
        b["spend_ex_housing"] = b["spend"] - b["housing"]
        b["net"] = b["income"] - b["spend"] - b["saved"]
        b["savings_rate"] = (b["saved"] / b["income"] * 100) if b["income"] > 0 else 0.0
    return months


def build_category_index(plan):
    """category -> {month_key: plan row}, plus category -> group."""
    cat_by_month, cat_meta = {}, {}
    for row in plan:
        if row["group"] not in SPEND_GROUPS and row["group"] not in SAVING_GROUPS:
            continue
        cat_meta[row["category"]] = row["group"]
        cat_by_month.setdefault(row["category"], {})[row["key"]] = row
    return cat_by_month, cat_meta


def window_keys(cur_key, n, earliest):
    """The n month-keys ending at cur_key, clamped to where data actually
    starts so a long window is not deflated by empty pre-history months."""
    keys = [k for k in month_range(cur_key, n) if k >= earliest]
    return keys or [cur_key]


def compute_window(months, cat_by_month, cat_meta, cur_key, keys):
    """Headline stats, category detail and group totals for one window."""
    prev_key = month_range(cur_key, 2)[0]
    yr_ago   = month_range(cur_key, 13)[0]   # same month last year, window-independent

    def mv(key, field):
        return round(months.get(key, blank_month()).get(field, 0.0), 2)

    def vals(field):
        return [months.get(k, blank_month()).get(field, 0.0) for k in keys]

    def stat(field):
        v = vals(field)
        sv = sorted(v)
        n = len(sv)
        median = sv[n // 2] if n % 2 else (sv[n // 2 - 1] + sv[n // 2]) / 2
        return {"cur": mv(cur_key, field), "prev": mv(prev_key, field),
                "yr_ago": mv(yr_ago, field),
                "avg": round(sum(v) / n, 2), "median": round(median, 2),
                "total": round(sum(v), 2)}

    headline = {f: stat(f) for f in
                ("income", "spend", "housing", "spend_ex_housing",
                 "saved", "assigned", "net", "savings_rate")}

    categories = []
    for name, per in cat_by_month.items():
        curr = per.get(cur_key)
        spent_cur = -curr["activity"] if curr else 0.0
        hist = [-per[k]["activity"] for k in keys if k in per]
        avg  = sum(hist) / len(hist) if hist else 0.0
        prev_row, ya_row = per.get(prev_key), per.get(yr_ago)
        if abs(spent_cur) < 0.005 and abs(avg) < 0.005:
            continue
        categories.append({
            "group":     cat_meta[name],
            "category":  name,
            "assigned":  round(curr["assigned"], 2) if curr else 0.0,
            "spent":     round(spent_cur, 2),
            "available": round(curr["available"], 2) if curr else 0.0,
            "prev":      round(-prev_row["activity"], 2) if prev_row else 0.0,
            "yr_ago":    round(-ya_row["activity"], 2) if ya_row else 0.0,
            "avg":       round(avg, 2),
            "vs_avg":    round(spent_cur - avg, 2),
        })
    categories.sort(key=lambda c: -c["spent"])

    groups = {}
    for c in categories:
        g = groups.setdefault(c["group"], {"group": c["group"], "spent": 0.0,
                                           "avg": 0.0, "prev": 0.0})
        g["spent"] += c["spent"]; g["avg"] += c["avg"]; g["prev"] += c["prev"]
    group_rows = sorted([g for g in groups.values()
                         if abs(g["spent"]) >= 1 or abs(g["avg"]) >= 1],
                        key=lambda g: -g["spent"])
    for g in group_rows:
        g["spent"] = round(g["spent"], 2)
        g["avg"]   = round(g["avg"], 2)
        g["prev"]  = round(g["prev"], 2)
        g["vs_avg"] = round(g["spent"] - g["avg"], 2)

    series = {f: [round(months.get(k, blank_month()).get(f, 0.0), 2) for k in keys]
              for f in ("income", "spend", "saved", "net", "housing", "spend_ex_housing")}

    return {"headline": headline, "categories": categories,
            "group_rows": group_rows, "series": series,
            "labels": [label_from_key(k) for k in keys],
            "keys": keys}


STACK_ORDER = ["House equity", "Pensions", "Investments & savings",
               "Cash & chequing", "Other"]


def build_snapshots(reg, cur_key):
    """Account balances rolled forward month by month. Runs once; every
    window slices the same snapshots."""
    per_account = {}
    for t in reg:
        per_account.setdefault(t["account"], {}).setdefault(t["key"], 0.0)
        per_account[t["account"]][t["key"]] += t["amount"]

    all_keys = sorted({t["key"] for t in reg if t["key"] <= cur_key})
    running = {a: 0.0 for a in per_account}
    snapshots = {}
    for k in all_keys:
        for a, by_m in per_account.items():
            running[a] += by_m.get(k, 0.0)
        snapshots[k] = dict(running)
    return snapshots


def _totals(snap):
    assets = debts = 0.0
    for a, v in snap.items():
        if account_bucket(a) == "Credit cards":
            debts += v
        else:
            assets += v
    return round(assets, 2), round(abs(min(debts, 0.0)), 2), round(assets + debts, 2)


def _by_bucket(snap):
    out = {}
    for a, v in snap.items():
        b = account_bucket(a)
        # credit-card balances fold into cash so the stacked areas sum to net
        # worth rather than to gross assets
        if b == "Credit cards":
            b = "Cash & chequing"
        out[b] = out.get(b, 0.0) + v
    return out


def net_worth_window(snapshots, keys):
    """Net worth series + stacked bands for one window."""
    series = []
    for k in keys:
        snap = snapshots.get(k)
        if snap is None:
            series.append({"key": k, "label": label_from_key(k),
                           "assets": 0.0, "debt": 0.0, "net": 0.0, "buckets": {}})
            continue
        a, d, n = _totals(snap)
        series.append({"key": k, "label": label_from_key(k),
                       "assets": a, "debt": d, "net": n,
                       "buckets": {kk: round(vv, 2) for kk, vv in _by_bucket(snap).items()}})

    raw = {name: [round(r["buckets"].get(name, 0.0), 2) for r in series]
           for name in STACK_ORDER}
    # "Other" is a catch-all for accounts no pattern claimed. Fold it into cash
    # when it holds nothing material OR when it ever dips below zero - a
    # negative band is drawn under the axis and visually breaks the whole
    # stack. Either way the bands still total exactly to net worth.
    other = raw["Other"]
    if max((abs(v) for v in other), default=0) < 1000 or any(v < 0 for v in other):
        raw["Cash & chequing"] = [round(c + o, 2) for c, o
                                  in zip(raw["Cash & chequing"], other)]
        raw["Other"] = [0.0] * len(series)
    stack = [{"bucket": name, "values": raw[name]} for name in STACK_ORDER
             if any(abs(v) >= 1 for v in raw[name])]

    empty = {"assets": 0.0, "debt": 0.0, "net": 0.0}
    for r in series:
        r.pop("buckets", None)
    return {"series": series, "stack": stack,
            "now":   series[-1] if series else empty,
            "prev":  series[-2] if len(series) > 1 else empty,
            "start": series[0] if series else empty}


def net_worth_accounts(snapshots, cur_key, prev_key):
    """The account table - always as of cur_key, delta always vs the month
    before, regardless of which comparison window is selected."""
    cur_snap  = snapshots.get(cur_key, {})
    prev_snap = snapshots.get(prev_key, {})
    accounts = []
    for a, v in cur_snap.items():
        if abs(v) < 0.005:
            continue
        accounts.append({"account": a, "bucket": account_bucket(a),
                         "balance": round(v, 2),
                         "delta": round(v - prev_snap.get(a, 0.0), 2)})
    accounts.sort(key=lambda x: -x["balance"])

    buckets = {}
    for a in accounts:
        b = buckets.setdefault(a["bucket"], {"bucket": a["bucket"],
                                             "balance": 0.0, "delta": 0.0})
        b["balance"] += a["balance"]; b["delta"] += a["delta"]
    bucket_rows = sorted(buckets.values(), key=lambda b: -b["balance"])
    for b in bucket_rows:
        b["balance"] = round(b["balance"], 2)
        b["delta"]   = round(b["delta"], 2)
    return accounts, bucket_rows


def compute_transactions(reg, cur_key):
    """Current-month transaction detail. Window-independent."""
    cur = [t for t in reg if t["key"] == cur_key]
    biggest = sorted(({"date": t["date"], "payee": t["payee"] or "(no payee)",
                       "category": t["category"], "account": t["account"],
                       "amount": round(-t["amount"], 2)}
                      for t in cur
                      if t["group"] in SPEND_GROUPS and not t["transfer"] and t["amount"] < 0),
                     key=lambda x: -x["amount"])[:12]
    return {"biggest": biggest, "txn_count": len(cur)}


def income_sources(reg, cur_key, keys):
    """This month's income by payee, averaged over the selected window."""
    inc_cur, inc_hist = {}, {}
    kset = set(keys)
    for t in reg:
        if t["category"] != "Ready to Assign":
            continue
        name = t["payee"] or "(no payee)"
        if t["key"] == cur_key:
            inc_cur[name] = inc_cur.get(name, 0.0) + t["amount"]
        if t["key"] in kset:
            inc_hist[name] = inc_hist.get(name, 0.0) + t["amount"]
    n = len(keys)
    return sorted(
        ({"payee": k, "amount": round(v, 2),
          "avg": round(inc_hist.get(k, 0.0) / n, 2),
          "vs_avg": round(v - inc_hist.get(k, 0.0) / n, 2)}
         for k, v in inc_cur.items() if abs(v) >= 0.005),
        key=lambda x: -x["amount"])


# ---------------------------------------------------------------------------
# PRESENTATION DATA  (the month-in-review walkthrough)
# ---------------------------------------------------------------------------

# Baseline periods offered in the walkthrough. Unlike the dashboard's
# trailing windows, these are the N months BEFORE the month under review.
#   id, button label, phrase used in copy, months
PRES_WINDOWS = [
    ("1m",  "Last month",    "last month",   1),
    ("3m",  "Last 3 months", "3-month",      3),
    ("12m", "Last 12 months", "12-month",    12),
    ("5y",  "Last 5 years",  "5-year",       60),
]
PRES_DEFAULT = "1m"


def compute_presentation(plan, reg, months, cat_by_month, cat_meta,
                         cur_key, house, p, snapshots):
    """Everything the click-through review needs.

    Every baseline here is the N months BEFORE cur_key - never including it.
    Comparing a month against an average that contains itself would be
    circular, which is why these windows differ from the dashboard's
    trailing-inclusive ones."""
    prev_key = month_range(cur_key, 2)[0]
    earliest = min(months) if months else cur_key

    def prior_keys(n):
        keys = [k for k in month_range(prev_key, n) if k >= earliest]
        return keys or [prev_key]

    # ---- per-category and per-payee history, gathered once ---------------
    inc_by_month = {}
    for t in reg:
        if t["category"] != "Ready to Assign":
            continue
        name = t["payee"] or "(no payee)"
        inc_by_month.setdefault(t["key"], {})
        inc_by_month[t["key"]][name] = inc_by_month[t["key"]].get(name, 0.0) + t["amount"]
    inc_cur = inc_by_month.get(cur_key, {})

    def build_baseline(wid, label, short, n):
        keys = prior_keys(n)
        m = len(keys)
        span = (label_from_key(keys[0]) + " - " + label_from_key(keys[-1])
                if m > 1 else label_from_key(keys[0]))
        # the phrase used in copy: "vs Jul 2026" / "vs the 3-month average"
        against = span if m == 1 else ("the " + short + " average")

        def avg_of(field):
            return round(sum(months.get(k, blank_month()).get(field, 0.0)
                             for k in keys) / m, 2)

        streams = []
        names = set(inc_cur)
        for k in keys:
            names |= set(inc_by_month.get(k, {}))
        for name in names:
            cur_v = round(inc_cur.get(name, 0.0), 2)
            avg_v = round(sum(inc_by_month.get(k, {}).get(name, 0.0)
                              for k in keys) / m, 2)
            # only streams that actually paid something this month
            if abs(cur_v) < 0.005:
                continue
            streams.append({"payee": name, "amount": cur_v, "avg": avg_v,
                            "vs_avg": round(cur_v - avg_v, 2),
                            "new": abs(avg_v) < 0.005})
        streams.sort(key=lambda x: -x["amount"])

        saving_rows = []
        for name, per in cat_by_month.items():
            if cat_meta[name] not in SAVING_GROUPS or name in SAVING_EXCLUDE:
                continue
            row = per.get(cur_key)
            cur_v = -row["activity"] if row else 0.0
            prev_row = per.get(prev_key)
            hist = [-per[k]["activity"] for k in keys if k in per]
            avg_v = sum(hist) / len(hist) if hist else 0.0
            if abs(cur_v) < 0.005 and abs(avg_v) < 0.005:
                continue
            saving_rows.append({"category": name, "amount": round(cur_v, 2),
                                "prev": round(-prev_row["activity"], 2) if prev_row else 0.0,
                                "avg": round(avg_v, 2),
                                "vs_avg": round(cur_v - avg_v, 2)})
        saving_rows.sort(key=lambda x: -x["amount"])

        cat_avg = {}
        for name, per in cat_by_month.items():
            hist = [-per[k]["activity"] for k in keys if k in per]
            if hist:
                cat_avg[name] = round(sum(hist) / len(hist), 2)

        nw_keys = keys + [cur_key]
        return {
            "id": wid, "label": label, "short": short, "months": m,
            "span": span, "against": against, "keys": keys,
            "clamped": m < n,
            "nw": net_worth_window(snapshots, nw_keys),
            "nw_span": label_from_key(nw_keys[0]) + " - " + label_from_key(nw_keys[-1]),
            "streams": streams, "saving_rows": saving_rows, "cat_avg": cat_avg,
            "avgs": {f: avg_of(f) for f in
                     ("income", "spend", "saved", "net", "housing",
                      "spend_ex_housing", "savings_rate")},
        }

    baselines = {}
    for wid, label, short, n in PRES_WINDOWS:
        baselines[wid] = build_baseline(wid, label, short, n)

    # ---- budget flags (window-independent) --------------------------------
    overspent, over_assigned = [], []
    for name, per in cat_by_month.items():
        row = per.get(cur_key)
        if not row:
            continue
        spent, assigned, available = -row["activity"], row["assigned"], row["available"]
        entry = {"group": cat_meta[name], "category": name,
                 "spent": round(spent, 2), "assigned": round(assigned, 2),
                 "available": round(available, 2)}
        if available < -0.005:
            entry["over"] = round(-available, 2)
            overspent.append(entry)
        elif spent - assigned > 0.005 and spent > 0:
            entry["over"] = round(spent - assigned, 2)
            over_assigned.append(entry)
    overspent.sort(key=lambda x: -x["over"])
    over_assigned.sort(key=lambda x: -x["over"])

    # ---- transactions behind every category's "spent" ---------------------
    cat_txns = {}
    for t in reg:
        if t["key"] != cur_key or not t["category"]:
            continue
        if t["group"] not in SPEND_GROUPS and t["group"] not in SAVING_GROUPS:
            continue
        cat_txns.setdefault(t["category"], []).append({
            "date": t["date"], "payee": t["payee"] or "(no payee)",
            "memo": t["memo"], "account": t["account"],
            "amount": round(-t["amount"], 2),
        })
    for rows in cat_txns.values():
        rows.sort(key=lambda r: -abs(r["amount"]))

    # net worth at every month end, so the walkthrough can difference any window
    nw_by_key = {}
    for k, snap in snapshots.items():
        nw_by_key[k] = round(sum(snap.values()), 2)

    m = months.get(cur_key, blank_month())
    return {
        "cur_label":   label_from_key(cur_key),
        "prev_label":  label_from_key(prev_key),
        "prev_key":    prev_key,
        "cur_key":     cur_key,
        "window_order": [w[0] for w in PRES_WINDOWS],
        "default_window": PRES_DEFAULT,
        "baselines":   baselines,
        "overspent":   overspent,
        "over_assigned": over_assigned,
        "cat_txns":    cat_txns,
        "nw_by_key":   nw_by_key,
        "cur": {
            "income":  round(m["income"], 2),
            "spend":   round(m["spend"], 2),
            "saved":   round(m["saved"], 2),
            "net":     round(m["net"], 2),
            "housing": round(m["housing"], 2),
            "spend_ex_housing": round(m["spend_ex_housing"], 2),
            "savings_rate": round(m["savings_rate"], 2),
        },
    }


# ---------------------------------------------------------------------------
# HTML TEMPLATE  (plain string + token replace - see CLAUDE.md gotcha #2)
# ---------------------------------------------------------------------------

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>__PRES_MONTH__ review &mdash; 64 Amroth</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  :root{
    --bg:#0f1117; --surface:#1a1d27; --surface2:#222536; --border:#2e3148;
    --accent:#6c8fff; --accent2:#4cd9ac; --accent3:#ff8c6b; --accent4:#f5c242;
    --accent5:#c08cff; --text:#e8eaf0; --muted:#8891aa;
    --positive:#4cd9ac; --negative:#ff6b6b;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--text);padding:24px;max-width:1500px;margin:0 auto}
  h1{font-size:1.55rem;font-weight:700;margin-bottom:4px}
  .subtitle{color:var(--muted);font-size:.83rem;margin-bottom:18px}

  .tabs{display:flex;gap:8px;margin-bottom:22px;border-bottom:1px solid var(--border);padding-bottom:0}
  .tabs button{background:transparent;border:none;border-bottom:2px solid transparent;color:var(--muted);
    font-size:.92rem;font-weight:600;padding:10px 18px;cursor:pointer;font-family:inherit}
  .tabs button:hover{color:var(--text)}
  .tabs button.active{color:var(--accent);border-bottom-color:var(--accent)}
  .page{display:none} .page.active{display:block}

  .banner{background:linear-gradient(90deg,rgba(108,143,255,.13),rgba(76,217,172,.06));
    border:1px solid var(--border);border-left:3px solid var(--accent);border-radius:10px;
    padding:13px 18px;margin-bottom:20px;font-size:.88rem;line-height:1.55}
  .banner strong{color:var(--accent2)}

  .grid{display:grid;gap:15px;margin-bottom:20px}
  .g4{grid-template-columns:repeat(auto-fit,minmax(240px,1fr))}
  .g3{grid-template-columns:repeat(auto-fit,minmax(290px,1fr))}
  .g2{grid-template-columns:repeat(auto-fit,minmax(560px,1fr))}
  .g6{grid-template-columns:repeat(auto-fit,minmax(165px,1fr))}

  .card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:18px 20px}
  .card.hero{border-top:3px solid var(--accent)}
  .card-label{font-size:.7rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:8px;font-weight:600}
  .card-value{font-size:1.65rem;font-weight:700;line-height:1.15}
  .card-value.sm{font-size:1.25rem}
  .card-sub{font-size:.77rem;color:var(--muted);margin-top:8px;line-height:1.55}
  .delta{font-weight:700}
  .good{color:var(--positive)} .bad{color:var(--negative)} .neutral{color:var(--muted)}

  .chart-card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:18px 20px}
  .chart-title{font-size:.75rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:14px}
  .chart-wrap{position:relative;height:290px}
  .chart-wrap.tall{height:340px}

  .section-title{font-size:.72rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:12px;font-weight:700}
  .section-head{font-size:1.02rem;font-weight:700;margin:28px 0 14px;padding-bottom:8px;border-bottom:1px solid var(--border)}

  table{width:100%;border-collapse:collapse;font-size:.82rem}
  th{text-align:right;padding:8px 10px;color:var(--muted);font-weight:600;border-bottom:1px solid var(--border);
     font-size:.68rem;text-transform:uppercase;letter-spacing:.06em;position:sticky;top:0;background:var(--surface);z-index:1}
  th:first-child,td:first-child{text-align:left}
  td{padding:7px 10px;border-bottom:1px solid var(--border);text-align:right;white-space:nowrap}
  tbody tr:last-child td{border-bottom:none}
  tbody tr:hover td{background:rgba(108,143,255,.05)}
  tr.total-row td{font-weight:700;background:var(--surface2)}
  .table-scroll{max-height:430px;overflow:auto}
  .muted-cell{color:var(--muted)}
  .tag{display:inline-block;font-size:.62rem;padding:2px 7px;border-radius:20px;font-weight:700;letter-spacing:.03em}
  .tag-g{background:rgba(76,217,172,.15);color:var(--accent2)}
  .tag-b{background:rgba(255,107,107,.15);color:var(--negative)}
  .tag-n{background:rgba(136,145,170,.15);color:var(--muted)}

  .winbar{display:flex;gap:7px;align-items:center;flex-wrap:wrap;background:var(--surface);
    border:1px solid var(--border);border-radius:12px;padding:12px 16px;margin-bottom:18px}
  .winbar .wlbl{font-size:.7rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);font-weight:700;margin-right:4px}
  .winbar button{background:var(--surface2);border:1px solid var(--border);color:var(--muted);font-family:inherit;
    font-size:.8rem;font-weight:600;padding:7px 15px;border-radius:8px;cursor:pointer}
  .winbar button:hover{color:var(--text);border-color:var(--accent)}
  .winbar button.active{background:rgba(108,143,255,.16);border-color:var(--accent);color:var(--accent)}
  .winbar .wspan{font-size:.74rem;color:var(--muted);margin-left:auto;text-align:right}

  .bar-track{height:8px;background:var(--surface2);border-radius:6px;overflow:hidden;margin-top:10px}
  .bar-fill{height:100%;background:linear-gradient(90deg,var(--accent),var(--accent2));border-radius:6px}

  /* ---------- presentation walkthrough ---------- */
  #pres{position:fixed;inset:0;background:var(--bg);z-index:60;display:flex;flex-direction:column}
  .pres-top{display:flex;align-items:center;gap:16px;padding:14px 26px;border-bottom:1px solid var(--border);flex:0 0 auto}
  .pres-title{font-size:.78rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);white-space:nowrap}
  .pres-dots{display:flex;gap:5px;flex:1 1 auto;flex-wrap:wrap}
  .pres-dots span{width:30px;height:4px;border-radius:3px;background:var(--surface2);cursor:pointer;transition:background .2s}
  .pres-dots span:hover{background:var(--border)}
  .pres-dots span.done{background:#3a3f5c}
  .pres-dots span.on{background:var(--accent)}
  .skip-btn{background:var(--surface2);border:1px solid var(--border);color:var(--muted);font-family:inherit;
    font-size:.78rem;font-weight:600;padding:7px 14px;border-radius:8px;cursor:pointer;white-space:nowrap}
  .skip-btn:hover{color:var(--accent);border-color:var(--accent)}
  .pres-stage{flex:1 1 auto;overflow-y:auto;padding:28px 26px 24px}
  .slide{display:none;max-width:1200px;margin:0 auto}
  .slide.on{display:block;animation:slideIn .32s ease both}
  @keyframes slideIn{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}
  .slide-kicker{font-size:.68rem;text-transform:uppercase;letter-spacing:.16em;color:var(--accent);font-weight:700;margin-bottom:9px}
  .slide-h{font-size:1.85rem;font-weight:700;line-height:1.15;margin-bottom:11px}
  .slide-lede{font-size:.93rem;color:var(--muted);line-height:1.65;margin-bottom:24px;max-width:900px}
  .slide-lede strong{color:var(--text);font-weight:600}
  .pres-nav{flex:0 0 auto;display:flex;align-items:center;justify-content:center;gap:18px;
    padding:13px 26px;border-top:1px solid var(--border)}
  .nav-btn{background:var(--surface2);border:1px solid var(--border);color:var(--text);font-family:inherit;
    font-size:.85rem;font-weight:600;padding:9px 22px;border-radius:9px;cursor:pointer}
  .nav-btn:hover:not(:disabled){border-color:var(--accent);color:var(--accent)}
  .nav-btn:disabled{opacity:.35;cursor:default}
  .nav-btn.primary{background:var(--accent);border-color:var(--accent);color:#0f1117}
  .nav-btn.primary:hover{opacity:.9;color:#0f1117}
  .nav-step{font-size:.78rem;color:var(--muted);min-width:64px;text-align:center}

  .big-stat{font-size:2.5rem;font-weight:700;line-height:1.1}
  .big-stat.sm{font-size:1.9rem}
  .flag{border-radius:12px;padding:16px 18px;border:1px solid var(--border);background:var(--surface)}
  .flag.red{border-left:3px solid var(--negative);background:rgba(255,107,107,.06)}
  .flag.amber{border-left:3px solid var(--accent4);background:rgba(245,194,66,.06)}
  .flag.green{border-left:3px solid var(--positive);background:rgba(76,217,172,.06)}
  .flag-top{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin-bottom:5px}
  .flag-name{font-weight:700;font-size:.95rem}
  .flag-amt{font-weight:700;font-size:1.05rem}
  .flag-sub{font-size:.76rem;color:var(--muted);line-height:1.5}

  tr.drill{cursor:pointer}
  tr.drill:hover td{background:rgba(108,143,255,.09)}
  tr.drill td:first-child::after{content:' ▸';color:var(--muted);font-size:.75rem}
  tr.drill.open td:first-child::after{content:' ▾';color:var(--accent)}
  tr.drill-body>td{padding:0;background:var(--bg)}
  .drill-wrap{padding:10px 14px 14px 30px}
  .drill-wrap table{font-size:.78rem}
  .drill-wrap th{background:var(--bg);font-size:.64rem}
  .drill-foot{font-size:.74rem;color:var(--muted);padding:8px 4px 0;border-top:1px solid var(--border);margin-top:4px}
  .notes{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:18px 20px;margin-top:18px}
  .notes ul{list-style:none;display:grid;grid-template-columns:repeat(2,1fr);gap:7px 26px}
  .notes li{font-size:.78rem;color:var(--muted);line-height:1.5}
  .notes li strong{color:var(--text)}
  @media(max-width:820px){.notes ul{grid-template-columns:1fr}}
</style>
</head>
<body>
"""

TEMPLATE += """
<div id="pres" style="display:none">
  <div class="pres-top">
    <span class="pres-title" id="pres-month">Month in review</span>
    <span class="pres-dots" id="pres-dots"></span>
    <button class="skip-btn" id="pres-skip">Skip to dashboard &rarr;</button>
  </div>

  <div class="pres-stage" id="pres-stage">

    <section class="slide" data-i="0">
      <div class="slide-kicker">Month in review</div>
      <div class="slide-h" id="s0-title">&mdash;</div>
      <div class="slide-lede" id="s0-lede">&mdash;</div>
      <div data-winbar></div>
      <div class="grid g4" id="s0-cards"></div>
    </section>

    <section class="slide" data-i="1">
      <div class="slide-kicker">Step 1 &middot; Money in</div>
      <div class="slide-h">Where the money came from</div>
      <div class="slide-lede" id="s1-lede">&mdash;</div>
      <div data-winbar></div>
      <div class="grid g2">
        <div class="chart-card"><div class="chart-title" id="s1-chart-title">Revenue streams</div>
          <div class="chart-wrap tall"><canvas id="c-streams"></canvas></div></div>
        <div class="card"><div class="section-title">Every stream</div>
          <div class="table-scroll"><table><thead><tr>
            <th>Source</th><th id="s1-cur-h">This month</th><th id="s1-avg-h">Average</th><th>vs average</th>
          </tr></thead><tbody id="s1-body"></tbody></table></div></div>
      </div>
    </section>

    <section class="slide" data-i="2">
      <div class="slide-kicker">Step 2 &middot; Budget</div>
      <div class="slide-h">What blew through the budget</div>
      <div class="slide-lede" id="s2-lede">&mdash;</div>
      <div id="s2-over"></div>
    </section>

    <section class="slide" data-i="3">
      <div class="slide-kicker">Step 3 &middot; Budget</div>
      <div class="slide-h">The biggest line items</div>
      <div class="slide-lede" id="s3-lede">&mdash;</div>
      <div class="card"><table><thead><tr>
        <th>Date</th><th>Payee</th><th>Category</th><th>Account</th><th>Amount</th><th>Share of spend</th>
      </tr></thead><tbody id="s3-body"></tbody></table></div>
    </section>

    <section class="slide" data-i="4">
      <div class="slide-kicker">Step 4 &middot; Budget</div>
      <div class="slide-h">The whole breakdown</div>
      <div class="slide-lede" id="s4-lede">&mdash;</div>
      <div data-winbar></div>
      <div class="card"><table><thead><tr>
        <th>Group / category</th><th>Assigned</th><th>Spent</th>
        <th id="s4-prev-h">Last month</th><th id="s4-vs-h">vs average</th>
        <th>Available</th><th>Items</th>
      </tr></thead><tbody id="s4-body"></tbody></table></div>
    </section>

    <section class="slide" data-i="5">
      <div class="slide-kicker">Step 5 &middot; Saving</div>
      <div class="slide-h">What we put away</div>
      <div class="slide-lede" id="s5-lede">&mdash;</div>
      <div data-winbar></div>
      <div class="grid g4" id="s5-cards"></div>
      <div class="grid g2">
        <div class="card"><div class="section-title">Where it went</div>
          <table><thead id="s5-head"></thead><tbody id="s5-body"></tbody></table></div>
        <div class="card"><div class="section-title">TFSA &mdash; earmarked for the buyout</div>
          <div id="s5-tfsa"></div></div>
      </div>
    </section>

    <section class="slide" data-i="6">
      <div class="slide-kicker">Step 6 &middot; The house</div>
      <div class="slide-h">64 Amroth</div>
      <div class="slide-lede" id="s6-lede">&mdash;</div>
      <div data-winbar></div>
      <div class="section-title">What moved in <span id="s6-month">this month</span></div>
      <div class="grid g3" id="s6-cards"></div>
      <div class="section-title">Where it stands</div>
      <div class="grid g4" id="s6-cards2"></div>
    </section>

    <section class="slide" data-i="7">
      <div class="slide-kicker">Step 7 &middot; Net worth</div>
      <div class="slide-h">What it all adds up to</div>
      <div class="slide-lede" id="s7-lede">&mdash;</div>
      <div data-winbar></div>
      <div class="grid g2">
        <div class="chart-card"><div class="chart-title" id="s7-chart-title">Net worth</div>
          <div class="chart-wrap tall"><canvas id="c-pres-nw"></canvas></div></div>
        <div class="card"><div class="section-title">What it is made of</div>
          <table><thead><tr><th>Type</th><th>Balance</th><th>Share</th>
            <th id="s7-vs-h">Change</th></tr></thead>
          <tbody id="s7-body"></tbody></table></div>
      </div>
    </section>

    <section class="slide" data-i="8">
      <div class="slide-kicker">That is the month</div>
      <div class="slide-h" id="s8-title">&mdash;</div>
      <div class="slide-lede" id="s8-lede">&mdash;</div>
      <div data-winbar></div>
      <div class="grid g4" id="s8-cards"></div>
      <div style="text-align:center;margin-top:34px">
        <button class="nav-btn primary" id="s8-open" style="font-size:.95rem;padding:13px 30px">
          Open the full dashboard &rarr;</button>
      </div>
    </section>

  </div>

  <div class="pres-nav">
    <button class="nav-btn" id="pres-prev">&larr; Back</button>
    <span class="nav-step" id="pres-step">1 / 9</span>
    <button class="nav-btn primary" id="pres-next">Next &rarr;</button>
  </div>
</div>

<div id="dashboard">

<h1>&#128200; Bender Dashboard <span style="color:var(--muted);font-weight:400">v3</span></h1>
<p class="subtitle">64 Amroth &amp; household finances &nbsp;&middot;&nbsp; Generated __GENERATED__</p>
<button class="nav-btn primary" id="replay-link" style="margin-bottom:20px">&#9654;&nbsp; Review __PRES_MONTH__ &mdash; guided walkthrough</button>

<nav class="tabs">
  <button data-tab="money" class="active">&#128176;&nbsp; Personal Finances</button>
  <button data-tab="house">&#127968;&nbsp; House &amp; Mortgage</button>
</nav>

<!-- ================= HOUSE ================= -->
<section class="page" id="page-house">

  <div class="banner" id="house-banner">&mdash;</div>

  <div class="section-title">This month vs last month</div>
  <div class="grid g4" id="house-hero"></div>

  <div class="section-title">Cumulative progress</div>
  <div class="grid g4" id="house-cum"></div>

  <div class="card" style="margin-bottom:20px">
    <div class="section-title">Month-over-month detail</div>
    <table><thead><tr>
      <th>Metric</th><th id="mom-prev-h">Last month</th><th id="mom-cur-h">This month</th><th>Change</th>
    </tr></thead><tbody id="mom-body"></tbody></table>
  </div>

  <div class="chart-card" style="margin-bottom:20px">
    <div class="chart-title">Bender principal gained each month &mdash; scheduled, extra &amp; partnership transfer</div>
    <div class="chart-wrap tall"><canvas id="c-principal"></canvas></div>
  </div>

  <div class="grid g2">
    <div class="chart-card"><div class="chart-title">Projected payoff date &mdash; where each month's balance says the mortgage ends</div>
      <div class="chart-wrap"><canvas id="c-payoff"></canvas></div></div>
    <div class="chart-card"><div class="chart-title">Bender equity &mdash; actual vs. no-extra-payments baseline</div>
      <div class="chart-wrap"><canvas id="c-equity"></canvas></div></div>
  </div>

  <div class="grid g2">
    <div class="chart-card"><div class="chart-title">Remaining amortization (months left)</div>
      <div class="chart-wrap"><canvas id="c-amort"></canvas></div></div>
    <div class="chart-card"><div class="chart-title">Sub-account balances &mdash; Bender vs Martin</div>
      <div class="chart-wrap"><canvas id="c-balances"></canvas></div></div>
  </div>

  <div class="section-head">Buyout snapshot &mdash; if the Benders bought out the Martins today</div>
  <div class="grid g6" id="buyout-cards"></div>
  <div class="grid g3">
    <div class="card"><div class="card-label">Monthly outlay today</div>
      <div class="card-value sm" id="b-net-now">&mdash;</div>
      <div class="card-sub" id="b-net-now-sub">&mdash;</div></div>
    <div class="card"><div class="card-label">Monthly outlay after buyout</div>
      <div class="card-value sm" id="b-net-after">&mdash;</div>
      <div class="card-sub" id="b-net-after-sub">&mdash;</div></div>
    <div class="card"><div class="card-label">Cash saved toward closing (TFSAs)</div>
      <div class="card-value sm" id="b-tfsa">&mdash;</div>
      <div class="card-sub" id="b-tfsa-sub">&mdash;</div>
      <div class="bar-track"><div class="bar-fill" id="b-tfsa-bar" style="width:0%"></div></div></div>
  </div>

  <div class="card" style="margin-top:20px">
    <div class="section-title">Payment history (actual months, newest first)</div>
    <div class="table-scroll"><table><thead><tr>
      <th>Month</th><th>Bender balance</th><th>Equity</th><th>Interest</th>
      <th>Scheduled principal</th><th>Extra</th><th>Transfer (half)</th>
      <th>Total principal gained</th><th>Months left</th><th>TFSA</th>
    </tr></thead><tbody id="hist-body"></tbody></table></div>
  </div>

  <div class="notes"><div class="section-title">How these numbers are built</div>
    <ul id="house-notes"></ul></div>
</section>
"""

TEMPLATE += """
<!-- ================= MONEY ================= -->
<section class="page active" id="page-money">

  <div class="winbar">
    <span class="wlbl">Compare against</span>
    <span id="win-buttons"></span>
    <span class="wspan" id="win-span">&mdash;</span>
  </div>

  <div class="banner" id="money-banner">&mdash;</div>

  <div class="section-title">The month at a glance</div>
  <div class="grid g4" id="money-hero"></div>

  <div class="section-title">Where it went &amp; what is left</div>
  <div class="grid g4" id="money-second"></div>

  <div class="card" style="margin-bottom:20px">
    <div class="section-title">Income sources &mdash; <span id="inc-month">this month</span></div>
    <table><thead><tr>
      <th>Source</th><th>This month</th><th id="inc-avg-h">Average</th><th>vs average</th>
    </tr></thead><tbody id="inc-body"></tbody></table>
  </div>

  <div class="grid g2">
    <div class="chart-card"><div class="chart-title" id="flow-title">Income, spending &amp; saving</div>
      <div class="chart-wrap tall"><canvas id="c-flow"></canvas></div></div>
    <div class="chart-card"><div class="chart-title" id="nw-title">Net worth, by what it is made of</div>
      <div class="chart-wrap tall"><canvas id="c-nw"></canvas></div></div>
  </div>

  <div class="section-head">Budget detail &mdash; <span id="budget-month">this month</span>
    <span style="font-size:.74rem;font-weight:400;color:var(--muted)">&nbsp;&nbsp;click a category to see its transactions</span></div>
  <div class="card">
    <div class="table-scroll"><table><thead><tr>
      <th>Group / category</th><th></th><th>Assigned</th><th>Spent</th><th>Available</th>
      <th>Last month</th><th id="cat-avg-h">Average</th><th>vs avg</th><th>Same month last yr</th>
    </tr></thead><tbody id="cat-body"></tbody></table></div>
  </div>

  <div class="grid g2" style="margin-top:20px">
    <div class="card"><div class="section-title">Largest single transactions this month</div>
      <div class="table-scroll"><table><thead><tr>
        <th>Date</th><th>Payee</th><th>Category</th><th>Amount</th>
      </tr></thead><tbody id="big-body"></tbody></table></div></div>
    <div class="card"><div class="section-title">Net worth by account</div>
      <div class="table-scroll"><table><thead><tr>
        <th>Account</th><th></th><th>Balance</th><th>Change vs last mo</th>
      </tr></thead><tbody id="acct-body"></tbody></table></div></div>
  </div>

  <div class="notes"><div class="section-title">How these numbers are built</div>
    <ul id="money-notes"></ul></div>
</section>

</div><!-- /#dashboard -->

<script>
const D = __DATA_JSON__;
</script>
"""

TEMPLATE += r"""
<script>
// ---------- helpers ----------
function fm(n, dp) {
  dp = dp || 0;
  if (n === null || n === undefined || isNaN(n)) return '&mdash;';
  var s = Math.abs(n).toLocaleString('en-CA', {minimumFractionDigits: dp, maximumFractionDigits: dp});
  return (n < 0 ? '-$' : '$') + s;
}
function pc(n, dp) { dp = (dp === undefined) ? 1 : dp; return (n === null || isNaN(n)) ? '&mdash;' : n.toFixed(dp) + '%'; }
function sg(n) { return n > 0 ? '+' : ''; }
// goodIsUp=true  -> a positive delta is good (equity, income, savings)
// goodIsUp=false -> a negative delta is good (debt, spending)
function dcls(n, goodIsUp) {
  if (Math.abs(n) < 0.005) return 'neutral';
  var good = goodIsUp ? n > 0 : n < 0;
  return good ? 'good' : 'bad';
}
function dspan(n, goodIsUp, dp) {
  return '<span class="delta ' + dcls(n, goodIsUp) + '">' + sg(n) + fm(n, dp) + '</span>';
}
function dspanPct(n, goodIsUp, dp) {
  return '<span class="delta ' + dcls(n, goodIsUp) + '">' + sg(n) + pc(n, dp) + '</span>';
}
var MONTH_NAMES = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
var DAYS_PER_MONTH = 365.25 / 12;
// The shaved figure is a fraction of an amortization period; one period is one
// monthly payment, so a period converts to the average calendar month.
function days(n) {
  if (n === null || n === undefined || isNaN(n)) return '&mdash;';
  var d = Math.round(n * DAYS_PER_MONTH);
  return d + ' day' + (Math.abs(d) === 1 ? '' : 's');
}
// fractional "months since year 0" -> "Mon YYYY"
function monthIdxLabel(v) {
  var w = Math.round(v);
  return MONTH_NAMES[((w % 12) + 12) % 12] + ' ' + Math.floor(w / 12);
}
function mos(n) {
  if (n === null || n === undefined) return '&mdash;';
  var a = Math.abs(n), sign = n < 0 ? '-' : '';
  if (a < 12) {
    var v = Math.round(a * 10) / 10;
    return sign + (v % 1 === 0 ? v.toFixed(0) : v.toFixed(1)) + ' mo';
  }
  var w = Math.round(a), y = Math.floor(w / 12), m = w % 12;
  return sign + y + ' yr' + (m ? ' ' + m + ' mo' : '');
}
function card(label, value, sub, color, hero) {
  return '<div class="card' + (hero ? ' hero' : '') + '">'
    + '<div class="card-label">' + label + '</div>'
    + '<div class="card-value" style="color:' + (color || 'var(--text)') + '">' + value + '</div>'
    + '<div class="card-sub">' + sub + '</div></div>';
}
function td(v, cls) { return '<td' + (cls ? ' class="' + cls + '"' : '') + '>' + v + '</td>'; }
function fill(id, html) { var el = document.getElementById(id); if (el) el.innerHTML = html; }

// ---------- tabs ----------
document.querySelectorAll('.tabs button').forEach(function (b) {
  b.addEventListener('click', function () {
    document.querySelectorAll('.tabs button').forEach(function (x) { x.classList.remove('active'); });
    document.querySelectorAll('.page').forEach(function (x) { x.classList.remove('active'); });
    b.classList.add('active');
    document.getElementById('page-' + b.dataset.tab).classList.add('active');
    Object.values(CHARTS).forEach(function (c) { if (c) c.resize(); });
  });
});

// ---------- chart defaults ----------
var CHARTS = {};
Chart.defaults.color = '#8891aa';
Chart.defaults.borderColor = '#2e3148';
Chart.defaults.font.family = "'Segoe UI', system-ui, sans-serif";
Chart.defaults.font.size = 11;
var C = {accent: '#6c8fff', accent2: '#4cd9ac', accent3: '#ff8c6b', accent4: '#f5c242',
         accent5: '#c08cff', muted: '#8891aa', neg: '#ff6b6b'};
function moneyTick(v) {
  var a = Math.abs(v), sign = v < 0 ? '-' : '';
  return sign + '$' + (a >= 1000 ? (a / 1000).toFixed(a >= 10000 ? 0 : 1).replace('.0', '') + 'k' : a.toFixed(0));
}
var GRID = {grid: {color: 'rgba(46,49,72,.6)'}};
</script>
"""

TEMPLATE += r"""
<script>
// =========================== HOUSE PAGE ===========================
var H = D.house, B = H.buyout;

fill('house-banner',
  '<strong>' + H.cur_label + '</strong> vs <strong>' + H.prev_label + '</strong> &nbsp;&middot;&nbsp; '
  + 'One more month of payments moved Bender equity by ' + dspan(H.equity_delta, true)
  + ' and the extra principal alone cut ' + '<span class="delta ' + dcls(H.shaved_mom, true) + '">'
  + days(H.shaved_mom) + '</span> off the remaining term. '
  + H.months_elapsed + ' months of real payments are on the books.');

fill('house-hero',
  card('Bender equity', fm(H.equity),
       dspan(H.equity_delta, true) + ' vs ' + H.prev_label + '<br>'
       + pc(H.equity_pct) + ' of the ' + fm(H.half_value) + ' Bender half (was ' + pc(H.equity_pct_prev) + ')',
       'var(--accent2)', true)
+ card('Extra amortization shaved',
       '<span class="' + dcls(H.shaved_mom, true) + '">' + days(H.shaved_mom) + '</span>',
       'Bought by the extra principal alone &mdash; the scheduled payment is excluded<br>Term left: '
       + mos(H.remaining) + ' &nbsp;(was ' + mos(H.remaining_prev) + ')',
       'var(--accent4)', true)
+ card('Principal gained', fm(H.principal_total),
       fm(H.base_prin) + ' scheduled &middot; ' + fm(H.extra) + ' extra'
       + (H.transfer ? ' &middot; ' + fm(H.transfer) + ' transfer' : '')
       + '<br>' + dspan(H.principal_delta, true) + ' vs ' + H.prev_label
       + ' (' + fm(H.principal_total_prev) + ')',
       'var(--accent)', true)
+ card('Cash saved toward buyout',
       '<span class="' + dcls(H.tfsa_delta, true) + '">' + sg(H.tfsa_delta) + fm(H.tfsa_delta) + '</span>',
       'Added in ' + H.tfsa_label + ' (vs ' + H.tfsa_prev_label + ')<br>'
       + fm(H.tfsa) + ' saved in total &mdash; '
       + pc(B.cash_at_closing > 0 ? H.tfsa / B.cash_at_closing * 100 : 0)
       + ' of the ' + fm(B.cash_at_closing) + ' needed at closing',
       'var(--accent5)', true));

fill('house-cum',
  card('Payoff date', H.payoff,
       'Baseline with no extra payments: ' + H.payoff_base + '<br>'
       + '<span class="' + dcls(H.shaved_total, true) + '">' + mos(H.shaved_total) + '</span> ahead of baseline'
       + (H.shaved_total_prev !== null ? ' (was ' + mos(H.shaved_total_prev) + ' last month)' : ''),
       'var(--accent2)')
+ card('Interest saved to date', fm(H.interest_saved),
       dspan(H.interest_saved_delta, true) + ' added this month<br>'
       + 'vs paying only the scheduled payment since day one', 'var(--accent2)')
+ card('Interest paid this month', fm(H.interest_month),
       dspan(H.interest_month_delta, false) + ' vs ' + H.prev_label + '<br>'
       + 'Bender share only, at ' + pc(D.params.rate_pct, 2) + ' annual', 'var(--accent3)')
+ card('Bender mortgage balance', fm(H.b_end),
       dspan(H.b_end_delta, false) + ' vs ' + H.prev_label + '<br>'
       + fm(H.all_in) + ' all-in to own the house outright '
       + '(Bender mortgage + the Martins&rsquo; half at ' + fm(B.martin_share) + ')',
       'var(--text)'));

// ---- month-over-month table ----
document.getElementById('mom-prev-h').textContent = H.prev_label;
document.getElementById('mom-cur-h').textContent  = H.cur_label;
function momRow(label, prev, cur, fmt, goodIsUp, deltaFmt) {
  var delta = (typeof cur === 'number' && typeof prev === 'number') ? cur - prev : null;
  var dHtml = '&mdash;';
  if (delta !== null) {
    dHtml = '<span class="delta ' + dcls(delta, goodIsUp) + '">' + sg(delta) + (deltaFmt || fmt)(delta) + '</span>';
  }
  return '<tr>' + td(label) + td(typeof prev === 'number' ? fmt(prev) : prev, 'muted-cell')
       + td(typeof cur === 'number' ? fmt(cur) : cur) + td(dHtml) + '</tr>';
}
var f0 = function (v) { return fm(v, 0); };
var f2 = function (v) { return fm(v, 2); };
var fpc = function (v) { return pc(v, 2); };
var fmo = function (v) { return mos(v); };
var momHtml =
    momRow('Bender equity', H.equity_prev, H.equity, f0, true)
  + momRow('Equity as % of Bender half', H.equity_pct_prev, H.equity_pct, fpc, true)
  + momRow('Bender mortgage balance', H.b_end_prev, H.b_end, f0, false)
  + momRow('All-in to own outright (Bender + Martin half)', H.all_in_prev, H.all_in, f0, false)
  + momRow('Interest paid (Bender share)', H.interest_month_prev, H.interest_month, f2, false)
  + momRow('Scheduled principal', H.base_prin_prev, H.base_prin, f2, true)
  + momRow('Extra principal payment', H.extra_prev, H.extra, f0, true)
  + momRow('Total principal gained', H.principal_total_prev, H.principal_total, f2, true)
  + momRow('Months of amortization left', H.remaining_prev, H.remaining, fmo, false)
  + '<tr>' + td('Projected payoff') + td(H.payoff_prev, 'muted-cell') + td(H.payoff)
      + td('<span class="delta ' + dcls(H.payoff_earlier, true) + '">' + mos(H.payoff_earlier) + ' earlier</span>') + '</tr>'
  + momRow('Total time shaved vs baseline', H.shaved_total_prev, H.shaved_total, fmo, true)
  + momRow('Interest saved to date', H.interest_saved_prev, H.interest_saved, f2, true)
  + momRow('TFSA saved for buyout (' + H.tfsa_prev_label + ' &rarr; ' + H.tfsa_label + ')', H.tfsa_prev, H.tfsa, f0, true);
fill('mom-body', momHtml);
</script>
"""

TEMPLATE += r"""
<script>
// ---- house charts ----
var S = H.series, SL = S.map(function (r) { return r.label; });
function ds(label, data, color, opts) {
  return Object.assign({label: label, data: data, borderColor: color, backgroundColor: color,
    borderWidth: 2, pointRadius: 0, tension: .25}, opts || {});
}
var lineOpts = {responsive: true, maintainAspectRatio: false,
  interaction: {mode: 'index', intersect: false},
  plugins: {legend: {labels: {boxWidth: 10, boxHeight: 10, usePointStyle: true}}},
  scales: {x: GRID, y: Object.assign({ticks: {callback: moneyTick}}, GRID)}};

// Payoff dates are plotted as "months since year 0" (~24,600), so Chart.js's
// default tick stepping lands almost nothing inside the data's ~30-month span.
// Bound the axis to the data and step in whole half-years.
var PV = S.map(function (r) { return r.payoff_idx; })
          .concat(S.map(function (r) { return r.base_payoff_idx; }))
          .filter(function (v) { return v !== null && v !== undefined; });
var pLo = Math.min.apply(null, PV), pHi = Math.max.apply(null, PV);
var pSpan = pHi - pLo;
var pStep = pSpan <= 30 ? 6 : (pSpan <= 72 ? 12 : 24);
var pPad  = Math.max(1, pSpan * 0.08);
var pMin  = Math.floor((pLo - pPad) / pStep) * pStep;
var pMax  = Math.ceil((pHi + pPad) / pStep) * pStep;

CHARTS.payoff = new Chart(document.getElementById('c-payoff'), {type: 'line', data: {labels: SL, datasets: [
  ds('Projected payoff', S.map(function (r) { return r.payoff_idx; }), C.accent2,
     {stepped: false, pointRadius: 2}),
  ds('If no extras had ever been paid', S.map(function (r) { return r.base_payoff_idx; }), C.muted,
     {borderDash: [5, 4]})
]}, options: {responsive: true, maintainAspectRatio: false,
  interaction: {mode: 'index', intersect: false},
  plugins: {legend: {labels: {boxWidth: 10, boxHeight: 10, usePointStyle: true}},
    tooltip: {callbacks: {label: function (c) {
      return c.dataset.label + ': ' + monthIdxLabel(c.parsed.y);
    }}}},
  scales: {x: GRID,
           y: Object.assign({min: pMin, max: pMax,
                             ticks: {stepSize: pStep,
                                     callback: function (v) { return monthIdxLabel(v); }}}, GRID)}}});

CHARTS.equity = new Chart(document.getElementById('c-equity'), {type: 'line', data: {labels: SL, datasets: [
  ds('Actual equity', S.map(function (r) { return r.equity; }), C.accent2,
     {fill: true, backgroundColor: 'rgba(76,217,172,.10)'}),
  ds('No-extras baseline', S.map(function (r) { return r.base_equity; }), C.muted, {borderDash: [5, 4]})
]}, options: lineOpts});

CHARTS.amort = new Chart(document.getElementById('c-amort'), {type: 'line', data: {labels: SL, datasets: [
  ds('Months left (actual)', S.map(function (r) { return r.remaining; }), C.accent4),
  ds('Months left (baseline)', S.map(function (r) { return r.base_remaining; }), C.muted, {borderDash: [5, 4]})
]}, options: {responsive: true, maintainAspectRatio: false,
  interaction: {mode: 'index', intersect: false},
  plugins: {legend: {labels: {boxWidth: 10, boxHeight: 10, usePointStyle: true}},
    tooltip: {callbacks: {label: function (c) { return c.dataset.label + ': ' + mos(c.parsed.y).replace('&nbsp;', ' '); }}}},
  scales: {x: GRID, y: Object.assign({ticks: {callback: function (v) { return v + ' mo'; }}}, GRID)}}});

CHARTS.principal = new Chart(document.getElementById('c-principal'), {type: 'bar', data: {labels: SL, datasets: [
  {label: 'Scheduled principal (Bender)', data: S.map(function (r) { return r.b_prin; }), backgroundColor: C.accent},
  {label: 'Extra payment (Bender)', data: S.map(function (r) { return r.b_extra; }), backgroundColor: C.accent2},
  {label: 'Partnership transfer (Bender half)', data: S.map(function (r) { return r.b_transfer; }), backgroundColor: C.accent5}
]}, options: {responsive: true, maintainAspectRatio: false,
  interaction: {mode: 'index', intersect: false},
  plugins: {legend: {labels: {boxWidth: 10, boxHeight: 10, usePointStyle: true}},
    tooltip: {callbacks: {footer: function (items) {
      return 'Total gained: ' + fm(items.reduce(function (a, i) { return a + i.parsed.y; }, 0), 2);
    }}}},
  scales: {x: Object.assign({stacked: true}, GRID),
           y: Object.assign({stacked: true, ticks: {callback: moneyTick}}, GRID)}}});

CHARTS.balances = new Chart(document.getElementById('c-balances'), {type: 'line', data: {labels: SL, datasets: [
  ds('Bender', S.map(function (r) { return r.b_end; }), C.accent),
  ds('Martin', S.map(function (r) { return r.m_end; }), C.accent3)
]}, options: lineOpts});

// ---- buyout cards ----
function mini(label, value, color) {
  return '<div class="card" style="padding:15px 16px"><div class="card-label">' + label + '</div>'
    + '<div class="card-value" style="font-size:1.12rem;color:' + (color || 'var(--text)') + '">' + value + '</div></div>';
}
fill('buyout-cards',
  mini('Martin 50% share', fm(B.martin_share))
+ mini('Bender balance', fm(B.b_end), 'var(--accent3)')
+ mini('Total to finance', fm(B.total_financing))
+ mini('New mortgage (80% LTV cap)', fm(B.new_mortgage), 'var(--accent)')
+ mini('Cash needed at closing', fm(B.cash_at_closing), 'var(--accent4)')
+ mini('Net payout to Martins', fm(B.martin_payout), 'var(--accent2)'));

document.getElementById('b-net-now').innerHTML = fm(B.net_now) + '<span style="font-size:.8rem;color:var(--muted)">/mo</span>';
fill('b-net-now-sub', fm(D.params.bender_payment) + ' mortgage + ' + fm(B.expenses / 2) + ' half of expenses'
  + ' &minus; ' + fm(B.tenant_rent / 2) + ' half of tenant rent + ' + fm(D.params.bender_rent / 2) + ' net rent as tenants');
document.getElementById('b-net-after').innerHTML = fm(B.net_after) + '<span style="font-size:.8rem;color:var(--muted)">/mo</span>';
fill('b-net-after-sub', fm(B.new_payment) + ' new payment at ' + pc(B.buyout_rate_pct, 2) + ' over ' + B.amort_yrs + ' yrs'
  + ' + ' + fm(B.expenses) + ' expenses &minus; ' + fm(B.tenant_rent) + ' tenant rent<br>'
  + dspan(B.net_change, false) + '/mo vs today');
document.getElementById('b-tfsa').innerHTML = fm(H.tfsa);
fill('b-tfsa-sub', 'Tim ' + fm(H.tim) + ' &middot; Vivian ' + fm(H.vivian) + ' &nbsp;' + dspan(H.tfsa_delta, true)
  + ' in ' + H.tfsa_label + '<br>' + pc(B.cash_at_closing > 0 ? H.tfsa / B.cash_at_closing * 100 : 0) + ' of ' + fm(B.cash_at_closing) + ' needed');
document.getElementById('b-tfsa-bar').style.width =
  Math.min(100, B.cash_at_closing > 0 ? H.tfsa / B.cash_at_closing * 100 : 0) + '%';

// ---- history table ----
fill('hist-body', H.history.map(function (r, i) {
  return '<tr' + (i === 0 ? ' class="total-row"' : '') + '>' + td(r.label) + td(fm(r.b_end))
    + td(fm(r.equity)) + td(fm(r.b_interest, 2), 'muted-cell') + td(fm(r.b_prin, 2))
    + td(r.b_extra ? fm(r.b_extra) : '&mdash;', r.b_extra ? '' : 'muted-cell')
    + td(r.b_transfer ? fm(r.b_transfer) : '&mdash;', r.b_transfer ? '' : 'muted-cell')
    + td(fm(r.principal_total, 2)) + td(mos(r.remaining), 'muted-cell')
    + td(r.tfsa !== null ? fm(r.tfsa) : '&mdash;', 'muted-cell') + '</tr>';
}).join(''));

fill('house-notes', D.house_notes.map(function (n) { return '<li>' + n + '</li>'; }).join(''));
</script>
"""

TEMPLATE += r"""
<script>
// =========================== MONEY PAGE ===========================
var F = D.fin, TX = F.txn;
var CURWIN = F.default_window;

var GROUP_ORDER = ['Monthly', 'Cumulative', 'Tax Deductible', 'Savings', 'Hidden Categories'];
function groupRank(g) { var i = GROUP_ORDER.indexOf(g); return i === -1 ? 99 : i; }
function vsTag(v) {
  return Math.abs(v) < 25 ? '<span class="tag tag-n">on pace</span>'
       : (v > 0 ? '<span class="tag tag-b">+' + fm(v) + '</span>'
                : '<span class="tag tag-g">' + fm(v) + '</span>');
}
var STACK_FILL = {
  'House equity':          ['rgba(108,143,255,.55)', C.accent],
  'Pensions':              ['rgba(192,140,255,.55)', C.accent5],
  'Investments & savings': ['rgba(76,217,172,.55)',  C.accent2],
  'Cash & chequing':       ['rgba(245,194,66,.55)',  C.accent4],
  'Other':                 ['rgba(136,145,170,.50)', C.muted]
};

// ---- comparison-window picker ----
fill('win-buttons', F.window_order.map(function (id) {
  return '<button data-win="' + id + '"' + (id === CURWIN ? ' class="active"' : '') + '>'
    + F.windows[id].label + '</button>';
}).join(''));
document.querySelectorAll('#win-buttons button').forEach(function (b) {
  b.addEventListener('click', function () {
    if (b.dataset.win === CURWIN) return;
    CURWIN = b.dataset.win;
    document.querySelectorAll('#win-buttons button').forEach(function (x) { x.classList.remove('active'); });
    b.classList.add('active');
    renderMoney();
  });
});

function statCard(W, label, st, goodIsUp, color, hero, isPct) {
  var f  = isPct ? function (v) { return pc(v, 1); } : function (v) { return fm(v, 0); };
  var df = isPct ? function (v) { return v.toFixed(1) + ' pts'; } : function (v) { return fm(v, 0); };
  var dAvg = st.cur - st.avg, dYr = st.cur - st.yr_ago;
  var dSpan = '<span class="delta ' + dcls(dAvg, goodIsUp) + '">' + sg(dAvg) + df(dAvg) + '</span>';
  var ySpan = '<span class="delta ' + dcls(dYr, goodIsUp) + '">' + sg(dYr) + df(dYr) + '</span>';
  return card(label, f(st.cur),
    dSpan + ' vs the ' + W.short + ' average of ' + f(st.avg) + ' (median ' + f(st.median) + ')<br>'
    + ySpan + ' vs ' + F.yr_ago_label + ' (' + f(st.yr_ago) + ')',
    color, hero);
}

function renderMoney() {
  var W = F.windows[CURWIN], HL = W.headline, NW = W.nw;

  document.getElementById('win-span').innerHTML =
    W.span + ' &nbsp;&middot;&nbsp; ' + W.months + ' months'
    + (W.clamped ? ' &nbsp;&middot;&nbsp; clamped to where the data starts' : '');

  fill('money-banner',
    '<strong>' + F.cur_label + '</strong> &nbsp;&middot;&nbsp; the last complete month, measured against '
    + W.label.toLowerCase() + ' (' + W.span + '). '
    + TX.txn_count + ' transactions recorded. Money in ' + fm(HL.income.cur)
    + ', money out ' + fm(HL.spend.cur) + ', set aside ' + fm(HL.saved.cur) + '.');

  fill('money-hero',
    statCard(W, 'Money in', HL.income, true, 'var(--accent2)', true)
  + statCard(W, 'Money out', HL.spend, false, 'var(--accent3)', true)
  + statCard(W, 'Saved &amp; invested', HL.saved, true, 'var(--accent5)', true)
  + card('Left over (in &minus; out &minus; saved)', fm(HL.net.cur),
      '<span class="delta ' + dcls(HL.net.cur - HL.net.avg, true) + '">' + sg(HL.net.cur - HL.net.avg)
        + fm(HL.net.cur - HL.net.avg) + '</span> vs the ' + W.short + ' average of ' + fm(HL.net.avg) + '<br>'
      + W.label + ' total: <span class="' + (HL.net.total >= 0 ? 'good' : 'bad') + '">' + fm(HL.net.total) + '</span>',
      HL.net.cur >= 0 ? 'var(--accent2)' : 'var(--negative)', true));

  fill('money-second',
    statCard(W, 'Savings rate', HL.savings_rate, true, 'var(--accent5)', false, true)
  + statCard(W, 'Housing (Amroth)', HL.housing, false, 'var(--accent4)')
  + statCard(W, 'Everything else', HL.spend_ex_housing, false, 'var(--accent3)')
  + card('Net worth', fm(NW.now.net),
      dspan(NW.now.net - NW.prev.net, true) + ' vs ' + F.prev_label + '<br>'
      + dspan(NW.now.net - NW.start.net, true) + ' over ' + W.label.toLowerCase() + '<br>'
      + 'Assets ' + fm(NW.now.assets) + ' &minus; debt ' + fm(NW.now.debt),
      'var(--accent)'));

  document.getElementById('inc-month').textContent = F.cur_label;
  document.getElementById('inc-avg-h').textContent = W.short + ' average';
  fill('inc-body', W.income_sources.map(function (s) {
    return '<tr>' + td(s.payee) + td(fm(s.amount, 2)) + td(fm(s.avg, 2), 'muted-cell')
      + td(dspan(s.vs_avg, true, 2)) + '</tr>';
  }).join('')
  + '<tr class="total-row">' + td('Total money in') + td(fm(HL.income.cur, 2))
  + td(fm(HL.income.avg, 2), 'muted-cell')
  + td(dspan(HL.income.cur - HL.income.avg, true, 2)) + '</tr>');

  document.getElementById('flow-title').innerHTML = 'Income, spending &amp; saving &mdash; ' + W.label.toLowerCase();
  document.getElementById('nw-title').innerHTML = 'Net worth &mdash; ' + W.label.toLowerCase() + ', by what it is made of';
  var dense = W.labels.length > 18;
  var xTicks = Object.assign({ticks: {autoSkip: true, maxTicksLimit: dense ? 12 : 18,
                                      maxRotation: 60, minRotation: 0}}, GRID);

  if (CHARTS.flow) CHARTS.flow.destroy();
  CHARTS.flow = new Chart(document.getElementById('c-flow'), {data: {labels: W.labels, datasets: [
    {type: 'bar', label: 'Money in', data: W.series.income, backgroundColor: 'rgba(76,217,172,.75)', order: 3},
    {type: 'bar', label: 'Money out', data: W.series.spend, backgroundColor: 'rgba(255,140,107,.75)', order: 3},
    {type: 'bar', label: 'Saved', data: W.series.saved, backgroundColor: 'rgba(192,140,255,.7)', order: 3},
    {type: 'line', label: 'Left over', data: W.series.net, borderColor: C.accent4, backgroundColor: C.accent4,
     borderWidth: 2, pointRadius: dense ? 0 : 3, tension: .25, order: 1}
  ]}, options: {responsive: true, maintainAspectRatio: false, animation: false,
    interaction: {mode: 'index', intersect: false},
    plugins: {legend: {labels: {boxWidth: 10, boxHeight: 10, usePointStyle: true}}},
    scales: {x: xTicks, y: Object.assign({ticks: {callback: moneyTick}}, GRID)}}});

  if (CHARTS.nw) CHARTS.nw.destroy();
  CHARTS.nw = new Chart(document.getElementById('c-nw'), {type: 'line', data: {
    labels: NW.series.map(function (r) { return r.label; }),
    datasets: NW.stack.map(function (b, i) {
      var col = STACK_FILL[b.bucket] || ['rgba(136,145,170,.5)', C.muted];
      return {label: b.bucket, data: b.values, backgroundColor: col[0], borderColor: col[1],
              borderWidth: 1, pointRadius: 0, tension: .25, fill: i === 0 ? 'origin' : '-1'};
    })
  }, options: {responsive: true, maintainAspectRatio: false, animation: false,
    interaction: {mode: 'index', intersect: false},
    plugins: {legend: {labels: {boxWidth: 10, boxHeight: 10, usePointStyle: true}},
      tooltip: {callbacks: {footer: function (items) {
        return 'Net worth: ' + fm(items.reduce(function (a, i) { return a + i.parsed.y; }, 0));
      }}}},
    scales: {x: xTicks, y: Object.assign({stacked: true, beginAtZero: true,
                                          ticks: {callback: moneyTick}}, GRID)}}});

  document.getElementById('budget-month').textContent = F.cur_label;
  document.getElementById('cat-avg-h').textContent = W.short + ' avg';
  var ordered = W.group_rows.slice().sort(function (a, b) { return groupRank(a.group) - groupRank(b.group); });
  fill('cat-body', ordered.map(function (g) {
    var kids = W.categories.filter(function (c) { return c.group === g.group; });
    if (!kids.length) return '';
    var head = '<tr class="total-row">' + td(g.group)
      + td('<span class="muted-cell">' + kids.length + ' categor' + (kids.length === 1 ? 'y' : 'ies') + '</span>')
      + td('') + td(fm(g.spent)) + td('') + td(fm(g.prev), 'muted-cell')
      + td(fm(g.avg), 'muted-cell') + td(vsTag(g.vs_avg)) + td('') + '</tr>';
    return head + kids.map(function (c) {
      var n = (D.pres.cat_txns[c.category] || []).length;
      return '<tr' + (n ? ' class="drill" data-cat="' + c.category.replace(/"/g, '&quot;') + '"' : '') + '>'
        + td('&nbsp;&nbsp;&nbsp;&nbsp;' + c.category) + td('')
        + td(fm(c.assigned, 2), 'muted-cell') + td(fm(c.spent, 2))
        + td(fm(c.available, 2), c.available < 0 ? 'bad' : 'muted-cell')
        + td(fm(c.prev, 2), 'muted-cell') + td(fm(c.avg, 2), 'muted-cell')
        + td(vsTag(c.vs_avg)) + td(fm(c.yr_ago, 2), 'muted-cell') + '</tr>';
    }).join('');
  }).join(''));
}

// ---- window-independent tables ----
fill('big-body', TX.biggest.map(function (t) {
  return '<tr>' + td(t.date, 'muted-cell') + td(t.payee)
    + td('<span class="muted-cell">' + (t.category || '&mdash;') + '</span>')
    + td(fm(t.amount, 2)) + '</tr>';
}).join(''));

var NWNOW = F.windows[F.default_window].nw;
var acctHtml = F.nw_buckets.map(function (b) {
  var kids = F.nw_accounts.filter(function (a) { return a.bucket === b.bucket; });
  return '<tr class="total-row">' + td(b.bucket)
    + td('<span class="muted-cell">' + kids.length + ' account' + (kids.length === 1 ? '' : 's') + '</span>')
    + td(fm(b.balance)) + td(dspan(b.delta, b.bucket !== 'Credit cards')) + '</tr>'
    + kids.map(function (a) {
        return '<tr>' + td('&nbsp;&nbsp;&nbsp;&nbsp;' + a.account) + td('')
          + td(fm(a.balance, 2), a.balance < 0 ? 'bad' : '')
          + td(a.delta ? dspan(a.delta, a.bucket !== 'Credit cards', 2) : '<span class="muted-cell">&mdash;</span>') + '</tr>';
      }).join('');
}).join('');
acctHtml += '<tr class="total-row">' + td('NET WORTH') + td('') + td(fm(NWNOW.now.net))
  + td(dspan(NWNOW.now.net - NWNOW.prev.net, true)) + '</tr>';
fill('acct-body', acctHtml);

fill('money-notes', D.money_notes.map(function (n) { return '<li>' + n + '</li>'; }).join(''));

renderMoney();
</script>

<script>
// =========================== PRESENTATION ===========================
var P = D.pres;
var PWIN = P.default_window;
var DASH = document.getElementById('dashboard');
var PRES = document.getElementById('pres');
var SLIDES = Array.prototype.slice.call(document.querySelectorAll('#pres .slide'));
var NS = SLIDES.length;
var IDX = 0;

function esc(v) {
  return String(v === null || v === undefined ? '' : v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
function PB() { return P.baselines[PWIN]; }
function killChart(k) { if (CHARTS[k]) { CHARTS[k].destroy(); CHARTS[k] = null; } }

// ---- the comparison-period toggle, repeated on every comparison slide ----
function winbarHtml() {
  var b = PB();
  return '<div class="winbar"><span class="wlbl">Compare ' + P.cur_label + ' against</span>'
    + P.window_order.map(function (id) {
        return '<button data-pwin="' + id + '"' + (id === PWIN ? ' class="active"' : '') + '>'
          + P.baselines[id].label + '</button>';
      }).join('')
    + '<span class="wspan">' + b.span
    + (b.months > 1 ? ' &nbsp;&middot;&nbsp; ' + b.months + ' months' : '')
    + (b.clamped ? ' &nbsp;&middot;&nbsp; clamped to where the data starts' : '') + '</span></div>';
}
function paintWinbars() {
  var slide = SLIDES[IDX];
  var bar = slide.querySelector('[data-winbar]');
  if (bar) bar.innerHTML = winbarHtml();
}
PRES.addEventListener('click', function (e) {
  var id = e.target.dataset ? e.target.dataset.pwin : null;
  if (!id || id === PWIN) return;
  PWIN = id;
  buildSlide(IDX);
});

function buildSlide(i) {
  if (BUILDERS[i]) BUILDERS[i]();
  paintWinbars();
  Object.values(CHARTS).forEach(function (c) { if (c) c.resize(); });
}

function showSlide(i) {
  IDX = Math.max(0, Math.min(NS - 1, i));
  SLIDES.forEach(function (s, j) { s.classList.toggle('on', j === IDX); });
  buildSlide(IDX);
  document.getElementById('pres-step').textContent = (IDX + 1) + ' / ' + NS;
  document.getElementById('pres-prev').disabled = IDX === 0;
  document.getElementById('pres-next').innerHTML = IDX === NS - 1 ? 'Finish &rarr;' : 'Next &rarr;';
  fill('pres-dots', SLIDES.map(function (s, j) {
    return '<span data-go="' + j + '" class="' + (j === IDX ? 'on' : (j < IDX ? 'done' : '')) + '"></span>';
  }).join(''));
  document.getElementById('pres-stage').scrollTop = 0;
}

function openDashboard() {
  PRES.style.display = 'none';
  DASH.hidden = false;
  document.body.style.padding = '24px';
  Object.values(CHARTS).forEach(function (c) { if (c) c.resize(); });
}
function openPresentation() {
  DASH.hidden = true;
  PRES.style.display = 'flex';
  document.body.style.padding = '0';
  showSlide(0);
}

document.getElementById('pres-next').addEventListener('click', function () {
  if (IDX === NS - 1) openDashboard(); else showSlide(IDX + 1);
});
document.getElementById('pres-prev').addEventListener('click', function () { showSlide(IDX - 1); });
document.getElementById('pres-skip').addEventListener('click', openDashboard);
document.getElementById('s8-open').addEventListener('click', openDashboard);
document.getElementById('pres-dots').addEventListener('click', function (e) {
  if (e.target.dataset.go !== undefined) showSlide(+e.target.dataset.go);
});
document.getElementById('replay-link').addEventListener('click', function (e) {
  e.preventDefault(); openPresentation();
});
document.addEventListener('keydown', function (e) {
  if (PRES.style.display === 'none') return;
  if (e.key === 'ArrowRight' || e.key === 'PageDown') { e.preventDefault(); if (IDX < NS - 1) showSlide(IDX + 1); else openDashboard(); }
  if (e.key === 'ArrowLeft' || e.key === 'PageUp') { e.preventDefault(); showSlide(IDX - 1); }
  if (e.key === 'Escape') openDashboard();
});

// ---- category drill-down, shared by the walkthrough and the dashboard ----
function drillHtml(cat) {
  var rows = P.cat_txns[cat] || [];
  if (!rows.length) {
    return '<div class="drill-wrap"><div class="drill-foot">No transactions recorded in '
      + P.cur_label + ' for this category.</div></div>';
  }
  var total = rows.reduce(function (a, r) { return a + r.amount; }, 0);
  return '<div class="drill-wrap"><table><thead><tr>'
    + '<th>Date</th><th>Payee</th><th>Memo</th><th>Account</th><th>Amount</th></tr></thead><tbody>'
    + rows.map(function (r) {
        return '<tr>' + td(r.date, 'muted-cell') + td(esc(r.payee))
          + td('<span class="muted-cell">' + esc(r.memo) + '</span>')
          + td('<span class="muted-cell">' + esc(r.account) + '</span>')
          + td(fm(r.amount, 2), r.amount < 0 ? 'good' : '') + '</tr>';
      }).join('')
    + '</tbody></table><div class="drill-foot">' + rows.length + ' transaction'
    + (rows.length === 1 ? '' : 's') + ' &middot; totals ' + fm(total, 2)
    + (total < 0 ? ' (net refund)' : '') + '</div></div>';
}

function attachDrill(tbodyId) {
  document.getElementById(tbodyId).addEventListener('click', function (e) {
    var tr = e.target.closest ? e.target.closest('tr.drill') : null;
    if (!tr || !tr.dataset.cat) return;
    var next = tr.nextElementSibling;
    if (next && next.classList.contains('drill-body')) {
      next.parentNode.removeChild(next); tr.classList.remove('open'); return;
    }
    // build the cell and set innerHTML on IT - setting innerHTML on a <tr>
    // parses in row context and mis-nests the inner table's <thead>
    var row = document.createElement('tr');
    row.className = 'drill-body';
    var cell = document.createElement('td');
    cell.colSpan = tr.children.length;
    cell.innerHTML = drillHtml(tr.dataset.cat);
    row.appendChild(cell);
    tr.parentNode.insertBefore(row, tr.nextSibling);
    tr.classList.add('open');
  });
}

// ---- slide builders ----
var CUR = P.cur;
function vsLine(cur, avg, goodIsUp, isPct) {
  var d = cur - avg, b = PB();
  var f = isPct ? function (v) { return v.toFixed(1) + ' pts'; } : function (v) { return fm(v, 0); };
  var shown = isPct ? avg.toFixed(1) + '%' : fm(avg, 0);
  return '<span class="delta ' + dcls(d, goodIsUp) + '">' + sg(d) + f(d) + '</span>'
    + ' vs ' + b.against + ' (' + shown + ')';
}

var BUILDERS = {};

BUILDERS[0] = function () {
  var A = PB().avgs;
  document.getElementById('pres-month').textContent = P.cur_label + ' in review';
  document.getElementById('s0-title').textContent = P.cur_label;
  fill('s0-lede', 'A walk through the month, one step at a time. Pick what to measure it against below &mdash; '
    + 'every baseline is the period <em>before</em> ' + P.cur_label + ', never including it. '
    + 'Use <strong>Next</strong>, the arrow keys, or the bars up top to move around.');
  fill('s0-cards',
    card('Money in', fm(CUR.income), vsLine(CUR.income, A.income, true), 'var(--accent2)', true)
  + card('Money out', fm(CUR.spend), vsLine(CUR.spend, A.spend, false), 'var(--accent3)', true)
  + card('Saved &amp; invested', fm(CUR.saved), vsLine(CUR.saved, A.saved, true), 'var(--accent5)', true)
  + card('Left over', fm(CUR.net), vsLine(CUR.net, A.net, true),
         CUR.net >= 0 ? 'var(--accent2)' : 'var(--negative)', true));
};

BUILDERS[1] = function () {
  var b = PB(), st = b.streams, top = st.slice(0, 10);
  var avgIn = b.avgs.income, d = CUR.income - avgIn;
  fill('s1-lede', '<strong>' + fm(CUR.income) + '</strong> came in across <strong>'
    + st.filter(function (x) { return x.amount > 0; }).length + ' streams</strong>, '
    + (d >= 0 ? 'up ' : 'down ') + fm(Math.abs(d)) + ' on ' + b.against + ' of ' + fm(avgIn)
    + ' (' + b.span + '). The bars show this month against that baseline, stream by stream.');
  document.getElementById('s1-chart-title').textContent = P.cur_label + ' vs ' + b.span;
  document.getElementById('s1-cur-h').textContent = P.cur_label;
  document.getElementById('s1-avg-h').textContent = b.months === 1 ? b.span : b.short + ' average';
  fill('s1-body', st.map(function (x) {
    return '<tr>' + td(esc(x.payee)) + td(fm(x.amount, 2)) + td(fm(x.avg, 2), 'muted-cell')
      + td(x.new ? '<span class="tag tag-g">new</span>' : dspan(x.vs_avg, true, 2)) + '</tr>';
  }).join('')
  + '<tr class="total-row">' + td('Total money in') + td(fm(CUR.income, 2))
  + td(fm(avgIn, 2), 'muted-cell') + td(dspan(d, true, 2)) + '</tr>');

  killChart('streams');
  CHARTS.streams = new Chart(document.getElementById('c-streams'), {type: 'bar', data: {
    labels: top.map(function (x) { return x.payee; }), datasets: [
    {label: P.cur_label, data: top.map(function (x) { return x.amount; }), backgroundColor: C.accent2},
    {label: b.months === 1 ? b.span : b.short + ' average',
     data: top.map(function (x) { return x.avg; }), backgroundColor: 'rgba(136,145,170,.55)'}
  ]}, options: {indexAxis: 'y', responsive: true, maintainAspectRatio: false, animation: false,
    plugins: {legend: {labels: {boxWidth: 10, boxHeight: 10, usePointStyle: true}}},
    scales: {x: Object.assign({ticks: {callback: moneyTick}}, GRID), y: GRID}}});
};

BUILDERS[2] = function () {
  var over = P.overspent, soft = P.over_assigned;
  fill('s2-lede', over.length
    ? '<strong>' + over.length + ' categor' + (over.length === 1 ? 'y' : 'ies') + '</strong> finished '
      + P.cur_label + ' with a negative balance &mdash; the assignment plus any carried-over cushion did not cover the spending. '
      + (soft.length ? soft.length + ' more went past this month&rsquo;s assignment but had enough banked to absorb it.' : '')
    : 'Nothing finished the month in the red. '
      + (soft.length ? soft.length + ' categor' + (soft.length === 1 ? 'y' : 'ies') + ' spent more than assigned, but carried-over balance absorbed it.' : ''));

  function flagCard(x, cls, label, word) {
    return '<div class="flag ' + cls + '">'
      + '<div class="flag-top"><span class="flag-name">' + esc(x.category) + '</span>'
      + '<span class="flag-amt ' + (cls === 'red' ? 'bad' : '') + '">' + fm(x.over, 2)
      + '<span style="font-size:.72rem;font-weight:600;color:var(--muted)"> ' + word + '</span></span></div>'
      + '<div class="flag-sub">' + esc(x.group) + ' &middot; spent ' + fm(x.spent, 2)
      + ' against ' + fm(x.assigned, 2) + ' assigned &middot; ' + label + ' ' + fm(x.available, 2) + '</div></div>';
  }
  var html = '';
  if (over.length) {
    html += '<div class="section-title" style="color:var(--negative)">Overspent &mdash; ended the month negative</div>'
      + '<div class="grid g3">' + over.map(function (x) { return flagCard(x, 'red', 'available', 'short'); }).join('') + '</div>';
  }
  if (soft.length) {
    html += '<div class="section-title" style="color:var(--accent4);margin-top:8px">Over the assignment &mdash; covered by carry-over</div>'
      + '<div class="grid g3">' + soft.map(function (x) { return flagCard(x, 'amber', 'still available', 'over plan'); }).join('') + '</div>';
  }
  if (!over.length && !soft.length) {
    html = '<div class="flag green"><div class="flag-name">Every category stayed inside its budget.</div></div>';
  }
  fill('s2-over', html);
};

BUILDERS[3] = function () {
  var big = TX.biggest.slice(0, 10), sum = big.reduce(function (a, r) { return a + r.amount; }, 0);
  fill('s3-lede', 'The ' + big.length + ' largest single transactions of ' + P.cur_label
    + ' account for <strong>' + fm(sum) + '</strong> &mdash; '
    + pc(CUR.spend ? sum / CUR.spend * 100 : 0) + ' of the month&rsquo;s ' + fm(CUR.spend) + ' of spending.');
  fill('s3-body', big.map(function (t) {
    return '<tr>' + td(t.date, 'muted-cell') + td(esc(t.payee))
      + td('<span class="muted-cell">' + esc(t.category) + '</span>')
      + td('<span class="muted-cell">' + esc(t.account) + '</span>')
      + td(fm(t.amount, 2))
      + td(pc(CUR.spend ? t.amount / CUR.spend * 100 : 0), 'muted-cell') + '</tr>';
  }).join('')
  + '<tr class="total-row">' + td('Top ' + big.length) + td('') + td('') + td('')
  + td(fm(sum, 2)) + td(pc(CUR.spend ? sum / CUR.spend * 100 : 0)) + '</tr>');
};

BUILDERS[4] = function () {
  var b = PB(), W = F.windows['3m'];
  fill('s4-lede', 'Every category that moved in ' + P.cur_label + ', grouped the way the budget is. '
    + '<strong>Click any row</strong> to unfold the individual transactions that add up to its "spent" figure &mdash; '
    + 'they reconcile exactly.');
  document.getElementById('s4-prev-h').textContent = P.prev_label;
  document.getElementById('s4-vs-h').textContent = b.months === 1 ? 'vs ' + b.span : 'vs ' + b.short + ' avg';

  // categories that actually moved this month, grouped
  var cats = W.categories.filter(function (c) {
    return Math.abs(c.spent) >= 0.005 || Math.abs(c.assigned) >= 0.005;
  });
  var groups = {};
  cats.forEach(function (c) {
    var g = groups[c.group] || (groups[c.group] = {group: c.group, spent: 0, prev: 0, avg: 0, kids: []});
    g.spent += c.spent; g.prev += c.prev; g.avg += (b.cat_avg[c.category] || 0); g.kids.push(c);
  });
  var ordered = Object.keys(groups).sort(function (x, y) { return groupRank(x) - groupRank(y); });
  fill('s4-body', ordered.map(function (gn) {
    var g = groups[gn];
    var head = '<tr class="total-row">' + td(g.group) + td('') + td(fm(g.spent))
      + td(fm(g.prev), 'muted-cell') + td(vsTag(g.spent - g.avg)) + td('')
      + td('<span class="muted-cell">' + g.kids.length + '</span>') + '</tr>';
    return head + g.kids.map(function (c) {
      var n = (P.cat_txns[c.category] || []).length;
      var avg = b.cat_avg[c.category] || 0;
      return '<tr' + (n ? ' class="drill" data-cat="' + esc(c.category) + '"' : '') + '>'
        + td('&nbsp;&nbsp;&nbsp;&nbsp;' + esc(c.category))
        + td(fm(c.assigned, 2), 'muted-cell') + td(fm(c.spent, 2))
        + td(fm(c.prev, 2), 'muted-cell') + td(vsTag(c.spent - avg))
        + td(fm(c.available, 2), c.available < 0 ? 'bad' : 'muted-cell')
        + td(n ? n + '' : '<span class="muted-cell">&mdash;</span>') + '</tr>';
    }).join('');
  }).join(''));
};

BUILDERS[5] = function () {
  var b = PB(), A = b.avgs;
  fill('s5-lede', '<strong>' + fm(CUR.saved) + '</strong> went into savings and investments in ' + P.cur_label
    + ' &mdash; a savings rate of <strong>' + CUR.savings_rate.toFixed(1) + '%</strong> of everything that came in. '
    + b.against.charAt(0).toUpperCase() + b.against.slice(1) + ' was ' + fm(A.saved)
    + ' at ' + A.savings_rate.toFixed(1) + '%.');
  fill('s5-cards',
    card('Saved &amp; invested', fm(CUR.saved), vsLine(CUR.saved, A.saved, true), 'var(--accent5)', true)
  + card('Savings rate', CUR.savings_rate.toFixed(1) + '%',
         vsLine(CUR.savings_rate, A.savings_rate, true, true), 'var(--accent5)', true)
  + card('Housing', fm(CUR.housing), vsLine(CUR.housing, A.housing, false), 'var(--accent4)', true)
  + card('Left over after everything', fm(CUR.net), vsLine(CUR.net, A.net, true),
         CUR.net >= 0 ? 'var(--accent2)' : 'var(--negative)', true));
  // when the baseline IS last month the two columns would be identical, so
  // the baseline-level column only appears for multi-month baselines
  var wide = b.months > 1;
  fill('s5-head', '<tr><th>Destination</th><th>' + P.cur_label + '</th><th>' + P.prev_label + '</th>'
    + (wide ? '<th>' + b.short + ' average</th>' : '')
    + '<th>vs ' + (wide ? b.short + ' avg' : b.span) + '</th></tr>');
  fill('s5-body', b.saving_rows.map(function (r) {
    var n = (P.cat_txns[r.category] || []).length;
    return '<tr' + (n ? ' class="drill" data-cat="' + esc(r.category) + '"' : '') + '>'
      + td(esc(r.category)) + td(fm(r.amount, 2)) + td(fm(r.prev, 2), 'muted-cell')
      + (wide ? td(fm(r.avg, 2), 'muted-cell') : '')
      + td(dspan(r.vs_avg, true, 2)) + '</tr>';
  }).join('')
  + '<tr class="total-row">' + td('Total set aside') + td(fm(CUR.saved, 2))
  + td(fm(P.baselines['1m'].avgs.saved, 2), 'muted-cell')
  + (wide ? td(fm(A.saved, 2), 'muted-cell') : '')
  + td(dspan(CUR.saved - A.saved, true, 2)) + '</tr>');

  var B = D.house.buyout, tf = D.house;
  var pctSaved = B.cash_at_closing > 0 ? tf.tfsa / B.cash_at_closing * 100 : 0;
  fill('s5-tfsa',
    '<div class="big-stat sm" style="color:var(--accent5)">' + fm(tf.tfsa) + '</div>'
    + '<div class="card-sub">Tim ' + fm(tf.tim) + ' &middot; Vivian ' + fm(tf.vivian) + '<br>'
    + dspan(tf.tfsa_delta, true) + ' added in ' + tf.tfsa_label + '<br>'
    + pc(pctSaved) + ' of the ' + fm(B.cash_at_closing) + ' needed as cash at closing</div>'
    + '<div class="bar-track"><div class="bar-fill" style="width:' + Math.min(100, pctSaved) + '%"></div></div>');
};

BUILDERS[6] = function () {
  // review the mortgage month matching the month under review, not
  // necessarily the newest row in the tracker
  var b = PB(), ser = D.house.series, i = -1;
  for (var k = 0; k < ser.length; k++) { if (ser[k].label === P.cur_label) i = k; }
  if (i < 1) i = ser.length - 1;
  var cur = ser[i], prv = ser[i - 1] || null;
  function payoffOf(r) {
    if (!r || r.remaining === null) return '&mdash;';
    var y = +r.key.slice(0, 4), m = +r.key.slice(5), idx = y * 12 + (m - 1) + r.remaining;
    return MONTH_NAMES[idx % 12] + ' ' + Math.floor(idx / 12);
  }
  // average the same per-month measures across the selected baseline months
  var pr = [], sh = [], itr = [];
  for (var j = 1; j <= i; j++) {
    if (b.keys.indexOf(ser[j].key) === -1) continue;
    pr.push(ser[j].principal_total);
    if (ser[j].shaved !== null) sh.push(ser[j].shaved);
    itr.push(ser[j].b_interest);
  }
  function mean(a) { return a.length ? a.reduce(function (x, y) { return x + y; }, 0) / a.length : 0; }
  var nB = pr.length;
  var against = nB === 0 ? null : (nB === 1 ? prv.label : 'the ' + b.short + ' average');
  function houseVs(cur_v, avg_v, goodIsUp, fmt) {
    if (against === null) return 'No comparable mortgage months in this baseline.';
    var d = cur_v - avg_v;
    return '<span class="delta ' + dcls(d, goodIsUp) + '">' + sg(d) + (fmt || function (v) { return fm(v, 0); })(d)
      + '</span> vs ' + against + ' (' + (fmt || function (v) { return fm(v, 0); })(avg_v) + ')';
  }
  var shaved  = cur.shaved;
  var B = D.house.buyout, allIn = cur.b_end + B.martin_share;

  document.getElementById('s6-month').textContent = cur.label;
  fill('s6-lede', 'The mortgage side of ' + cur.label + '. A payment of <strong>'
    + fm(cur.principal_total, 2) + '</strong> went against principal &mdash; '
    + fm(cur.b_prin, 2) + ' scheduled'
    + (cur.b_extra ? ' plus ' + fm(cur.b_extra) + ' extra' : '')
    + (cur.b_transfer ? ' plus ' + fm(cur.b_transfer, 2) + ' from a partnership transfer' : '')
    + ' &mdash; and interest took ' + fm(cur.b_interest, 2) + '. '
    + (nB ? 'The baseline below averages the same measures over ' + nB + ' tracked mortgage month'
        + (nB === 1 ? '' : 's') + '.' : ''));

  fill('s6-cards',
    card('Principal gained', fm(cur.principal_total), houseVs(cur.principal_total, mean(pr), true)
      + '<br>' + fm(cur.b_prin, 2) + ' scheduled &middot; ' + fm(cur.b_extra) + ' extra'
      + (cur.b_transfer ? ' &middot; ' + fm(cur.b_transfer, 2) + ' transfer' : ''), 'var(--accent)', true)
  + card('Extra amortization shaved', '<span class="' + dcls(shaved, true) + '">' + days(shaved) + '</span>',
      houseVs(shaved, mean(sh), true, function (v) { return days(v); })
      + '<br>Extra principal only &middot; term left ' + mos(cur.remaining),
      'var(--accent4)', true)
  + card('Interest paid', fm(cur.b_interest, 2), houseVs(cur.b_interest, mean(itr), false, function (v) { return fm(v, 2); })
      + '<br>Bender share at ' + pc(D.params.rate_pct, 2) + ' annual', 'var(--accent3)', true));

  fill('s6-cards2',
    card('Bender equity', fm(cur.equity),
      pc(cur.equity_pct) + ' of the ' + fm(D.house.half_value) + ' Bender half<br>'
      + 'It grows by exactly the principal gained, shown above', 'var(--accent2)')
  + card('Bender mortgage balance', fm(cur.b_end),
      (prv ? dspan(cur.b_end - prv.b_end, false) + ' on the month<br>' : '')
      + fm(allIn) + ' all-in to own outright', 'var(--text)')
  + card('Projected payoff', payoffOf(cur),
      'On the scheduled payment with no further extras' + (prv ? '<br>Last month it read ' + payoffOf(prv) : ''), 'var(--accent2)')
  + card('Interest saved to date', fm(cur.base_cum_interest - cur.cum_interest, 2),
      'vs paying only the scheduled payment since day one', 'var(--accent2)'));
};

BUILDERS[7] = function () {
  var b = PB(), NW = b.nw;
  var now = NW.now;                       // the month under review
  var startNet = NW.start.net;            // first month of the selected baseline
  var overPeriod = now.net - startNet;
  var startLabel = NW.series[0].label;

  fill('s7-chart-title', 'Net worth &mdash; ' + b.nw_span);
  document.getElementById('s7-vs-h').textContent = 'since ' + startLabel;
  fill('s7-lede', 'Net worth finished ' + P.cur_label + ' at <strong>' + fm(now.net) + '</strong>, '
    + dspan(overPeriod, true) + ' since ' + startLabel
    + (b.months > 1 ? ' &mdash; the start of the ' + b.label.toLowerCase() + ' you are comparing against' : '')
    + '. The bands are what it is made of; the top of the stack is the total.');

  fill('s7-body', NW.stack.map(function (x) {
    var v = x.values[x.values.length - 1], p = x.values[0];
    return '<tr>' + td(x.bucket) + td(fm(v)) + td(pc(now.net ? v / now.net * 100 : 0), 'muted-cell')
      + td(dspan(v - p, true)) + '</tr>';
  }).join('')
  + '<tr class="total-row">' + td('Net worth') + td(fm(now.net)) + td('100.0%')
  + td(dspan(overPeriod, true)) + '</tr>');

  killChart('presnw');
  var few = NW.series.length <= 4;        // a 2-point area is unreadable; use bars
  CHARTS.presnw = new Chart(document.getElementById('c-pres-nw'), {type: few ? 'bar' : 'line', data: {
    labels: NW.series.map(function (r) { return r.label; }),
    datasets: NW.stack.map(function (x, i) {
      var col = STACK_FILL[x.bucket] || ['rgba(136,145,170,.5)', C.muted];
      var d = {label: x.bucket, data: x.values, backgroundColor: col[0], borderColor: col[1], borderWidth: 1};
      if (!few) { d.pointRadius = 0; d.tension = .25; d.fill = i === 0 ? 'origin' : '-1'; }
      return d;
    })
  }, options: {responsive: true, maintainAspectRatio: false, animation: false,
    interaction: {mode: 'index', intersect: false},
    plugins: {legend: {labels: {boxWidth: 10, boxHeight: 10, usePointStyle: true}},
      tooltip: {callbacks: {footer: function (items) {
        return 'Net worth: ' + fm(items.reduce(function (a, i) { return a + i.parsed.y; }, 0));
      }}}},
    scales: {x: Object.assign({stacked: true, ticks: {autoSkip: true, maxTicksLimit: 12, maxRotation: 60}}, GRID),
             y: Object.assign({stacked: true, beginAtZero: true, ticks: {callback: moneyTick}}, GRID)}}});
};

BUILDERS[8] = function () {
  var b = PB(), A = b.avgs, NW = F.windows['12m'].nw;
  document.getElementById('s8-title').textContent = P.cur_label + ' in four numbers';
  fill('s8-lede', 'That is the month, measured against ' + b.against + ' (' + b.span + '). '
    + 'The full dashboard has the same data with its own trailing comparison windows, the mortgage tab, '
    + 'and every table in full. The walkthrough button under the dashboard title brings you back here.');
  fill('s8-cards',
    card('Left over', fm(CUR.net), vsLine(CUR.net, A.net, true),
         CUR.net >= 0 ? 'var(--accent2)' : 'var(--negative)', true)
  + card('Saved &amp; invested', fm(CUR.saved), vsLine(CUR.saved, A.saved, true), 'var(--accent5)', true)
  + card('Bender equity', fm(D.house.equity),
         dspan(D.house.equity_delta, true) + ' in ' + D.house.cur_label, 'var(--accent2)', true)
  + card('Net worth', fm(NW.now.net),
         dspan(NW.now.net - NW.prev.net, true) + ' on the month', 'var(--accent)', true));
};

function label_from(key) {
  return MONTH_NAMES[+key.slice(5) - 1] + ' ' + key.slice(0, 4);
}

// Drill-down listeners live on the <tbody> elements, which survive the
// innerHTML swaps the builders do - so attach once, not inside a builder.
attachDrill('cat-body');
attachDrill('s4-body');
attachDrill('s5-body');
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def review_filename(cur_key):
    return "bender_review_" + cur_key + ".html"


def write_index(dirpath, generated):
    """Rebuild reviews/index.html so the folder is browsable. Regenerated on
    every run, so it always lists every review actually present - including
    ones made before this script knew about them."""
    rows = []
    for fn in sorted(os.listdir(dirpath), reverse=True):
        m = re.match(r"^bender_review_(\d{4}-\d{2})\.html$", fn)
        if not m:
            continue
        key = m.group(1)
        stamp = datetime.fromtimestamp(os.path.getmtime(os.path.join(dirpath, fn)))
        rows.append('<a class="row" href="./' + fn + '">'
                    + '<span class="m">' + label_from_key(key) + '</span>'
                    + '<span class="f">' + fn + '</span>'
                    + '<span class="d">built ' + stamp.strftime("%d %b %Y, %H:%M") + '</span></a>')
    if not rows:
        rows = ['<p class="empty">No reviews generated yet.</p>']

    html = ('<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="UTF-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
            '<title>Bender Reviews</title>\n<style>\n'
            ':root{--bg:#0f1117;--surface:#1a1d27;--surface2:#222536;--border:#2e3148;'
            '--accent:#6c8fff;--text:#e8eaf0;--muted:#8891aa}\n'
            '*{box-sizing:border-box;margin:0;padding:0}\n'
            "body{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--text);"
            'padding:40px 24px;max-width:760px;margin:0 auto}\n'
            'h1{font-size:1.5rem;font-weight:700;margin-bottom:4px}\n'
            '.sub{color:var(--muted);font-size:.85rem;margin-bottom:28px}\n'
            '.row{display:flex;align-items:baseline;gap:16px;text-decoration:none;color:inherit;'
            'background:var(--surface);border:1px solid var(--border);border-left:3px solid var(--accent);'
            'border-radius:10px;padding:15px 18px;margin-bottom:10px}\n'
            '.row:hover{border-color:var(--accent);background:var(--surface2)}\n'
            '.m{font-size:1.05rem;font-weight:700;min-width:120px}\n'
            '.f{font-size:.78rem;color:var(--muted);flex:1}\n'
            '.d{font-size:.75rem;color:var(--muted);white-space:nowrap}\n'
            '.empty{color:var(--muted);font-size:.9rem}\n'
            '</style>\n</head>\n<body>\n'
            '<h1>&#128200; Bender monthly reviews</h1>\n'
            '<p class="sub">64 Amroth &amp; household finances &nbsp;&middot;&nbsp; index rebuilt '
            + generated + '</p>\n' + "\n".join(rows) + '\n</body>\n</html>\n')

    path = os.path.join(dirpath, "index.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return path


# ---------------------------------------------------------------------------
# WHICH MONTH ARE WE REVIEWING?
# ---------------------------------------------------------------------------
# The finance tab and the walkthrough are always about ONE complete month.
# Default is the last complete calendar month, but the current month is often
# only part-budgeted, so the month is selectable:
#
#   python bender_dashboard_v3.py                 -> pick from a menu
#   python bender_dashboard_v3.py 2026-08         -> straight to August 2026
#   python bender_dashboard_v3.py "Aug 2026"      -> same
#   python bender_dashboard_v3.py --latest        -> newest month, no prompt
#   python bender_dashboard_v3.py --list          -> show what is available
#
# Set FINANCE_MONTH to pin it permanently and skip all of the above.
FINANCE_MONTH = None

MONTH_LOOKUP = {}
for _i, _n in enumerate(MONTH_NAMES):
    MONTH_LOOKUP[_n.lower()] = _i + 1
for _full, _i in [("january", 1), ("february", 2), ("march", 3), ("april", 4),
                  ("may", 5), ("june", 6), ("july", 7), ("august", 8),
                  ("september", 9), ("october", 10), ("november", 11),
                  ("december", 12)]:
    MONTH_LOOKUP[_full] = _i


def parse_month(text):
    """Accept 2026-08, 2026-8, 08-2026, Aug 2026, August 2026, 2026-08-31."""
    t = (text or "").strip().replace(",", " ")
    if not t:
        return None

    def ok(year, mon):
        return "%s-%02d" % (year, mon) if 1 <= mon <= 12 else None

    m = re.match(r"^(\d{4})-(\d{1,2})(?:-\d{1,2})?$", t)
    if m:
        return ok(m.group(1), int(m.group(2)))
    m = re.match(r"^(\d{1,2})-(\d{4})$", t)
    if m:
        return ok(m.group(2), int(m.group(1)))
    m = re.match(r"^([A-Za-z]+)\s+(\d{4})$", t)
    if m and m.group(1).lower() in MONTH_LOOKUP:
        return "%s-%02d" % (m.group(2), MONTH_LOOKUP[m.group(1).lower()])
    m = re.match(r"^(\d{4})\s+([A-Za-z]+)$", t)
    if m and m.group(2).lower() in MONTH_LOOKUP:
        return "%s-%02d" % (m.group(1), MONTH_LOOKUP[m.group(2).lower()])
    return None


def month_summary(reg, plan, today):
    """Every month present in the data, newest first, with enough detail to
    tell a finished month from a part-budgeted one."""
    txn_count, assigned = {}, {}
    for t in reg:
        txn_count[t["key"]] = txn_count.get(t["key"], 0) + 1
    for row in plan:
        if row["group"] in SPEND_GROUPS:
            assigned[row["key"]] = assigned.get(row["key"], 0.0) + row["assigned"]
    this_month = "%d-%02d" % (today.year, today.month)
    out = []
    for k in sorted(txn_count, reverse=True):
        if k > this_month:          # scheduled future transactions, not a month to review
            continue
        out.append({"key": k, "label": label_from_key(k),
                    "txns": txn_count[k], "assigned": round(assigned.get(k, 0.0), 2),
                    "partial": k >= this_month})
    return out


def default_month(available, today):
    """Last complete calendar month that actually has data."""
    y, m = add_months(today.year, today.month, -1)
    want = "%d-%02d" % (y, m)
    keys = [x["key"] for x in available]
    if want in keys:
        return want
    for k in keys:                   # already newest-first
        if k <= want:
            return k
    return keys[0] if keys else want


def choose_month(available, fallback, today):
    """Interactive picker. Enter accepts the default."""
    print("")
    print("  Which month should the review cover?")
    print("")
    print("     %-4s %-10s %9s  %s" % ("", "MONTH", "TXNS", "ASSIGNED"))
    shown = available[:15]
    for i, x in enumerate(shown, 1):
        mark = "  <- default" if x["key"] == fallback else ""
        flag = " (in progress)" if x["partial"] else ""
        print("     %-4s %-10s %9d  %10s%s%s"
              % (str(i) + ".", x["label"], x["txns"],
                 "$" + format(int(round(x["assigned"])), ","), flag, mark))
    print("")
    try:
        raw = input("  Number, month (e.g. 2026-08 or 'Aug 2026'), or Enter for "
                    + label_from_key(fallback) + ": ").strip()
    except (EOFError, KeyboardInterrupt):
        print("")
        return fallback
    if not raw:
        return fallback
    if raw.isdigit() and 1 <= int(raw) <= len(shown):
        return shown[int(raw) - 1]["key"]
    parsed = parse_month(raw)
    if parsed and parsed in [x["key"] for x in available]:
        return parsed
    if parsed:
        print("  No data for " + label_from_key(parsed) + " - using "
              + label_from_key(fallback) + " instead.")
    else:
        print("  Could not read '" + raw + "' - using " + label_from_key(fallback) + " instead.")
    return fallback


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    today = date.today()
    want_latest = False
    just_list = False
    asked = None
    out_arg = None
    for a in argv:
        if a in ("--latest", "-l"):
            want_latest = True
        elif a in ("--list", "--months"):
            just_list = True
        elif a in ("-h", "--help"):
            print(__doc__ or "")
            print("Usage: python bender_dashboard_v3.py [MONTH] [--latest] [--list]")
            return
        elif a.startswith("--out="):
            out_arg = a.split("=", 1)[1]
        elif a.startswith("--month="):
            asked = a.split("=", 1)[1]
        elif a == "--month":
            continue
        elif not a.startswith("-"):
            asked = a

    plan_path = find_csv("Plan")
    reg_path  = find_csv("Register")
    plan = load_ynab_plan(plan_path)
    reg  = load_ynab_register(reg_path)
    if not plan or not reg:
        raise SystemExit("Could not find the YNAB Plan / Register CSV exports in " + SCRIPT_DIR)

    p    = load_params(TRACKER_FILE)
    loan = load_loan_info(TRACKER_FILE, today)
    inv  = load_buyout_savings(reg, today)   # was the Investments tab, now YNAB
    house = compute_house(p, loan, inv)

    available = month_summary(reg, plan, today)
    if not available:
        raise SystemExit("The register has no usable months.")
    keys = [x["key"] for x in available]
    fallback = default_month(available, today)

    if just_list:
        print("Months available in " + os.path.basename(reg_path) + ":")
        for x in available:
            print("  %-10s %5d txns  %10s assigned%s%s"
                  % (x["label"], x["txns"],
                     "$" + format(int(round(x["assigned"])), ","),
                     "  (in progress)" if x["partial"] else "",
                     "  <- default" if x["key"] == fallback else ""))
        return

    if FINANCE_MONTH:
        cur_key = FINANCE_MONTH
    elif asked:
        cur_key = parse_month(asked)
        if cur_key is None:
            raise SystemExit("Could not read the month '" + asked
                             + "'. Try 2026-08 or \"Aug 2026\", or --list.")
        if cur_key not in keys:
            raise SystemExit("No data for " + label_from_key(cur_key)
                             + ". Run with --list to see what is available.")
    elif want_latest or not sys.stdin.isatty():
        cur_key = fallback
    else:
        cur_key = choose_month(available, fallback, today)

    if cur_key not in keys:
        raise SystemExit("No data for " + label_from_key(cur_key)
                         + ". Run with --list to see what is available.")
    chosen = next(x for x in available if x["key"] == cur_key)
    if chosen["partial"]:
        print("  NOTE: " + chosen["label"] + " is the month in progress - it is very "
              "likely only part-budgeted.")

    months     = build_months(plan, reg)
    cat_by_month, cat_meta = build_category_index(plan)
    snapshots  = build_snapshots(reg, cur_key)
    prev_key   = month_range(cur_key, 2)[0]
    yr_ago_key = month_range(cur_key, 13)[0]
    earliest   = min(list(months) + sorted({t["key"] for t in reg})[:1])

    accounts, bucket_rows = net_worth_accounts(snapshots, cur_key, prev_key)
    txn = compute_transactions(reg, cur_key)

    windows = {}
    for wid, wlabel, wshort, wmonths in WINDOW_DEFS:
        keys = window_keys(cur_key, wmonths, earliest)
        w = compute_window(months, cat_by_month, cat_meta, cur_key, keys)
        w["id"] = wid
        w["label"] = wlabel
        w["short"] = wshort
        w["months"] = len(keys)
        w["span"] = label_from_key(keys[0]) + " - " + label_from_key(keys[-1])
        w["clamped"] = len(keys) < wmonths
        w["nw"] = net_worth_window(snapshots, keys)
        w["income_sources"] = income_sources(reg, cur_key, keys)
        windows[wid] = w

    pres = compute_presentation(plan, reg, months, cat_by_month, cat_meta,
                                cur_key, house, p, snapshots)

    fin_out = {
        "cur_label":    label_from_key(cur_key),
        "prev_label":   label_from_key(prev_key),
        "yr_ago_label": label_from_key(yr_ago_key),
        "window_order": [w[0] for w in WINDOW_DEFS],
        "default_window": DEFAULT_WINDOW,
        "windows":      windows,
        "nw_accounts":  accounts,
        "nw_buckets":   bucket_rows,
        "txn":          txn,
    }

    house_notes = [
        "<strong>Equity</strong> = the Bender half of the house value (" + fmt_money(p["bender_half_value"])
        + ") minus the Bender sub-account balance. It does not include any change in the house's market value.",
        "<strong>Amortization shaved this month</strong> compares where the balance would have landed on the scheduled payment alone "
        "(start balance + this month's interest - the payment) against where it actually landed. Both go through the same "
        "solve, so a month with no extra payment reads exactly zero and only extra principal moves the number.",
        "<strong>Baseline interest</strong> is charged at the same effective rate the tracker charged that month, not a flat "
        "rate/12. The tracker bills on an actual-day count, so the implied annual rate moves between roughly 3.6% and 4.2%; "
        "running the baseline on a flat rate would bank that wobble as fake saving.",
        "<strong>Months left</strong> is solved from the current balance at " + ("%.2f" % (p["rate"] * 100))
        + "% annual on the Bender scheduled payment of " + fmt_money(p["bender_payment"]) + "/mo, assuming no further extra payments.",
        "<strong>Baseline</strong> re-runs the Bender sub-account from the first tracked month paying only the scheduled payment - no extras, no partnership transfers. The gap between the two lines is what the extra payments have bought.",
        "<strong>Partnership transfers</strong> are stored once at full value in the tracker; each party is credited exactly half, so the history table shows the half that lands on the Bender side.",
        "<strong>Buyout snapshot</strong> uses today's balances: total to finance = Bender balance + the Martins' 50% share of "
        + fmt_money(p["house_value"] * (1 - p["bender_share"])) + ", capped at 80% LTV, with the remainder due as cash at closing.",
        "<strong>Cash saved toward buyout</strong> is Tim + Vivian's TFSA balances read straight from the YNAB register ("
        + ", ".join(sorted(inv["accounts"])) + "). The emergency-fund TFSA is excluded - it is not buyout money.",
        "<strong>Mortgage data</strong> runs through " + house["cur_label"] + " (" + str(house["months_elapsed"]) + " actual payment months).",
    ]

    money_notes = [
        "<strong>Source:</strong> the YNAB Plan (budget) and Register (ledger) exports sitting in this folder, re-read every time the script runs.",
        "<strong>The month shown</strong> is " + fin_out["cur_label"] + " - the last complete calendar month. The current partial month is deliberately excluded so comparisons are like-for-like.",
        "<strong>Money in</strong> = every transaction categorised Inflow: Ready to Assign. Transfers between your own accounts are never counted as income.",
        "<strong>Money out</strong> = activity in the Monthly, Cumulative, Tax Deductible and Hidden category groups. Credit-card payment categories are excluded - they move money, they do not spend it.",
        "<strong>Saved &amp; invested</strong> = activity in the Savings group (RESP, Retirement, Emergency Fund, House), excluding Investment Gain/Loss and Savings Expenses.",
        "<strong>Housing</strong> is the Amroth House category - the single monthly transfer that covers the mortgage and the Benders' share of house expenses.",
        "<strong>The comparison window</strong> (3 months / 12 months / 5 years) is switched with the buttons at the top of this tab. "
        "Every average, median, total, the two charts and the vs-average column follow it. A window is clamped to where the data actually "
        "starts, so the 5-year view covers " + windows["5y"]["span"] + " rather than padding with empty months.",
        "<strong>The median</strong> is shown next to every average because a few months carry large one-offs that pull the average around.",
        "<strong>Same month last year</strong> and the account table's month-on-month change are fixed comparisons - they do not follow the window.",
        "<strong>Net worth</strong> is every YNAB account balance rolled forward through " + fin_out["cur_label"]
        + ". It includes the tracked Amroth Equity account.",
        "<strong>The net worth chart</strong> stacks the balances by type, so the top of the stack is net worth itself. "
        "Credit-card balances are folded into Cash &amp; chequing (they are a claim on cash), which is why the stack totals "
        "net worth rather than gross assets - the account table below still lists cards separately.",
    ]

    data = {
        "generated": today.isoformat(),
        "params": {
            "rate_pct":       round(p["rate"] * 100, 2),
            "bender_payment": round(p["bender_payment"], 2),
            "bender_rent":    round(p["bender_rent"], 2),
            "house_value":    p["house_value"],
        },
        "house": house,
        "fin":   fin_out,
        "pres":  pres,
        "house_notes": house_notes,
        "money_notes": money_notes,
    }

    if out_arg:
        out_file = (out_arg if out_arg.lower().endswith(".html")
                    else os.path.join(out_arg, review_filename(cur_key)))
    else:
        out_file = os.path.join(OUTPUT_DIR, review_filename(cur_key))
    out_dir = os.path.dirname(os.path.abspath(out_file)) or "."
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)

    html = (TEMPLATE
            .replace("__DATA_JSON__", json.dumps(data, default=str))
            .replace("__PRES_MONTH__", pres["cur_label"])
            .replace("__GENERATED__", today.strftime("%B %-d, %Y") if os.name != "nt"
                     else today.strftime("%B %d, %Y").replace(" 0", " ")))

    with open(out_file, "w", encoding="utf-8") as fh:
        fh.write(html)

    index_path = write_index(out_dir, today.strftime("%d %b %Y"))

    print("Wrote " + out_file)
    print("Index " + index_path)
    print("  House   : " + house["cur_label"] + " vs " + str(house["prev_label"])
          + "  equity " + fmt_money(house["equity"]) + " (" + ("%+.0f" % house["equity_delta"]) + ")")
    dw = windows[DEFAULT_WINDOW]
    print("  Finances: " + fin_out["cur_label"] + "  in " + fmt_money(dw["headline"]["income"]["cur"])
          + " / out " + fmt_money(dw["headline"]["spend"]["cur"])
          + " / saved " + fmt_money(dw["headline"]["saved"]["cur"]))
    print("  Net worth: " + fmt_money(dw["nw"]["now"]["net"]))
    for wid, wlabel, _short, _n in WINDOW_DEFS:
        w = windows[wid]
        print("  Window %-16s %s (%d mo)  avg in %s / out %s"
              % (wlabel, w["span"], w["months"],
                 fmt_money(w["headline"]["income"]["avg"]),
                 fmt_money(w["headline"]["spend"]["avg"])))


def fmt_money(n):
    return "$" + format(round(n), ",d")


if __name__ == "__main__":
    main()
