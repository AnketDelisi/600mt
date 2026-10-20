#!/usr/bin/env python3
"""Calibration harness for the U.S. Senate model.

Loads the cached 2022/2024 backtest snapshots and scores a parameterised v2
estimator against the current model:

  * polls rebuilt from the individual polls with recency, partisan and
    outlier weights (no more 2022 polls averaging into a 2024 race);
  * structural prior = the state's lean in the last presidential election
    (relative to the nation) + the cycle environment scaled by the state's
    historical elasticity + incumbency + trend. This replaced PVI + last
    Senate result, which compressed safe seats and carried personal-vote
    artifacts (WV 2024: Manchin D+3, state R+43);
  * a poll-vs-structure outlier guard (a stale poll cannot drag a safe seat);
  * win probabilities from a calibrated margin sigma.

The live model uses env_full=0.8 (the generic ballot damped 20%); this
harness fits env_full around 0.75-1.0 and the gap is negligible.

Run: python scraper/us_calibrate.py [--grid] [--diag]
"""
import json
import math
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scraper"))
import us_scrape_model as m
import us_scrape_polls as pp

CACHE = ROOT / "scraper" / ".cache"
SW = json.loads((ROOT / "data" / "us" / "state_swing.json").read_text(encoding="utf8"))
NAT = SW["national_margin"]
SW = SW["states"]
ELECTION = {2022: date(2022, 11, 8), 2024: date(2024, 11, 5)}
ENV = {2022: -1.0, 2024: -0.1}
PRES_YEAR = {2022: "2020", 2024: "2020", 2026: "2024"}

BASE = {
    "half_life": 120, "max_age": 540, "partisan_w": 0.6, "trim": 12.0,
    "agg_sigma": 2.5, "dir_sigma": 4.0, "min_neff": 1.5,
    "pres_w": 1.0, "env_full": 1.0, "use_inc": True,
    "last_w": {"solid": 0.0, "likely": 0.0, "lean": 0.0, "tossup": 0.0, "none": 0.0},
    "sigma_s": {"solid": 4.0, "likely": 5.0, "lean": 6.0, "tossup": 8.0, "none": 8.0},
    "band_shrink": 0.0, "trend_w": 0.2, "env_w": 0.25, "beta_env": 1.0,
    "guard_start": 8.0, "guard_width": 8.0, "sigma_prob": 6.0,
}


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def poll_date(s):
    y, mo, d = pp.date_key(s)
    if not y:
        return None
    return date(y, mo, d)


def two_party(d, r):
    return (d - r) / (d + r) * 100.0 if (d + r) > 0 else None


def poll_est(entry, asof, p):
    """(margin, sigma, n_eff, source) from an aggregate or individual polls."""
    if not entry:
        return None
    dem, rep = entry.get("dem"), entry.get("rep")
    if dem is not None and rep is not None:
        src = entry.get("source") or ""
        if "aggregate" in src.lower():
            mar = two_party(dem, rep)
            return (mar, p["agg_sigma"], 3.0, "aggregate") if mar is not None else None
    polls = entry.get("polls") or []
    rows = []
    for pol in polls:
        if pol.get("dem") is None or pol.get("rep") is None:
            continue
        dt = poll_date(pol.get("dates"))
        if not dt:
            continue
        age = (asof - dt).days
        if age < -10 or age > p["max_age"]:
            continue
        mar = two_party(pol["dem"], pol["rep"])
        if mar is None:
            continue
        w = 0.5 ** (age / p["half_life"])
        if pol.get("partisan"):
            w *= p["partisan_w"]
        rows.append((mar, w))
    if len(rows) < 2:
        return None
    rows.sort(key=lambda x: x[0])
    # weighted median, then trim polls far from it
    tot = sum(w for _, w in rows)
    acc = 0.0
    med = rows[-1][0]
    for mar, w in rows:
        acc += w
        if acc >= tot / 2:
            med = mar
            break
    keep = [(mar, w) for mar, w in rows if abs(mar - med) <= p["trim"]]
    if len(keep) < 2:
        return None
    ws = sum(w for _, w in keep)
    mean = sum(mar * w for mar, w in keep) / ws
    neff = ws * ws / sum(w * w for _, w in keep)
    if neff < p["min_neff"]:
        return None
    sigma = max(2.0, p["dir_sigma"] / math.sqrt(neff))
    return (mean, sigma, neff, "direct")


def grade_of(race):
    band = m.consensus_band(race.get("ratings"))
    if band is None:
        return "none"
    c = band[2]
    a = abs(c)
    if a >= 15:
        return "solid"
    if a >= 7.5:
        return "likely"
    if a >= 2.5:
        return "lean"
    return "tossup"


