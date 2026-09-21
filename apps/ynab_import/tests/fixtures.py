"""
Two exports to test against.

The real one in `docs/reference/` is the point: every figure the plan asserts was
measured on it, so it is the fixture that proves the import against something a
person actually budgeted in. The tiny synthetic one exists for the cases the real
export happens not to contain (an account dropped, a liability, a rename) and for
tests where reading 10,500 rows would be the slowest thing in the file.
"""

import glob
import os
from functools import lru_cache

from apps.ynab_import.services.analyse import analyse
from apps.ynab_import.services.parse import parse_plan, parse_register

REFERENCE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "docs",
    "reference",
)


def sample_bytes(pattern: str) -> bytes:
    matches = glob.glob(os.path.join(REFERENCE, pattern))
    if not matches:
        raise FileNotFoundError(f"No sample export matching {pattern!r} in {REFERENCE}")
    with open(matches[0], "rb") as handle:
        return handle.read()


@lru_cache(maxsize=1)
def sample_register_bytes() -> bytes:
    return sample_bytes("*Register.csv")


@lru_cache(maxsize=1)
def sample_plan_bytes() -> bytes:
    return sample_bytes("*Plan.csv")


@lru_cache(maxsize=1)
def sample_analysis():
    """Parsed once for the whole test run: it is pure, so it cannot be dirtied."""
    return analyse(parse_register(sample_register_bytes()), parse_plan(sample_plan_bytes()))


# ---------------------------------------------------------------------------
# A small, hand-written export
# ---------------------------------------------------------------------------

REGISTER_HEADER = (
    '"Account","Flag","Date","Payee","Category Group/Category","Category Group","Category",'
    '"Memo","Outflow","Inflow","Cleared"'
)

# account, date, payee, group, category, memo, outflow, inflow, cleared
TINY_ROWS = [
    ("Chequing", "01-01-2024", "Starting Balance", "Inflow", "Ready to Assign", "", "0.00", "500.00", "Reconciled"),
    ("Visa", "01-01-2024", "Starting Balance", "", "", "", "120.00", "0.00", "Reconciled"),
    ("Chequing", "05-01-2024", "Employer", "Inflow", "Ready to Assign", "Pay day", "0.00", "2000.00", "Reconciled"),
    ("Chequing", "06-01-2024", "Grocer", "Monthly", "Groceries", "Weekly shop", "80.00", "0.00", "Reconciled"),
    ("Visa", "07-01-2024", "Cafe", "Monthly", "Groceries", "Split (1/2)", "6.00", "0.00", "Cleared"),
    ("Visa", "07-01-2024", "Cafe", "Monthly", "Fun", "Split (2/2)", "4.00", "0.00", "Cleared"),
    ("Chequing", "08-01-2024", "Transfer : Savings", "Savings", "House", "To savings", "300.00", "0.00", "Reconciled"),
    ("Savings", "08-01-2024", "Transfer : Chequing", "", "", "To savings", "0.00", "300.00", "Uncleared"),
    ("Savings", "09-01-2024", "Interest", "", "", "Monthly interest", "0.00", "1.25", "Uncleared"),
]


def register_csv(rows=None) -> str:
    """The rows as YNAB writes them: quoted, with the currency symbol trailing."""
    lines = [REGISTER_HEADER]
    for account, day, payee, group, category, memo, outflow, inflow, cleared in rows or TINY_ROWS:
        combined = f"{group}: {category}" if category else ""
        lines.append(
            f'"{account}","","{day}","{payee}","{combined}","{group}","{category}",'
            f'"{memo}",{outflow}$,{inflow}$,"{cleared}"'
        )
    return "\n".join(lines) + "\n"


TINY_REGISTER = register_csv()

TINY_PLAN = """\
"Month","Category Group/Category","Category Group","Category","Assigned","Activity","Available"
"Jan 2024","Credit Card Payments: Visa","Credit Card Payments","Visa",10.00$,0.00$,10.00$
"Jan 2024","Monthly: Groceries","Monthly","Groceries",100.00$,-86.00$,14.00$
"Jan 2024","Monthly: Fun","Monthly","Fun",0.00$,-4.00$,-4.00$
"Jan 2024","Savings: House","Savings","House",300.00$,-300.00$,0.00$
"Feb 2024","Credit Card Payments: Visa","Credit Card Payments","Visa",0.00$,0.00$,10.00$
"Feb 2024","Monthly: Groceries","Monthly","Groceries",50.00$,0.00$,64.00$
"Feb 2024","Monthly: Fun","Monthly","Fun",20.00$,0.00$,20.00$
"Feb 2024","Savings: House","Savings","House",0.00$,0.00$,0.00$
"""


def tiny_analysis():
    return analyse(parse_register(TINY_REGISTER.encode()), parse_plan(TINY_PLAN.encode()))
