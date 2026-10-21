#!/usr/bin/env python3
"""Governor calibration harness: current PVI/last/band model vs a state
presidential-lean prior, on the cached 2022/2024 races.

Run: python scraper/us_calibrate_governor.py [--grid]
"""
import json
import math
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scraper"))
import us_scrape_model as m

CACHE = ROOT / "scraper" / ".cache"
ELECTION = {2018: date(2018, 11, 6), 2020: date(2020, 11, 3),
            2022: date(2022, 11, 8), 2024: date(2024, 11, 5)}
BASE = {"pres_w": 0.0, "env_w": 0.25, "last_w": 0.7, "open_w": 0.4,
        "band": 1, "inc": 1}


def load():
    rows = []
    for cyc in (2018, 2020, 2022, 2024):
        path = CACHE / ("us_gov_bt_%d.json" % cyc)
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf8"))
        for r in data:
            if r.get("actual") is None:
                continue
            rows.append(dict(r, cycle=cyc))
    return rows


def margin(r, p, asof):
    pvi = m.pvi_margin(r.get("pvi") or 0.0)
    pres = r.get("state_pres")
    lean = (p["pres_w"] * pres + (1.0 - p["pres_w"]) * pvi
            if pres is not None else pvi)
    polls = r.get("polls")
    if p["inc"] and not polls:
        lean += m.incumbency_adj(r)
    last = m.last_margin(r)
    if last is not None and p["last_w"]:
        lw = p["open_w"] if m.is_open_seat(r) else p["last_w"]
        lean = (1.0 - lw) * lean + lw * last
    band = m.consensus_band(r.get("ratings"))
    if band is not None and p["band"]:
        lo, hi, _ = band
        lean = max(lo, min(hi, lean))
    env_w = p["env_w"] if band is not None else 1.0
    lean += env_w * (r.get("env") or 0.0)
    if polls:
        lean = m.blend_poll(lean, polls, asof, m.grade_of(r))
    return lean


def score(rows, p, label=""):
    n = win = 0
    mae = brier = 0.0
    for r in rows:
        mu = margin(r, p, ELECTION[r["cycle"]])
        a = r["actual"]
        n += 1
        mae += abs(mu - a)
        pw = 1.0 / (1.0 + math.exp(-mu / m.LOGISTIC_BETA["governor"]))
        brier += (pw - (1.0 if a > 0 else 0.0)) ** 2
        win += 1 if (mu > 0) == (a > 0) else 0
    print("%-34s n=%2d  MAE %5.2f  win %3.0f%%  Brier %.4f"
          % (label, n, mae / n, 100.0 * win / n, brier / n))
    return mae / n, brier / n


def score_quiet(rows, p):
    return score(rows, p, "tmp")[0]


def main():
    rows = load()
    print("races:", len(rows), "| " + " | ".join(
        "%d: %d" % (c, sum(1 for r in rows if r["cycle"] == c))
        for c in (2018, 2020, 2022, 2024)))
    n = win = 0
    mae = brier = 0.0
    for r in rows:
        mu = m.final_margin(r, r.get("polls"), "governor", r.get("env") or 0.0,
                            ELECTION[r["cycle"]])
        a = r["actual"]
        n += 1
        mae += abs(mu - a)
        pw = 1.0 / (1.0 + math.exp(-mu / m.LOGISTIC_BETA["governor"]))
        brier += (pw - (1.0 if a > 0 else 0.0)) ** 2
        win += 1 if (mu > 0) == (a > 0) else 0
    print("%-34s n=%2d  MAE %5.2f  win %3.0f%%  Brier %.4f"
          % ("live governor model", n, mae / n, 100.0 * win / n, brier / n))
    for cyc in (2018, 2020, 2022, 2024):
        sel = [r for r in rows if r["cycle"] == cyc]
        if not sel:
            continue
        score(sel, BASE, "param baseline %d" % cyc)
        score(sel, dict(BASE, pres_w=0.5), "half state pres %d" % cyc)
        score(sel, dict(BASE, pres_w=1.0), "state pres only %d" % cyc)
        score(sel, dict(BASE, pres_w=1.0, last_w=0.0),
              "state pres, band, inc %d" % cyc)
        score(sel, dict(BASE, pres_w=0.5, last_w=0.4), "half pres, last .4 %d" % cyc)

    if "--grid" in sys.argv:
        fit = [r for r in rows if r["cycle"] in (2018, 2020, 2022)]
        check = [r for r in rows if r["cycle"] == 2024]
        best = []
        for pres_w in (0.0, 0.25, 0.5, 1.0):
            for env_w in (0.25, 1.0):
                for last_w in (0.0, 0.4, 0.7):
                    for band in (0, 1):
                        for inc in (0, 1):
                            p = dict(BASE, pres_w=pres_w, env_w=env_w,
                                     last_w=last_w, open_w=min(0.4, last_w),
                                     band=band, inc=inc)
                            mae_fit = score_quiet(fit, p)
                            mae_check = score_quiet(check, p)
                            best.append((mae_fit + mae_check, mae_fit, mae_check,
                                         pres_w, env_w, last_w, band, inc))
        best.sort()
        print("\nsum MAE | fit | 2024 | pres_w | env | last | band | inc")
        for b in best[:15]:
            print("%6.2f  %5.2f  %5.2f   %.2f   %.2f  %.2f   %d   %d"
                  % (b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7]))


if __name__ == "__main__":
    main()
