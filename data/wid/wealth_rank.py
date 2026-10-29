"""Local (Canada) and global wealth rank for one adult's net worth.

Usage:  python wealth_rank.py 500000          (net worth in CAD)
Data:   wealth_lookup_2024.csv + reference_rates_population.csv (from WID, extracted by build_extract.py)
Concept: WID net personal wealth, adults 20+, equal-split between spouses, constant 2025 prices.
"""
import csv, os, sys
D = os.path.dirname(os.path.abspath(__file__))
YEAR = 2024
REF = {(r["region"], int(r["year"]), r["variable"]): float(r["value"])
       for r in csv.DictReader(open(os.path.join(D, "reference_rates_population.csv")))}
CAD_PER_USD_MER = REF[("CA", 2025, "xlcusxi999")]   # 2025 rates: matches constant-2025-price units
CAD_PER_USD_PPP = REF[("CA", 2025, "xlcuspi999")]
ADULTS = {"canada": REF[("CA", YEAR, "npopuli992")], "world": REF[("WO-MER", YEAR, "npopuli992")]}

def _table(tcol, acol):
    rows = list(csv.DictReader(open(os.path.join(D, f"wealth_lookup_{YEAR}.csv"))))
    return [(float(r["p_lower"]), float(r["p_upper"]), float(r[tcol]), float(r[acol])) for r in rows]
TABLES = {"canada": _table("canada_threshold_cad", "canada_bracket_avg_cad"),
          "world_mer": _table("world_threshold_usd_mer", "world_bracket_avg_usd_mer"),
          "world_ppp": _table("world_threshold_usd_ppp", "world_bracket_avg_usd_ppp")}

def percentile(w, tab):
    """Share of adults (in %) with net worth below w."""
    if w < tab[0][2]:
        return 0.0
    for i in range(len(tab) - 1):
        lo, hi, t, _ = tab[i]
        t_next = tab[i + 1][2]
        if t <= w < t_next:
            return lo + (hi - lo) * (w - t) / (t_next - t)
    lo, hi, t, a = tab[-1]                      # top 0.001%: Pareto tail fitted to bracket average
    alpha = a / (a - t)
    return 100 - (100 - lo) * (w / t) ** (-alpha)

def rank(net_worth_cad):
    res = {}
    for key, val in (("canada", net_worth_cad),
                     ("world_mer", net_worth_cad / CAD_PER_USD_MER),
                     ("world_ppp", net_worth_cad / CAD_PER_USD_PPP)):
        p = percentile(val, TABLES[key])
        pop = ADULTS["canada" if key == "canada" else "world"]
        res[key] = {"value_compared": round(val), "percentile": p, "top_pct": 100 - p,
                    "approx_rank": max(1, round((100 - p) / 100 * pop)), "adults": int(pop)}
    return res

if __name__ == "__main__":
    nw = float(sys.argv[1].replace(",", "")) if len(sys.argv) > 1 else float(input("Net worth (CAD): "))
    labels = {"canada": "Canada (CAD)", "world_mer": "World, market FX (USD)", "world_ppp": "World, PPP (USD)"}
    for k, r in rank(nw).items():
        print(f"{labels[k]:<24} compared={r['value_compared']:>15,}  percentile={r['percentile']:8.4f}  "
              f"top {r['top_pct']:.4f}%  rank ~{r['approx_rank']:,} of {r['adults']:,} adults")
