"""Tests for the global wealth rank (docs/wealth-rank-plan.md)."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from .consolidated import net_worth_report
from .test_consolidated import ConsolidatedReportsBase
from .wealth_rank import Distribution, DistributionError, global_distribution, global_rank


def distribution(points, top_average=2000, population=1000):
    return Distribution.from_dict(
        {
            "points": points,
            "top_bracket_average": top_average,
            "adults": population,
            "data_year": 2024,
            "price_year": 2025,
            "source": "Test",
        }
    )


SIMPLE = [[0, -100], [50, 0], [90, 100], [99, 1000]]


class InterpolationTest(SimpleTestCase):
    def setUp(self):
        self.dist = distribution(SIMPLE)

    def test_exact_at_every_knot(self):
        for percentile, threshold in SIMPLE:
            self.assertAlmostEqual(self.dist.locate(threshold)[0], percentile)

    def test_linear_inside_a_segment(self):
        percentile, places = self.dist.locate(50)
        self.assertAlmostEqual(percentile, 70)
        # 40% of 1,000 adults over $100.
        self.assertAlmostEqual(places, 4)

    def test_negative_wealth_ranks(self):
        self.assertAlmostEqual(self.dist.locate(-50)[0], 25)

    def test_below_the_lowest_threshold_is_last(self):
        rank = self.dist.rank_for(-500)
        self.assertEqual((rank.percentile, rank.rank, rank.places_per_dollar), (0.0, 1000, None))

    def test_rank_counts_richer_adults(self):
        self.assertEqual(self.dist.rank_for(50).rank, 301)  # 30% of 1,000 are richer
        self.assertEqual(self.dist.rank_for(10**12).rank, 1)

    def test_a_band_at_one_figure_is_stepped_over(self):
        dist = distribution([[0, 0], [10, 0], [20, 0], [30, 10], [99, 1000]])
        self.assertAlmostEqual(dist.locate(0)[0], 20)  # the top of the band
        self.assertAlmostEqual(dist.locate(5)[0], 25)

    def test_pareto_tail_is_continuous_and_falls_off(self):
        self.assertAlmostEqual(self.dist.locate(1000)[0], 99)
        self.assertAlmostEqual(self.dist.locate(1000.0001)[0], 99, places=5)
        # alpha = 2000 / (2000 - 1000) = 2: share above $2,000 = 1% * 2^-2.
        self.assertAlmostEqual(self.dist.locate(2000)[0], 99.75)

    def test_malformed_distributions_are_refused(self):
        for points, top_average in (
            ([[1, 0], [50, 10]], 100),  # does not start at 0
            ([[0, 10], [50, 5]], 100),  # threshold falls
            ([[0, 0], [50, 5], [50, 6]], 100),  # percentile repeats
            ([[0, 0], [50, 10]], 10),  # top average not above its threshold
        ):
            with self.subTest(points=points), self.assertRaises(DistributionError):
                distribution(points, top_average=top_average)

    def test_top_pct_display(self):
        for percentile, expected in ((84.069, "15.9"), (99.9987655, "0.00123"), (0, "100"), (95, "5.00")):
            rank = replace(self.dist.rank_for(0), percentile=percentile)
            self.assertEqual(rank.top_pct_display, expected)


class ShippedDistributionTest(SimpleTestCase):
    """The committed `data/global_wealth.json` (WID 2024, CAD)."""

    def setUp(self):
        self.dist = global_distribution()

    def test_it_loads_and_covers_every_g_percentile(self):
        self.assertEqual(len(self.dist.percentiles), 127)
        self.assertEqual((self.dist.data_year, self.dist.price_year), (2024, 2025))
        self.assertGreater(self.dist.population, 5_000_000_000)

    def test_matches_the_reference_script(self):
        """`data/wid/wealth_rank.py`, which ranks in USD instead of converting the thresholds to CAD."""
        for wealth, percentile, rank in ((100_000, 84.0690, 875_136_417), (1_000_000, 97.7205, 125_221_401)):
            result = self.dist.rank_for(wealth)
            self.assertAlmostEqual(result.percentile, percentile, places=3)
            self.assertLess(abs(result.rank - rank), 100)

    def test_monotonic(self):
        previous = -1.0
        for wealth in range(-200_000, 3_000_000, 997):
            percentile = self.dist.locate(wealth)[0]
            self.assertGreaterEqual(percentile, previous)
            previous = percentile

    def test_places_per_dollar_is_the_rank_change_of_one_dollar(self):
        for wealth in (0, 25_000, 100_000, 1_000_000, 10_000_000):
            with self.subTest(wealth=wealth):
                before, after = self.dist.rank_for(wealth), self.dist.rank_for(wealth + 1)
                self.assertAlmostEqual(before.rank - after.rank, before.places_per_dollar, delta=1)

    def test_household_adults_split_the_net_worth(self):
        self.assertEqual(global_rank(Decimal("200000"), adults=2).wealth, Decimal("100000"))
        self.assertEqual(global_rank(Decimal("200000"), adults=2).rank, global_rank(Decimal("100000")).rank)


class NetWorthReportRankTest(ConsolidatedReportsBase):
    def test_report_ranks_the_end_of_range_net_worth(self):
        self.post(date(2026, 1, 5), self.bank, self.salary, "50000.00")
        report = net_worth_report(self.book, date(2026, 1, 1), date(2026, 1, 31))
        self.assertEqual(report["wealth_rank"].wealth, report["stats"]["net_worth"])

    def test_report_shows_the_rank(self):
        self.post(date(2026, 1, 5), self.bank, self.salary, "50000.00")
        response = self.client.get(self.url("net_worth"), {"start_month": "2026-01", "end_month": "2026-01"})
        self.assertContains(response, 'data-testid="global-wealth-rank"')
        rank = global_rank(Decimal("50000")).rank
        self.assertContains(response, f"#{rank:,}")
        self.assertContains(response, "as one adult")

    def test_report_ranks_per_adult(self):
        self.book.household_adults = 2
        self.book.save()
        self.post(date(2026, 1, 5), self.bank, self.salary, "50000.00")
        response = self.client.get(self.url("net_worth"), {"start_month": "2026-01", "end_month": "2026-01"})
        self.assertContains(response, f"#{global_rank(Decimal('25000')).rank:,}")
        self.assertContains(response, "split between 2 adults")
