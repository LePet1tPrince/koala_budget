# WID wealth-rank extract (Canada + World)

Source: WID bulk files WID_data_CA.csv, WID_data_WO-MER.csv, WID_data_WO-PPP.csv (6.4 GB folder -> ~1.7 MB here).
Variable: thwealj992 (threshold) + ahwealj992 (bracket average) = net personal wealth, adults 20+,
equal-split between spouses, constant 2025 prices. Percentiles: p0..p99 (1-pt), p99..p99.9 (0.1), p99.9..p99.99 (0.01), p99.99..p100 (0.001).

| File | Content |
|---|---|
| wealth_lookup_2024.csv | Latest year, wide: Canada (CAD), World market-FX (USD), World PPP (USD). 127 rows. |
| wealth_thresholds_all_years.csv | Same 3 series, every year available (CA 1820-2024, World 1820-2024), long format. |
| reference_rates_population.csv | CAD/USD market + PPP rates, price index, adult population, 1995-2025. |
| wealth_rank.py | `python wealth_rank.py <net_worth_CAD>` -> Canada + world percentile and approx. rank. |
| build_extract.py | Regenerates everything from the raw files. |

Method: linear interpolation between thresholds; Pareto tail above p99.999 (alpha from bracket average).
CAD -> USD uses 2025 rates (market 1.3607, PPP 1.1471) to match constant-2025 units.

Caveats:
- WID rates Canada's wealth series quality 0.1 (imputed). Distribution is lumpy (plateaus p25-p40 ~154k, p50-p70 ~268k CAD)
  and has no zero/negative wealth (p0 = 0, p1 = 48k CAD). Ranks for net worth < ~150k CAD in Canada are unreliable.
- World MER: dollars converted at market rates (standard for "global rich list"). PPP: adjusts for cost of living.
- Unit is the individual adult; for a couple, use half of household net worth.
