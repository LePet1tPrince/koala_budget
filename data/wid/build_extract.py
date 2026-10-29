"""Rebuilds the extract from the raw WID bulk files in the parent folder."""

import csv
import os
import re

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.dirname(os.path.abspath(__file__))
REGIONS = {"CA": "CAD", "WO-MER": "USD (market exchange rates)", "WO-PPP": "USD (PPP)"}
pat = re.compile(r"^p([\d.]+)p([\d.]+)$")


def fine(lo, hi):  # keep only single-step generalized percentiles
    step = 1 if lo < 99 else 0.1 if lo < 99.9 else 0.01 if lo < 99.99 else 0.001
    return abs((hi - lo) - step) < 1e-9


rows, ref = {}, {}
for reg in REGIONS:
    with open(os.path.join(SRC, f"WID_data_{reg}.csv"), newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter=";"):
            v = r["variable"]
            if v in ("thwealj992", "ahwealj992"):
                m = pat.match(r["percentile"])
                if not m:
                    continue
                lo, hi = float(m.group(1)), float(m.group(2))
                if not fine(lo, hi):
                    continue
                k = (reg, int(r["year"]), lo, hi)
                rows.setdefault(k, {})[v] = r["value"]
            elif r["percentile"] == "p0p100" and v in ("xlcusxi999", "xlcuspi999", "inyixxi999", "npopuli992"):
                ref[(reg, int(r["year"]), v)] = r["value"]

with open(os.path.join(OUT, "wealth_thresholds_all_years.csv"), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["region", "year", "p_lower", "p_upper", "threshold", "bracket_avg", "unit"])
    for k in sorted(rows):
        reg, yr, lo, hi = k
        d = rows[k]
        w.writerow(
            [
                reg,
                yr,
                f"{lo:g}",
                f"{hi:g}",
                d.get("thwealj992", ""),
                d.get("ahwealj992", ""),
                REGIONS[reg] + " constant 2025 prices",
            ]
        )

Y = max(y for (reg, y, _, _) in rows if reg == "CA")
pcts = sorted({(lo, hi) for (reg, y, lo, hi) in rows if y == Y})
with open(os.path.join(OUT, f"wealth_lookup_{Y}.csv"), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(
        [
            "p_lower",
            "p_upper",
            "canada_threshold_cad",
            "canada_bracket_avg_cad",
            "world_threshold_usd_mer",
            "world_bracket_avg_usd_mer",
            "world_threshold_usd_ppp",
            "world_bracket_avg_usd_ppp",
        ]
    )
    for lo, hi in pcts:
        out = [f"{lo:g}", f"{hi:g}"]
        for reg in REGIONS:
            d = rows.get((reg, Y, lo, hi), {})
            out += [d.get("thwealj992", ""), d.get("ahwealj992", "")]
        w.writerow(out)

with open(os.path.join(OUT, "reference_rates_population.csv"), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["region", "year", "variable", "value", "meaning"])
    mean = {
        "xlcusxi999": "market exchange rate, LCU per USD",
        "xlcuspi999": "PPP factor, LCU per USD",
        "inyixxi999": "price index (2025=1)",
        "npopuli992": "adult (20+) population",
    }
    for k in sorted(ref):
        if k[1] >= 1995:
            w.writerow([k[0], k[1], k[2], ref[k], mean[k[2]]])
print("latest year:", Y, "rows:", len(rows))
