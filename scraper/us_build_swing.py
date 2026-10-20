#!/usr/bin/env python3
"""Build data/us/state_swing.json — the historical swing structure used by
the model's national-environment layer.

Sources: the county-level presidential results 2008-2024 in
github.com/tonmcg/US_County_Level_Election_Results_08-24 (aggregated to the
50 states). For every state:
  * elasticity beta: response of the state's two-party margin to a one-point
    national swing (OLS over the four 4-year intervals, shrunk halfway to 1);
  * trend: the state's relative drift over the last two cycles (mean residual
    of the elastic swing, i.e. how much the state has been moving against the
    nation beyond what its elasticity explains);
  * idio sigma: residual swing volatility (shrunk toward the pooled value);
  * region: the Census region for the correlated regional shock.
Plus the national two-party margins and the pooled region/idio variances.

Usage: python scraper/us_build_swing.py
"""
import csv
import io
import json
import math
import statistics
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "us" / "state_swing.json"
CACHE = ROOT / "scraper" / ".cache" / "us_swing"
BASE = ("https://raw.githubusercontent.com/tonmcg/"
        "US_County_Level_Election_Results_08-24/master/")
FILES = [
    ("US_County_Level_Presidential_Results_08-16.csv", "fips"),
    ("2020_US_County_Level_Presidential_Results.csv", "name"),
    ("2024_US_County_Level_Presidential_Results.csv", "name"),
]
YEARS = [2008, 2012, 2016, 2020, 2024]
FIPS = {
    "01": "Alabama", "02": "Alaska", "04": "Arizona", "05": "Arkansas",
    "06": "California", "08": "Colorado", "09": "Connecticut", "10": "Delaware",
    "12": "Florida", "13": "Georgia", "15": "Hawaii", "16": "Idaho",
    "17": "Illinois", "18": "Indiana", "19": "Iowa", "20": "Kansas",
    "21": "Kentucky", "22": "Louisiana", "23": "Maine", "24": "Maryland",
    "25": "Massachusetts", "26": "Michigan", "27": "Minnesota",
    "28": "Mississippi", "29": "Missouri", "30": "Montana", "31": "Nebraska",
    "32": "Nevada", "33": "New Hampshire", "34": "New Jersey",
    "35": "New Mexico", "36": "New York", "37": "North Carolina",
    "38": "North Dakota", "39": "Ohio", "40": "Oklahoma", "41": "Oregon",
    "42": "Pennsylvania", "44": "Rhode Island", "45": "South Carolina",
    "46": "South Dakota", "47": "Tennessee", "48": "Texas", "49": "Utah",
    "50": "Vermont", "51": "Virginia", "53": "Washington",
    "54": "West Virginia", "55": "Wisconsin", "56": "Wyoming",
}
REGIONS = {
    "Northeast": ["Connecticut", "Maine", "Massachusetts", "New Hampshire",
                  "Rhode Island", "Vermont", "New Jersey", "New York",
                  "Pennsylvania"],
    "Midwest": ["Illinois", "Indiana", "Michigan", "Ohio", "Wisconsin",
                "Iowa", "Kansas", "Minnesota", "Missouri", "Nebraska",
                "North Dakota", "South Dakota"],
    "South": ["Delaware", "Florida", "Georgia", "Maryland", "North Carolina",
              "South Carolina", "Virginia", "West Virginia", "Alabama",
              "Kentucky", "Mississippi", "Tennessee", "Arkansas", "Louisiana",
              "Oklahoma", "Texas"],
    "West": ["Arizona", "Colorado", "Idaho", "Montana", "Nevada", "New Mexico",
             "Utah", "Wyoming", "Alaska", "California", "Hawaii", "Oregon",
             "Washington"],
}


def fetch(name):
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / name
    if not path.is_file():
        req = urllib.request.Request(BASE + name, headers={"User-Agent": "600mt/1.0"})
        path.write_bytes(urllib.request.urlopen(req, timeout=120).read())
    return path.read_text(encoding="utf-8-sig")


