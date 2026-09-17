"""
Generate a realistic sample bank CSV for users who want to try the import flow
before they have a statement of their own to hand.

This is *not* seed data. Nothing is written to the database here -- the file is
handed to the user, who then walks it through the ordinary upload wizard exactly
as they would their own statement. They see the real flow, and the rows that land
in their books are ones they knowingly imported and can delete.

Two details matter for the file to behave like a real bank export:

* **Dual amount columns.** ``BankTransaction.amount`` follows the Plaid
  convention (positive = money out). A single ``Amount`` column would therefore
  need a *negative* number for a paycheque, which looks wrong to anyone who opens
  the file. ``Funds In`` / ``Funds Out`` reads naturally, is auto-detected by the
  column-mapping step's keyword list, and is converted to the internal convention
  by the dual-column branch of ``preview_transactions``.
* **Dates relative to today.** A file with hardcoded dates would be describing
  someone's ancient history a year after it was written, and would land outside
  the budget month the walkthrough then asks the user to set. Rows are generated
  for the three complete months before this one, plus the current month up to
  today -- so the income statement has several periods to compare and the current
  month has actuals to check a budget against.
"""

import calendar
import csv
import io
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from dateutil.relativedelta import relativedelta

CSV_HEADERS = ["Date", "Description", "Funds In", "Funds Out"]

# How many complete months precede the current (partial) one.
COMPLETE_MONTHS = 3


@dataclass(frozen=True)
class SampleRow:
    """One recurring line in the fictional account's month."""

    day: int
    description: str
    inflow: Decimal = Decimal("0")
    outflow: Decimal = Decimal("0")
    # Fixed costs (rent, subscriptions) repeat to the cent; everyday spending
    # varies month to month so the charts and the budget-vs-actual view have
    # something to show.
    varies: bool = False


def _d(value: str) -> Decimal:
    return Decimal(value)


# A single month in the life of a fictional chequing account, in CAD.
# Net positive by roughly $1,700/month, so net worth visibly climbs.
MONTHLY_PATTERN: list[SampleRow] = [
    SampleRow(1, "RENT PAYMENT - PROPERTY MGMT", outflow=_d("1850.00")),
    SampleRow(2, "PRESTO FARE RELOAD", outflow=_d("156.00"), varies=True),
    SampleRow(3, "LOBLAWS #1042", outflow=_d("142.68"), varies=True),
    SampleRow(4, "TIM HORTONS #3318", outflow=_d("6.85"), varies=True),
    SampleRow(6, "NETFLIX.COM", outflow=_d("20.99")),
    SampleRow(8, "PETRO-CANADA 07231", outflow=_d("68.40"), varies=True),
    SampleRow(9, "SHOPPERS DRUG MART", outflow=_d("34.20"), varies=True),
    SampleRow(11, "LOBLAWS #1042", outflow=_d("92.15"), varies=True),
    SampleRow(12, "ROGERS WIRELESS", outflow=_d("121.47")),
    SampleRow(15, "PAYROLL DEPOSIT - ACME LOGISTICS", inflow=_d("2450.00")),
    SampleRow(15, "TRANSFER TO SAVINGS", outflow=_d("400.00")),
    SampleRow(17, "TORONTO HYDRO", outflow=_d("94.63"), varies=True),
    SampleRow(18, "THE KEG STEAKHOUSE", outflow=_d("78.50"), varies=True),
    SampleRow(21, "LOBLAWS #1042", outflow=_d("118.04"), varies=True),
    SampleRow(23, "TIM HORTONS #3318", outflow=_d("4.95"), varies=True),
    SampleRow(24, "SPOTIFY PREMIUM", outflow=_d("11.99")),
    SampleRow(26, "PETRO-CANADA 07231", outflow=_d("61.25"), varies=True),
    SampleRow(28, "INTEREST PAID", inflow=_d("1.34")),
    SampleRow(30, "PAYROLL DEPOSIT - ACME LOGISTICS", inflow=_d("2450.00")),
]

# Applied to `varies=True` amounts, indexed by how many months back the month is.
# Fixed rather than random so the same day always produces the same file -- which
# keeps the tests meaningful and means two users comparing notes see the same thing.
VARIATION = [Decimal("1.00"), Decimal("0.91"), Decimal("1.12"), Decimal("0.96")]


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _format(value: Decimal) -> str:
    """Blank rather than 0.00 for the unused side, as bank exports do."""
    return f"{_money(value):.2f}" if value else ""


def sample_rows(today: date | None = None) -> list[tuple[date, str, Decimal, Decimal]]:
    """
    Build the sample transactions as ``(date, description, inflow, outflow)``.

    Returns them oldest first, covering ``COMPLETE_MONTHS`` whole months plus the
    current month up to and including ``today``.
    """
    today = today or date.today()
    current_month = today.replace(day=1)

    rows: list[tuple[date, str, Decimal, Decimal]] = []

    # Oldest month first; offset 0 is the current, partial month.
    for months_back in range(COMPLETE_MONTHS, -1, -1):
        month_start = current_month - relativedelta(months=months_back)
        factor = VARIATION[months_back % len(VARIATION)]
        days_in_month = calendar.monthrange(month_start.year, month_start.month)[1]

        for row in MONTHLY_PATTERN:
            posted = month_start.replace(day=min(row.day, days_in_month))
            if posted > today:
                # The current month has not finished happening yet.
                continue

            inflow = row.inflow
            outflow = row.outflow
            if row.varies:
                inflow = _money(inflow * factor)
                outflow = _money(outflow * factor)

            rows.append((posted, row.description, inflow, outflow))

    rows.sort(key=lambda r: r[0])
    return rows


def build_sample_csv(today: date | None = None) -> str:
    """Render the sample transactions as CSV text, headers included."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_HEADERS)

    for posted, description, inflow, outflow in sample_rows(today):
        writer.writerow([posted.isoformat(), description, _format(inflow), _format(outflow)])

    return buffer.getvalue()