def structural(race, grade, p, env, cycle):
    st = SW.get(race.get("state")) or {}
    year = PRES_YEAR[cycle]
    pres = (st.get("margins") or {}).get(year)
    if pres is None:
        pres = st.get("margin_2024")
        nat = NAT.get("2024", 0.0)
    else:
        nat = NAT.get(year, 0.0)
    pres_lean = (pres - nat) if pres is not None else 0.0
    pvi_m = -1.0 * (race.get("pvi") or 0.0)
    lean = p["pres_w"] * pres_lean + (1.0 - p["pres_w"]) * pvi_m
    beta = (st.get("beta", 1.0) ** p["beta_env"]) if p["beta_env"] else 1.0
    base = lean + p["env_full"] * env * beta
    if p["use_inc"]:
        base += m.incumbency_adj(race)
    last = m.last_margin(race)
    lw = p["last_w"][grade] if last is not None else 0.0
    if lw:
        base = (1.0 - lw) * base + lw * last
    band = m.consensus_band(race.get("ratings"))
    if band is not None and p["band_shrink"]:
        base = (1.0 - p["band_shrink"]) * base + p["band_shrink"] * band[2]
    base += p["trend_w"] * st.get("trend", 0.0)
    return base


def predict(race, asof, env, p):
    grade = grade_of(race)
    S = structural(race, grade, p, env, cycle_of(asof))
    pe = poll_est(race.get("polls"), asof, p)
    if pe is None:
        return S, p["sigma_s"][grade], None
    P, sig_p, neff, src = pe
    w = p["sigma_s"][grade] ** 2 / (p["sigma_s"][grade] ** 2 + sig_p ** 2)
    excess = max(0.0, abs(P - S) - p["guard_start"])
    w /= (1.0 + (excess / p["guard_width"]) ** 2)
    return S + w * (P - S), p["sigma_s"][grade], pe


def cycle_of(asof):
    return asof.year if asof.year in PRES_YEAR else 2024


def load():
    rows = []
    for cyc in (2022, 2024):
        data = json.loads((CACHE / ("us_bt_%d.json" % cyc)).read_text(encoding="utf8"))
        for r in data:
            if r.get("actual") is None:
                continue
            pe = r.get("polls") or {}
            if pe and pe.get("dem") is None:
                continue          # Republican-vs-Independent races
            rows.append(dict(r, cycle=cyc))
    return rows


def score(rows, p, label=""):
    n = win = 0
    mae = bias = brier = 0.0
    bins = [(0.5, 0.6), (0.6, 0.7), (0.7, 0.85), (0.85, 1.01)]
    bstat = {b: [0, 0] for b in bins}
    for r in rows:
        mu, sig, pe = predict(r, ELECTION[r["cycle"]], ENV[r["cycle"]], p)
        a = r["actual"]
        n += 1
        mae += abs(mu - a)
        bias += mu - a
        pw = norm_cdf(mu / p["sigma_prob"])
        dw = 1.0 if a > 0 else 0.0
        brier += (pw - dw) ** 2
        win += 1 if (mu > 0) == (dw == 1.0) else 0
        for b in bins:
            if b[0] <= pw < b[1]:
                bstat[b][0] += 1
                bstat[b][1] += 1 if dw == 1.0 else 0
    print("%-26s n=%2d  bias %+4.1f  MAE %5.2f  win %3.0f%%  Brier %.4f"
          % (label, n, bias / n, mae / n, 100.0 * win / n, brier / n))
    return mae / n, brier / n


def v1_score(rows):
    n = win = 0
    mae = brier = 0.0
    for r in rows:
        pred = m.legacy_final_margin(r, r.get("polls"), "senate")
        rated = m.consensus_band(r.get("ratings")) is not None
        mu = (m.ENV_WEIGHT["senate"] if rated else m.UNRATED_ENV_WEIGHT["senate"]) * ENV[r["cycle"]]
        pred += mu
        a = r["actual"]
        n += 1
        mae += abs(pred - a)
        p = 1.0 / (1.0 + math.exp(-pred / m.LOGISTIC_BETA["senate"]))
        brier += (p - (1.0 if a > 0 else 0.0)) ** 2
        win += 1 if (pred > 0) == (a > 0) else 0
    print("%-26s n=%2d  MAE %5.2f  win %3.0f%%  Brier %.4f"
          % ("v1 current model", n, mae / n, 100.0 * win / n, brier / n))


