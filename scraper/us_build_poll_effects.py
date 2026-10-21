#!/usr/bin/env python3
"""Estimate shrunk pollster house effects from the historical snapshots.

Fits 2018-2022 only; 2024 stays a holdout. A two-way fixed-effects model
polls ~ race mean + pollster effect is fitted iteratively, then shrunk by
poll count. Partisan polls are excluded from estimation (they are still used
in the forecast, with their existing weight).

Writes data/us/pollster_effects.json.
Run: python scraper/us_build_poll_effects.py
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scraper"))
import us_scrape_model as m

CACHE = ROOT / "scraper" / ".cache"
OUT = ROOT / "data" / "us" / "pollster_effects.json"
FIT_CYCLES = (2018, 2020, 2022)
SHRINK = 5.0
ITERATIONS = 30
CHAMBERS = {
    "senate": "us_bt_%d.json",
    "house": "us_house_bt_%d.json",
    "governor": "us_gov_bt_%d.json",
}


def load_rows():
    rows = []
    for chamber, pattern in CHAMBERS.items():
        for cycle in FIT_CYCLES:
            path = CACHE / (pattern % cycle)
            if not path.is_file():
                continue
            for race in json.loads(path.read_text(encoding="utf8")):
                if race.get("actual") is None:
                    continue
                pe = race.get("polls") or {}
                race_key = "%s|%d|%s|%s" % (
                    chamber, cycle, race.get("state"),
                    race.get("district", ""))
                for pol in pe.get("polls") or []:
                    if pol.get("partisan"):
                        continue
                    if pol.get("dem") is None or pol.get("rep") is None:
                        continue
                    pollster = (pol.get("pollster") or "").strip()
                    if not pollster or pollster.lower() in ("average", ""):
                        continue
                    margin = m.two_party(pol["dem"], pol["rep"])
                    if margin is None:
                        continue
                    rows.append((chamber, race_key, m.pollster_key(pollster),
                                 pollster, margin))
    return rows


def fit(rows):
    by_race = defaultdict(list)
    names = {}
    for _, race_key, key, name, margin in rows:
        by_race[race_key].append((margin, key))
        names.setdefault(key, name)
    races = {k: v for k, v in by_race.items() if len(v) >= 2}
    effects = defaultdict(float)
    counts = defaultdict(int)
    if not races:
        return {}
    for _ in range(ITERATIONS):
        means = {}
        for race_key, polls in races.items():
            means[race_key] = sum(
                margin - effects[key] for margin, key in polls) / len(polls)
        num = defaultdict(float)
        cnt = defaultdict(int)
        for race_key, polls in races.items():
            for margin, key in polls:
                num[key] += margin - means[race_key]
                cnt[key] += 1
        new = {key: (num[key] / cnt[key]) * cnt[key] / (cnt[key] + SHRINK)
               for key in cnt}
        vals = [new[key] for polls in races.values() for _, key in polls]
        center = sum(vals) / len(vals) if vals else 0.0
        effects = {key: val - center for key, val in new.items()}
        counts = cnt
    return {
        key: {"effect": round(val, 2),
              "n": counts[key],
              "name": names.get(key, key)}
        for key, val in sorted(effects.items(), key=lambda x: -abs(x[1]))
    }


def main():
    rows = load_rows()
    if not rows:
        raise SystemExit("no cached polls; rebuild the backtest snapshots first")
    all_effects = fit(rows)
    chamber_effects = {}
    for chamber in CHAMBERS:
        chamber_effects[chamber] = fit(
            [x for x in rows if x[0] == chamber])
    out = {
        "source": "600 pollster house effects from 2018-22 snapshots",
        "fit_cycles": list(FIT_CYCLES),
        "shrink": SHRINK,
        "min_race_polls": 2,
        "effects": {"all": all_effects, **chamber_effects},
    }
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False),
                   encoding="utf-8")
    print("polls:", len(rows), "| races:", len({r[1] for r in rows}))
    for chamber in ("all", "senate", "house", "governor"):
        table = out["effects"][chamber]
        print("%-9s pollsters %3d" % (chamber, len(table)))
        for key, item in list(table.items())[:8]:
            print("  %-28s %+5.1f  n=%d" % (
                item["name"][:28], item["effect"], item["n"]))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
