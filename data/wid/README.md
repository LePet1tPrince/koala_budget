# WID.world source files

Raw input for the global wealth rank (`docs/wealth-rank-plan.md`). Not read at runtime: a build step
turns these into `apps/reports/data/global_wealth.json`.

Expected files, as downloaded from https://wid.world/data/ ("Download full dataset"):

| File | Contents |
|---|---|
| `WID_data_WO*.csv` | World aggregates: wealth thresholds (`thweal`), Pareto coefficients (`bhweal`), adult population (`npopul`) |
| `WID_data_CA.csv` | Canada: market exchange rate CAD per EUR (`xlceux`) |
| `WID_metadata_*.csv` | Matching metadata files, if present (units, sources) |

Keep the original file names.
