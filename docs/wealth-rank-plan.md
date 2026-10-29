# Wealth rank — plan

Status: **phase 1 (global) built.** See §9 for what the build settled.

Goal: on the Net Worth report (`reports:net_worth`), show where the book's net worth ranks among
the world's adults, as a percentile **and** an absolute place ("#2,780,000 of 5.6 billion"), plus how
many places one more dollar buys. Later phases add Canada and the user's province/city.

---

## 1. Income vs wealth

The request says "income distribution", but the figure being ranked is **net worth**, so the data has
to be a **wealth** distribution: assets minus debts, per adult. Ranking net worth against an income
distribution would compare a stock with a flow, and the result would mean nothing. Everything below
uses wealth data.

---

## 2. Source

### Candidates

| Source | What it publishes | Granularity | Licence / access | Verdict |
|---|---|---|---|---|
| **World Inequality Database (WID.world)**, World Inequality Lab (Paris School of Economics) | Net personal wealth per adult (`hweal`), world aggregate, annual | **127 "g-percentiles"**: p0–p99 by 1%, p99–p99.9 by 0.1%, p99.9–p99.99 by 0.01%, p99.99–p99.999 by 0.001%. Each has a **threshold** (`thweal`), average (`ahweal`) and inverted-Pareto coefficient (`bhweal`) | Free bulk CSV download + API. Open data with attribution (licence to be confirmed on download, §8) | **Use this** |
| UBS Global Wealth Report 2026 (2025 data; formerly Credit Suisse) | Adults by wealth band in USD | **4 bands** publicly (<$10k, $10k–100k, $100k–1M, >$1M). The per-decile "Databook" tables are no longer published | Proprietary PDF | Cross-check only |
| Statistics Canada, Survey of Financial Security | Canadian household net worth | Quintiles/percentiles, by province | Open | Phase 2/3 (Canada, local) |

### Why WID

1. **Thresholds at fine percentiles.** Linear interpolation needs known (percentile, wealth) points.
   WID gives 127 of them, densest at the top where wealth rises fastest. UBS's 4 bands would
   interpolate across $90,000 gaps.
2. **The whole distribution, including negatives.** WID thresholds in the bottom percentiles are
   negative (net debtors), so a book with negative net worth still gets a rank.
3. **One source for everything.** Population (`npopul`), wealth thresholds and the market exchange
   rates to convert them (`xlceux`) all come from the same release and the same data year, so no
   figures from different sources get mixed.
4. **Reproducible.** It's a downloadable dataset with documented variable codes
   (wid.world/codes-dictionary), updated yearly. The Dec 2025 technical note (2025/10) extends the
   series through 2024.
5. **Standing.** It's the dataset behind the World Inequality Report 2026. UBS's own figures are
   modelled estimates that aren't published at percentile level.

UBS is a sanity check: its 2025 data has about 41% of adults below US$10,000 and about 1.5–1.6%
above US$1M. After conversion, WID's thresholds should land in the same region at those two points.
If they don't, the unit choice in §3 is wrong.

### Series to download

| Code | Meaning |
|---|---|
| `thweal_pXpY_992_j` | Threshold of net personal wealth at g-percentile `pXpY`, adults 20+ (`992`), equal-split (`j`) |
| `bhweal_p99.999p100_992_j` | Inverted Pareto coefficient at the top, for the tail (§4) |
| `npopul_992_i` | Number of adults 20+ |
| `xlceux_999_i` (Canada) | Market exchange rate, CAD per EUR |

Region: **world at market exchange rates** (WID's `WO-MER` aggregate, rather than the default `WO`,
which is PPP). The exact code needs confirming against the download.

---

## 3. Units

**Market exchange rate, not PPP.** PPP answers "what could you buy locally". The question here is
"how does your money compare with everyone else's", and that means converting everyone at market
rates. Global-rank calculators and UBS both use market rates. PPP inflates poor countries' wealth,
so the same Canadian would rank noticeably lower under it.

**Conversion to CAD:** `threshold_CAD = threshold_EUR(MER) × xlceux(Canada, data year)`, applied once
at build time. CAD is what's stored, so the app does no currency maths at runtime.

