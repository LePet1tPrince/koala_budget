"""
Build `apps/reports/data/global_wealth.json` from the WID extract in `data/wid/`.

The extract (`data/wid/build_extract.py`, run against the WID bulk download) holds the
world's net-personal-wealth thresholds at market exchange rates, in USD at constant
prices of the latest year, plus exchange rates and adult population. This converts the
thresholds to CAD at that same year's market rate -- the prices the thresholds are
already expressed in -- and writes the knots `apps.reports.wealth_rank` reads.

    python manage.py build_wealth_distribution [--year 2024] [--source-dir data/wid]
"""

import csv
import json
import re
from datetime import date
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.reports.wealth_rank import GLOBAL_DISTRIBUTION_PATH, Distribution, DistributionError

WORLD = "WO-MER"
CANADA = "CA"
# Cross-checks against the UBS Global Wealth Report 2026 (2025 data): about 41% of
# adults below US$10,000 and about 1.5% above US$1M. Printed, not enforced: the two
# sources are built differently.
CROSS_CHECKS_USD = (10_000, 1_000_000)


class Command(BaseCommand):
    help = "Build the global wealth distribution (CAD) from the WID extract in data/wid/."

    def add_arguments(self, parser):
        parser.add_argument("--source-dir", default=str(Path(settings.BASE_DIR) / "data" / "wid"))
        parser.add_argument("--year", type=int, help="Data year (default: the latest wealth_lookup_<year>.csv).")
        parser.add_argument("--output", default=str(GLOBAL_DISTRIBUTION_PATH))

    def handle(self, *args, source_dir, year, output, **options):
        source = Path(source_dir)
        year = year or self._latest_year(source)
        lookup = source / f"wealth_lookup_{year}.csv"
        if not lookup.exists():
            raise CommandError(f"{lookup} not found.")

        reference = self._reference(source / "reference_rates_population.csv")
        price_year = self._price_year(reference)
        try:
            cad_per_usd = reference[(CANADA, price_year, "xlcusxi999")]
            adults = round(reference[(WORLD, year, "npopuli992")])
        except KeyError as missing:
            raise CommandError(f"reference_rates_population.csv has no {missing}.") from missing

        with lookup.open(newline="") as f:
            rows = list(csv.DictReader(f))
        points = [[float(r["p_lower"]), round(float(r["world_threshold_usd_mer"]) * cad_per_usd, 2)] for r in rows]
        top_average = round(float(rows[-1]["world_bracket_avg_usd_mer"]) * cad_per_usd, 2)

        data = {
            "source": "World Inequality Database (WID.world)",
            "url": "https://wid.world/data/",
            "series": f"thwealj992 / ahwealj992, {WORLD}: net personal wealth, adults 20+, equal-split",
            "data_year": year,
            "price_year": price_year,
            "currency": "CAD",
            "cad_per_usd": round(cad_per_usd, 6),
            "adults": adults,
            "built": date.today().isoformat(),
            "top_bracket_average": top_average,
            "points": points,
        }
        try:
            dist = Distribution.from_dict(data)
        except DistributionError as error:
            raise CommandError(f"{lookup}: {error}") from error

        Path(output).write_text(_dump(data))
        self.stdout.write(
            f"Wrote {output}: {len(points)} points, {year} data in {price_year} prices, {adults:,} adults"
        )
        for usd in CROSS_CHECKS_USD:
            self.stdout.write(f"  below US${usd:,}: {dist.locate(usd * cad_per_usd)[0]:.1f}% of adults")

    @staticmethod
    def _latest_year(source):
        names = (p.name for p in source.glob("wealth_lookup_*.csv"))
        years = [int(m.group(1)) for name in names if (m := re.search(r"_(\d{4})\.csv$", name))]
        if not years:
            raise CommandError(f"No wealth_lookup_<year>.csv in {source}.")
        return max(years)

    @staticmethod
    def _reference(path):
        with path.open(newline="") as f:
            return {(r["region"], int(r["year"]), r["variable"]): float(r["value"]) for r in csv.DictReader(f)}

    @staticmethod
    def _price_year(reference):
        """The year the extract's constant prices are in: where the world price index is 1."""
        years = [y for (region, y, var), v in reference.items() if region == WORLD and var == "inyixxi999" and v == 1]
        if len(years) != 1:
            raise CommandError("Can't tell the price year: expected one year with a world price index of 1.")
        return years[0]


def _dump(data):
    """Indented JSON with one point per line, so a rebuild's diff reads point by point."""
    head = json.dumps({k: v for k, v in data.items() if k != "points"}, indent=1)[:-2]
    points = ",\n".join(f"  {json.dumps(point)}" for point in data["points"])
    return f'{head},\n "points": [\n{points}\n ]\n}}\n'