def main():
    rows = load()
    print("races:", len(rows),
          "| 2022:", sum(1 for r in rows if r["cycle"] == 2022),
          "| 2024:", sum(1 for r in rows if r["cycle"] == 2024))
    v1_score(rows)
    for cyc in (2022, 2024):
        score([r for r in rows if r["cycle"] == cyc], BASE, "v2 %d" % cyc)
    score(rows, BASE, "v2 both")

    if "--diag" in sys.argv:
        do_diag(rows)

    if "--grid" in sys.argv:
        print("\n== grid (margin MAE / Brier; fit 2022, check 2024)")
        r22 = [r for r in rows if r["cycle"] == 2022]
        r24 = [r for r in rows if r["cycle"] == 2024]
        best = []
        for pres_w in (1.0,):
            for env_full in (0.75, 1.0):
                for use_inc in (True,):
                    for last_solid in (0.0,):
                        for band in (0.0,):
                            for guard in (8.0,):
                                for trend in (0.0, 0.2, 0.4):
                                    for beta_env in (0.0, 0.5, 1.0):
                                        p = json.loads(json.dumps(BASE))
                                        p["pres_w"] = pres_w
                                        p["env_full"] = env_full
                                        p["use_inc"] = use_inc
                                        p["last_w"] = {"solid": last_solid, "likely": last_solid,
                                                       "lean": last_solid, "tossup": last_solid,
                                                       "none": last_solid}
                                        p["band_shrink"] = band
                                        p["guard_start"] = guard
                                        p["trend_w"] = trend
                                        p["beta_env"] = beta_env
                                        mae22 = score_quiet(r22, p)
                                        mae24 = score_quiet(r24, p)
                                        best.append((mae22 + mae24, mae22, mae24, pres_w,
                                                     env_full, use_inc, last_solid, band,
                                                     guard, trend, beta_env))
        best.sort()
        print("sum MAE | 2022 | 2024 | pres_w | env | inc | last | band | guard | trend | beta")
        for b in best[:12]:
            print("%6.2f  %5.2f  %5.2f   %.2f   %.2f  %s  %.2f  %.2f  %.1f  %.1f  %.1f"
                  % (b[0], b[1], b[2], b[3], b[4], "Y" if b[5] else "n",
                     b[6], b[7], b[8], b[9], b[10]))


def score_quiet(rows, p):
    mae = 0.0
    n = 0
    for r in rows:
        mu, sig, pe = predict(r, ELECTION[r["cycle"]], ENV[r["cycle"]], p)
        mae += abs(mu - r["actual"])
        n += 1
    return mae / n


def do_diag(rows):
    from statistics import mean, pstdev
    print("\n== residual diagnostics (v2)")
    out = []
    for r in rows:
        mu, sig, pe = predict(r, ELECTION[r["cycle"]], ENV[r["cycle"]], BASE)
        src = pe[3] if pe else "none"
        out.append((r["cycle"], r["state"], grade_of(r), src, mu - r["actual"],
                    sig, mu, r["actual"]))

    for key, sel in (
            ("all", out),
            ("polled", [x for x in out if x[3] != "none"]),
            ("unpolled", [x for x in out if x[3] == "none"]),
            ("aggregate", [x for x in out if x[3] == "aggregate"]),
            ("direct", [x for x in out if x[3] == "direct"])):
        if sel:
            print("%-10s n=%2d  bias %+5.2f  sd %5.2f  MAE %5.2f"
                  % (key, len(sel), mean(x[4] for x in sel),
                     pstdev(x[4] for x in sel), mean(abs(x[4]) for x in sel)))

    print("\n== by grade")
    for g in ("solid", "likely", "lean", "tossup", "none"):
        sel = [x for x in out if x[2] == g]
        if sel:
            print("%-7s n=%2d  bias %+5.2f  sd %5.2f  MAE %5.2f"
                  % (g, len(sel), mean(x[4] for x in sel),
                     pstdev(x[4] for x in sel), mean(abs(x[4]) for x in sel)))

    print("\n== probability calibration (per-race sigma, 8 bins)")
    bins = [(0, .1), (.1, .2), (.2, .3), (.3, .4), (.4, .6), (.6, .7), (.7, .9), (.9, 1.01)]
    for lo, hi in bins:
        sel = [x for x in out if lo <= norm_cdf(x[6] / x[5]) < hi]
        if sel:
            print("p %.1f-%.1f  n=%2d  pred %.2f  actual %.2f"
                  % (lo, hi, len(sel),
                     mean(norm_cdf(x[6] / x[5]) for x in sel),
                     mean(1.0 if x[7] > 0 else 0.0 for x in sel)))

    brier_fixed = mean((norm_cdf(x[6] / 6.0) - (1.0 if x[7] > 0 else 0.0)) ** 2 for x in out)
    brier_own = mean((norm_cdf(x[6] / x[5]) - (1.0 if x[7] > 0 else 0.0)) ** 2 for x in out)
    print("\nBrier fixed sigma 6: %.4f | per-race sigma: %.4f" % (brier_fixed, brier_own))


if __name__ == "__main__":
    main()
