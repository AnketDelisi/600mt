#!/usr/bin/env python3
"""Historical Governor seat-distribution diagnostic.

Replays the 2018-2024 governor up-races with the current national/regional/
state uncertainty model, adds the fixed governorships not up in that cycle,
and compares the full D distribution with the actual result.

Run: python scraper/us_governor_seat_calibration.py [--sims 20000]
"""
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scraper"))
import us_scrape_model as m
import us_calibrate_governor as g

ACTUAL_FULL_D = {2018: 23, 2020: 23, 2022: 24, 2024: 23}
N_SIMS = 20000


def build_cycle(cycle):
    rows = [r for r in g.load()
            if r["cycle"] == cycle and r.get("actual") is not None]
    races = []
    actual_up = 0
    for row in rows:
        mu = m.final_margin(row, row.get("polls"), "governor",
                            row.get("env") or 0.0, g.ELECTION[cycle])
        state = row["state"].replace("_", " ")
        races.append((mu, state))
        actual_up += 1 if row["actual"] > 0 else 0
    return races, actual_up


def simulate(races, not_up_d, sims):
    out = []
    for _ in range(sims):
        z = random.gauss(0.0, m.NATIONAL_SIGMA)
        zb = random.gauss(0.0, m.POLL_BIAS_SIGMA)
        regions = {}
        states = {}
        seats = not_up_d
        for mu, state in races:
            if state not in states:
                region = (m.STATE_SWING.get(state) or {}).get("region") or ""
                if region not in regions:
                    regions[region] = random.gauss(0.0, m.REGION_SIGMA)
                states[state] = regions[region] + random.gauss(0.0, m.STATE_SIGMA)
            swing = z + zb + states[state]
            p = 1.0 / (1.0 + math.exp(-(mu + swing) / m.LOGISTIC_BETA["governor"]))
            seats += 1 if random.random() < p else 0
        out.append(seats)
    out.sort()
    return out


def main():
    sims = N_SIMS
    if "--sims" in sys.argv:
        sims = int(sys.argv[sys.argv.index("--sims") + 1])
    print("Governor seat distribution | sims %d | national %.1f region %.1f state %.1f"
          % (sims, m.NATIONAL_SIGMA, m.REGION_SIGMA, m.STATE_SIGMA))
    for cycle in (2018, 2020, 2022, 2024):
        races, actual_up = build_cycle(cycle)
        actual = ACTUAL_FULL_D[cycle]
        not_up = actual - actual_up
        seats = simulate(races, not_up, sims)
        expected = sum(seats) / len(seats)
        p5 = seats[int(0.05 * len(seats))]
        p95 = seats[int(0.95 * len(seats))]
        p_majority = sum(1 for x in seats if x >= 26) / len(seats)
        pct = sum(1 for x in seats if x < actual) / len(seats)
        print("%d expected %5.1f  actual %3d  err %+5.1f  90%% [%d, %d]  "
              "P(D>=26) %4.1f%%  actual pct %4.1f%%"
              % (cycle, expected, actual, expected - actual, p5, p95,
                 100 * p_majority, 100 * pct))


if __name__ == "__main__":
    main()
