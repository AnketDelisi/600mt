#!/usr/bin/env python3
"""Seat-count holdout report.

2018-2022 are the fit cycles; 2024 is reported separately as the holdout.
Run: python scraper/us_seat_report.py
"""
import json
import math
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scraper"))
import us_calibrate as sc
import us_scrape_model as m

CACHE = ROOT / "scraper" / ".cache"
ELECTION = {2018: date(2018, 11, 6), 2020: date(2020, 11, 3),
            2022: date(2022, 11, 8), 2024: date(2024, 11, 5)}
HOUSE_FULL = {2018: 235, 2020: 222, 2022: 213, 2024: 215}


def win_prob(margin, chamber):
    return 1.0 / (1.0 + math.exp(-margin / m.LOGISTIC_BETA[chamber]))


def house():
    print("HOUSE  expected D seats (all 435) vs actual full")
    for cyc in (2018, 2020, 2022, 2024):
        data = json.loads((CACHE / ("us_house_bt_%d.json" % cyc)).read_text())
        exp = sum(win_prob(m.final_margin(
            r, r.get("polls"), "house", r.get("env") or 0.0, ELECTION[cyc]),
            "house") for r in data)
        print("%d expected %5.1f actual %3d error %+5.1f%s"
              % (cyc, exp, HOUSE_FULL[cyc], exp - HOUSE_FULL[cyc],
                 "  HOLDOUT" if cyc == 2024 else ""))


def governor():
    print("\nGOVERNOR  expected D (scored races) vs actual D")
    for cyc in (2018, 2020, 2022, 2024):
        data = json.loads((CACHE / ("us_gov_bt_%d.json" % cyc)).read_text())
        exp = act = 0.0
        for r in data:
            if r.get("actual") is None:
                continue
            mu = m.final_margin(r, r.get("polls"), "governor",
                                r.get("env") or 0.0, ELECTION[cyc])
            exp += win_prob(mu, "governor")
            act += 1.0 if r["actual"] > 0 else 0.0
        print("%d expected %5.1f actual %3.0f error %+5.1f%s"
              % (cyc, exp, act, exp - act, "  HOLDOUT" if cyc == 2024 else ""))


def senate():
    print("\nSENATE  expected D (scored up races) vs actual D")
    for cyc in (2018, 2020, 2022, 2024):
        rows = [r for r in sc.load() if r["cycle"] == cyc]
        exp = act = 0.0
        for r in rows:
            mu = m.final_margin(r, r.get("polls"), "senate", sc.ENV[cyc],
                                sc.ELECTION[cyc], lean_year=sc.PRES_YEAR[cyc])
            exp += win_prob(mu, "senate")
            act += 1.0 if r["actual"] > 0 else 0.0
        print("%d expected %5.1f actual %3.0f error %+5.1f%s"
              % (cyc, exp, act, exp - act, "  HOLDOUT" if cyc == 2024 else ""))


def main():
    print("2024 is the holdout; 2018-2022 are the fit cycles\n")
    house()
    governor()
    senate()


if __name__ == "__main__":
    main()
