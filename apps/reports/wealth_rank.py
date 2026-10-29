"""
Where a net worth ranks among the world's adults (docs/wealth-rank-plan.md).

The distribution is a list of published (percentile, wealth threshold) knots from the
World Inequality Database, already converted to CAD by `build_wealth_distribution`
and shipped as `data/global_wealth.json`. Between two knots the percentile is
linearly interpolated, so within a segment every dollar is worth the same number of
places; above the last knot (the top 0.001%) a Pareto tail fitted to that bracket's
average takes over. Pure: no database, no network.
"""

import json
import math
from bisect import bisect_right
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

GLOBAL_DISTRIBUTION_PATH = Path(__file__).resolve().parent / "data" / "global_wealth.json"


class DistributionError(ValueError):
    """The distribution file is malformed."""


@dataclass(frozen=True)
class WealthRank:
    wealth: Decimal  # the per-adult figure that was ranked
    percentile: float  # share of adults with less, 0-100
    rank: int  # 1 = richest
    population: int
    places_per_dollar: float | None  # None below the lowest threshold, where a dollar moves nothing
    data_year: int
    price_year: int
    source: str

    @property
    def top_pct(self) -> float:
        return 100.0 - self.percentile

    @property
    def top_pct_display(self) -> str:
        """Three significant figures, never scientific notation ("34.6", "0.00123")."""
        top = self.top_pct
        if top >= 100:
            return "100"
        if top <= 0:
            return "0"
        decimals = max(1, 2 - math.floor(math.log10(top)))
        return f"{top:.{decimals}f}"

    @property
    def population_billions(self) -> float:
        return self.population / 1e9

    @property
    def dollars_per_place(self) -> float | None:
        if not self.places_per_dollar:
            return None
        return 1 / self.places_per_dollar


@dataclass(frozen=True)
class Distribution:
    percentiles: tuple[float, ...]  # p_lower of each bracket, ascending
    thresholds: tuple[float, ...]  # minimum wealth of each bracket, CAD, non-decreasing
    top_average: float  # average wealth of the last bracket, CAD (fits the tail)
    population: int
    data_year: int
    price_year: int
    source: str

    @classmethod
    def from_dict(cls, data) -> "Distribution":
        points = data["points"]
        dist = cls(
            percentiles=tuple(float(p) for p, _ in points),
            thresholds=tuple(float(t) for _, t in points),
            top_average=float(data["top_bracket_average"]),
            population=int(data["adults"]),
            data_year=int(data["data_year"]),
            price_year=int(data["price_year"]),
            source=data["source"],
        )
        dist.validate()
        return dist

    def validate(self):
        if len(self.percentiles) < 2:
            raise DistributionError("A distribution needs at least two points.")
        if self.percentiles[0] != 0:
            raise DistributionError("The first point must be the 0th percentile.")
        pairs = zip(self.percentiles, self.percentiles[1:], strict=False)
        if any(b <= a for a, b in pairs) or self.percentiles[-1] >= 100:
            raise DistributionError("Percentiles must rise strictly and stay below 100.")
        if any(b < a for a, b in zip(self.thresholds, self.thresholds[1:], strict=False)):
            raise DistributionError("Thresholds must not fall as the percentile rises.")
        if self.thresholds[-1] <= 0 or self.top_average <= self.thresholds[-1]:
            raise DistributionError("The top bracket's average must exceed its positive threshold.")
        if self.population <= 0:
            raise DistributionError("The adult population must be positive.")

    @property
    def _tail(self) -> tuple[float, float]:
        """(share of adults above the last threshold, Pareto alpha)."""
        t, a = self.thresholds[-1], self.top_average
        # Pareto with threshold t has mean t * alpha / (alpha - 1); solve for alpha.
        return (100 - self.percentiles[-1]) / 100, a / (a - t)

    def locate(self, wealth: float) -> tuple[float, float | None]:
        """(percentile, places per dollar) for one adult's wealth."""
        p, t = self.percentiles, self.thresholds
        n = self.population
        if wealth < t[0]:
            return 0.0, None
        if wealth >= t[-1]:
            share, alpha = self._tail
            above = share * (wealth / t[-1]) ** -alpha
            return 100 * (1 - above), n * above * alpha / wealth
        # The last knot at or below `wealth`, so t[i] <= wealth < t[i + 1]: a run of equal
        # thresholds (a band of adults all at one figure) is stepped over, and the
        # segment never has zero width.
        i = bisect_right(t, wealth) - 1
        span = t[i + 1] - t[i]
        percentile = p[i] + (wealth - t[i]) / span * (p[i + 1] - p[i])
        return percentile, n * (p[i + 1] - p[i]) / 100 / span

    def rank_for(self, wealth) -> WealthRank:
        percentile, places = self.locate(float(wealth))
        richer = self.population * (1 - percentile / 100)
        return WealthRank(
            wealth=Decimal(wealth),
            percentile=percentile,
            rank=min(self.population, math.floor(richer) + 1),
            population=self.population,
            places_per_dollar=places,
            data_year=self.data_year,
            price_year=self.price_year,
            source=self.source,
        )


@lru_cache(maxsize=1)
def global_distribution() -> Distribution:
    return Distribution.from_dict(json.loads(GLOBAL_DISTRIBUTION_PATH.read_text()))


def global_rank(net_worth, adults: int = 1) -> WealthRank:
    """The world rank of a household's net worth, split equally between its adults."""
    return global_distribution().rank_for(Decimal(net_worth) / max(1, adults))