**Price year.** The thresholds are in data-year money (2024), while the user's net worth is 2026
CAD. No adjustment is proposed: inflating the thresholds by Canadian CPI would be inventing data,
because world wealth didn't grow at Canadian inflation. The UI shows the year ("Based on 2024 world
data"). Expect the thresholds to be about 5–10% stale each year until the next release.

**Per adult (equal-split).** WID's unit is one adult, with household wealth split equally between
the adults in it. A book is usually a household's books, so a couple sharing one book would be
ranked as one person with twice the wealth unless the book says how many adults it covers.
→ New `Book.household_adults` (default 1, set on book General settings). The rank uses
`net_worth / household_adults`, and the UI says "per adult" whenever it isn't 1.

---

## 4. Rank calculation

Knots: `(p_i, t_i)` for the 127 g-percentiles, with `p` in [0, 100) and `t` in CAD, sorted. Adult
population: `N`.

**Percentile (share of adults poorer than you)**, for `t_i ≤ w < t_{i+1}`:

```
p(w) = p_i + (w − t_i) / (t_{i+1} − t_i) × (p_{i+1} − p_i)
```

**Absolute rank** (1 = richest):

```
rank(w) = round(N × (1 − p(w) / 100)) + 1      → "You are #2,780,000"
```

**Places per dollar** (what the user asked for: "+$1 = up 40 places"). This is constant inside a
segment, so it's exact under linear interpolation:

```
places_per_dollar = N × (p_{i+1} − p_i) / 100 / (t_{i+1} − t_i)
```

**Edges**

| Case | Rule |
|---|---|
| `w < t_0` (below the lowest threshold) | `p = 0`, rank = `N` (last) |
| `w ≥ t_last` (top 0.001%, about 56,000 adults) | Pareto tail: `share_above(w) = (1 − p_last/100) × (w / t_last)^(−α)`, with `α = b / (b − 1)` from `bhweal`. Linear interpolation has nothing to interpolate to here, and clamping would tell a billionaire they're tied with 56,000 people. |
| Zero-width segment (`t_i == t_{i+1}`, e.g. a band of people at exactly $0) | Skip it when searching (no division by zero). A user exactly on that value gets the top of the band. |
| `places_per_dollar` < 1 (the far top) | Show "$X per place" instead. |

**Order of magnitude (illustrative, not measured: real figures come from the download).** With
N ≈ 5.6 bn adults, one percentile is about 56 M people.
- Near the median, thresholds a percentile apart differ by roughly US$1,000 → tens of thousands
  of places per dollar.
- Around the top 1% (US$1M+), 0.1% = 5.6 M people over a step of roughly US$100k+ → about **40
  places per dollar**, which is the example in the request.

The number moves a lot with wealth, and that's what makes it interesting to show.

---

## 5. Storage — no runtime network

The data changes once a year, so it ships with the code.

- `apps/reports/data/global_wealth.json` — committed and generated, never hand-edited:
  ```json
  {
    "source": "World Inequality Database (WID.world)",
    "url": "https://wid.world/data/",
    "licence": "…",
    "series": "thweal_*_992_j, WO-MER",
    "data_year": 2024,
    "built": "2026-10-28",
    "currency": "CAD",
    "fx_cad_per_eur": 1.48,
    "adults": 5600000000,
    "tail_b": 1.9,
    "points": [[0.0, -12345.0], [1.0, -2100.0], …, [99.999, 123456789.0]]
  }
  ```
  (values above are placeholders)
- `manage.py build_wealth_distribution --csv <WID download> [--year 2024]` reads the WID bulk CSV
  and writes the JSON. It refuses non-monotonic thresholds or a missing g-percentile, and prints the
  UBS cross-check (share below US$10k, share above US$1M).
- The JSON is read once per process (`functools.lru_cache`).

---

## 6. Code

