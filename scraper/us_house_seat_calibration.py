#!/usr/bin/env python3
"""Historical House seat-distribution diagnostic.

Replays the 2018-2024 House races with the current national/regional/state
uncertainty model and compares the simulated seat distribution with the
actual full-chamber result. This is a calibration diagnostic, not a forecast.

Run: python scraper/us_house_seat_calibration.py [--sims 20000]
"""
import json
import math
import random
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scraper"))
import us_scrape_model as m

CACHE = ROOT / "scraper" / ".cache"
ELECTION = {2018: date(2018, 11, 6), 2020: date(2020, 11, 3),
            2022: date(2022, 11, 8), 2024: date(2024, 11, 5)}
ACTUAL_D = {2018: 235, 2020: 222, 2022: 213, 2024: 215}
N_SIMS = 20000


def build_cycle(cycle):
    rows = json.loads((CACHE / ("us_house_bt_%d.json" % cycle)).read_text())
    races = []
    for row in rows:
        mu = m.final_margin(row, row.get("polls"), "house",
                            row.get("env") or 0.0, ELECTION[cycle])
        state = row["state"].replace("_", " ")
        races.append((mu, state))
    return races


def simulate(races, sims):
    out = []
    for _ in range(sims):
        z = random.gauss(0.0, m.NATIONAL_SIGMA)
        zb = random.gauss(0.0, m.POLL_BIAS_SIGMA)
        regions = {}
        states = {}
        seats = 0
        for mu, state in races:
            if state not in states:
                region = (m.STATE_SWING.get(state) or {}).get("region") or ""
                if region not in regions:
                    regions[region] = random.gauss(0.0, m.REGION_SIGMA)
                states[state] = regions[region] + random.gauss(0.0, m.STATE_SIGMA)
            swing = z + zb + states[state]
            p = 1.0 / (1.0 + math.exp(-(mu + swing) / m.LOGISTIC_BETA["house"]))
            seats += 1 if random.random() < p else 0
        out.append(seats)
    out.sort()
    return out


def main():
    sims = N_SIMS
    if "--sims" in sys.argv:
        sims = int(sys.argv[sys.argv.index("--sims") + 1])
    if "--poll-bias" in sys.argv:
        m.POLL_BIAS_SIGMA = float(
            sys.argv[sys.argv.index("--poll-bias") + 1])
    print("House seat distribution | sims %d | national %.1f region %.1f state %.1f"
          % (sims, m.NATIONAL_SIGMA, m.REGION_SIGMA, m.STATE_SIGMA))
    for cycle in (2018, 2020, 2022, 2024):
        races = build_cycle(cycle)
        seats = simulate(races, sims)
        actual = ACTUAL_D[cycle]
        expected = sum(seats) / len(seats)
        p5 = seats[int(0.05 * len(seats))]
        p50 = seats[int(0.50 * len(seats))]
        p95 = seats[int(0.95 * len(seats))]
        p_majority = sum(1 for x in seats if x >= 218) / len(seats)
        pct = sum(1 for x in seats if x < actual) / len(seats)
        print("%d expected %5.1f  actual %3d  err %+5.1f  90%% [%d, %d]  "
              "P(D maj) %4.1f%%  actual pct %4.1f%%"
              % (cycle, expected, actual, expected - actual, p5, p95,
                 100 * p_majority, 100 * pct))


if __name__ == "__main__":
    main()