def main():
    # votes[state][year] = [dem, gop]
    votes = {}
    for name, kind in FILES:
        rows = csv.DictReader(io.StringIO(fetch(name)))
        for row in rows:
            if kind == "fips":
                st = FIPS.get((row.get("fips_code") or "")[:2])
                if not st:
                    continue
                for year in (2008, 2012, 2016):
                    d = float(row.get("dem_%d" % year) or 0)
                    r = float(row.get("gop_%d" % year) or 0)
                    acc = votes.setdefault(st, {}).setdefault(year, [0.0, 0.0])
                    acc[0] += d
                    acc[1] += r
            else:
                st = (row.get("state_name") or "").strip()
                if st not in FIPS_VALUES:
                    continue
                d = float(row.get("votes_dem") or 0)
                r = float(row.get("votes_gop") or 0)
                year = 2020 if "2020" in name else 2024
                acc = votes.setdefault(st, {}).setdefault(year, [0.0, 0.0])
                acc[0] += d
                acc[1] += r
    states = sorted(votes)
    # the 2008-2016 county file carries no Alaska rows; its official totals
    # (Obama/McCain 2008, Obama/Romney 2012, Clinton/Trump 2016)
    AK = {2008: (123594, 193841), 2012: (122640, 164676),
          2016: (116454, 163387)}
    for year, (d, r) in AK.items():
        votes.setdefault("Alaska", {}).setdefault(year, [float(d), float(r)])
    missing = [s for s in states if any(y not in votes[s] for y in YEARS)]
    assert not missing, "missing years for %s" % missing

    def margin(d, r):
        return (d - r) / (d + r) * 100.0 if (d + r) else 0.0

    nat = {}
    for y in YEARS:
        td = sum(votes[s][y][0] for s in states)
        tr = sum(votes[s][y][1] for s in states)
        nat[y] = margin(td, tr)
    dm_nat = [nat[YEARS[i]] - nat[YEARS[i - 1]] for i in range(1, len(YEARS))]
    dn2 = sum(x * x for x in dm_nat)

    state_out = {}
    residuals = {}
    for s in states:
        ms = {y: margin(*votes[s][y]) for y in YEARS}
        dm = [ms[YEARS[i]] - ms[YEARS[i - 1]] for i in range(1, len(YEARS))]
        beta_raw = sum(a * b for a, b in zip(dm, dm_nat)) / dn2
        beta = 1.0 + 0.5 * (beta_raw - 1.0)          # shrink halfway to 1
        res = [a - beta_raw * b for a, b in zip(dm, dm_nat)]
        residuals[s] = res
        state_out[s] = {
            "margins": {str(y): round(ms[y], 2) for y in YEARS},
            "margin_2008": round(ms[2008], 2),
            "margin_2024": round(ms[2024], 2),
            "beta_raw": round(beta_raw, 3),
            "beta": round(beta, 3),
            "trend": round(statistics.mean(res[-2:]), 2),
            "region": next(r for r, lst in REGIONS.items() if s in lst),
        }

    # pooled region/idio variance: residual = region factor + idio
    region_series = {r: [] for r in REGIONS}
    for s, res in residuals.items():
        region_series[state_out[s]["region"]].append(res)
    region_factor = {}
    for r, series in region_series.items():
        if series:
            region_factor[r] = [statistics.mean(col) for col in zip(*series)]
    all_rf = [v for series in region_factor.values() for v in series]
    sigma_region = statistics.pstdev(all_rf) if len(all_rf) > 2 else 1.0
    idio = []
    for s, res in residuals.items():
        rf = region_factor.get(state_out[s]["region"], [0] * len(res))
        idio.extend(a - b for a, b in zip(res, rf))
    sigma_idio = statistics.pstdev(idio) if len(idio) > 2 else 2.0
    # per-state idio, shrunk toward the pooled value (4 intervals are noisy)
    for s, res in residuals.items():
        rf = region_factor.get(state_out[s]["region"], [0] * len(res))
        rr = [a - b for a, b in zip(res, rf)]
        raw = statistics.pstdev(rr) if len(rr) > 2 else sigma_idio
        state_out[s]["sigma_idio"] = round(
            math.sqrt((3 * raw * raw + 8 * sigma_idio ** 2) / 11.0), 2)

    out = {
        "source": "Presidential county results 2008-2024 (tonmcg/"
                  "US_County_Level_Election_Results_08-24), aggregated to states",
        "years": YEARS,
        "national_margin": {str(y): round(nat[y], 2) for y in YEARS},
        "national_deltas": [round(x, 2) for x in dm_nat],
        "region_sigma": round(sigma_region, 2),
        "idio_sigma": round(sigma_idio, 2),
        "beta_shrink": 0.5,
        "states": state_out,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print("wrote", OUT)
    print("national margins:", out["national_margin"])
    print("region sigma %.2f | idio sigma %.2f" % (sigma_region, sigma_idio))
    betas = sorted((v["beta"], s) for s, v in state_out.items())
    print("least elastic:", betas[:5])
    print("most elastic:", betas[-5:])
    trends = sorted((v["trend"], s) for s, v in state_out.items())
    print("trend D:", trends[-5:])
    print("trend R:", trends[:5])


FIPS_VALUES = set(FIPS.values())

if __name__ == "__main__":
    main()