| Piece | Where |
|---|---|
| `WealthDistribution` (load + validate) and `rank_for(wealth) -> WealthRank(percentile, top_pct, rank, population, places_per_dollar, data_year, source)` — pure, no DB | `apps/reports/wealth_rank.py` |
| Builder command | `apps/reports/management/commands/build_wealth_distribution.py` |
| `Book.household_adults` + migration, field on `BookSettingsForm` | `apps/books` |
| `stats["global_rank"] = rank_for(end_worth / book.household_adults)` | `apps/reports/consolidated.py::net_worth_report` |
| Fifth stat in the summary strip: **Global wealth rank**, `#2,780,000`, desc "Top 34.6% of 5.6 B adults · +40 places per $1", source footnote with year and attribution | `templates/reports/consolidated/net_worth.html` (`global-wealth-rank` testid) |

The stat uses the report's **end date** net worth, the same figure as the "Net worth" stat.

Tests (`apps/reports/tests/test_wealth_rank.py`):
- exact at every knot
- midpoint of a segment
- monotonic in `w`
- negative wealth
- below `t_0`
- the Pareto tail is continuous at `t_last`
- zero-width segments
- `places_per_dollar` matches the rank difference for `w` and `w + 1` (within rounding)
- `household_adults` divides
- the report view renders the stat
- the shipped JSON passes validation (so a bad rebuild fails CI)

---

## 7. Later phases

- **National (Canada):** Statistics Canada, Survey of Financial Security (latest 2023), net worth by
  percentile, for economic families and unattached individuals. It's a household unit rather than
  per adult, so the conversion needs deciding then. Alternatively the quarterly Distributions of
  Household Economic Accounts (wealth by quintile, top 1%). Same interpolation engine, different
  JSON.
- **Local:** SFS by province (cities are too thin a sample). Needs a "where do you live" setting on
  the book.

The engine in §4 is source-agnostic: each level is one JSON file of `(percentile, threshold)` knots
plus a population.

---

## 8. Open items / blockers

1. ~~Network~~: resolved, the extract was supplied in `data/wid/`.
2. Confirm on download:
   - the MER world region code
   - the latest data year
   - the exact licence text, so the attribution string is correct
3. Decisions: `household_adults` on the book (recommended), and market rates rather than PPP
   (recommended).

---

## 9. Built (phase 1)

- **Data**: the WID bulk download (6.4 GB) was reduced offline by `data/wid/build_extract.py` to
  `data/wid/` (1.7 MB: every year, Canada + world at market rates + world PPP, plus exchange rates
  and population). The app ships only `apps/reports/data/global_wealth.json` (2.9 KB: 127 knots, CAD),
  built from that extract by `manage.py build_wealth_distribution`.
- **Units settled**: WID series `thwealj992`/`ahwealj992`, region `WO-MER`, **2024 data in constant 2025
  prices**, so thresholds are converted at the **2025** CAD/USD market rate (1.3607). The price-year
  caveat in §3 mostly goes away: thresholds are already in 2025 dollars. 5,493,281,049 adults (2024).
- **Cross-check**: WID puts 50.0% of adults below US$10k (UBS: ~41%) and 1.3% above US$1M (UBS: ~1.5%).
  Same region, different methods; WID is used as is.
- **Tail**: the Pareto alpha comes from the top bracket's average (`alpha = avg / (avg - threshold)`)
  rather than `bhweal`; same thing, already in the extract.
- **Code**: `apps/reports/wealth_rank.py` (`Distribution.locate`/`rank_for`, `global_rank(net_worth,
  adults)`); `Book.household_adults` (1-10, books migration `0004`) on book General settings;
  "Where you rank" card on `reports:net_worth` (`wealth-rank`, `global-wealth-rank*` testids) ranking the
  end-of-range net worth. Rank = `floor(N × (1 − p/100)) + 1`. Tests: `apps/reports/test_wealth_rank.py`
  (including agreement with the extract's own `data/wid/wealth_rank.py`).
- **Not yet**: Canada and local levels (§7). The extract already holds Canada's distribution, but WID
  rates its quality low (0.1, imputed, no negative wealth, plateaus): phase 2 should compare it with
  Statistics Canada's SFS before using it.
