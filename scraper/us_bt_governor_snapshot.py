#!/usr/bin/env python3
"""Cache the governor backtest races (features + polls + actuals + the last
state presidential lean) for fast model iteration.

Usage: python scraper/us_bt_governor_snapshot.py [2018] [2020] [2022] [2024]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import us_backtest as bt
import us_scrape_model as m

CACHE = Path(__file__).resolve().parent / ".cache"
CACHE.mkdir(exist_ok=True)
PRES_YEAR = {2018: "2016", 2020: "2016", 2022: "2020", 2024: "2020"}


def clean_polls(p):
    if not p:
        return None
    out = {k: v for k, v in p.items() if k != "polls"}
    if p.get("polls"):
        out["polls"] = p["polls"]
    return out


def main():
    cycles = [int(x) for x in sys.argv[1:]] or [2022, 2024]
    for cycle in cycles:
        path = CACHE / ("us_gov_bt_%d.json" % cycle)
        if path.is_file():
            print("cached", path)
            continue
        print("scraping", cycle, "governors ...")
        races = bt.load_governors(cycle)
        env = bt.CYCLES[cycle]["env_fallback"]
        rows = []
        for race in races:
            rows.append({
                "state": race["state"], "pvi": race.get("pvi"),
                "party": race.get("party"), "incumbent": race.get("incumbent"),
                "ratings": race.get("ratings"), "last": race.get("last"),
                "polls": clean_polls(race.get("_polls")),
                "actual": race.get("_actual"),
                "state_pres": m.state_lean(race, PRES_YEAR[cycle]),
                "env": env,
            })
        path.write_text(json.dumps(rows, indent=1), encoding="utf-8")
        print("wrote", path, "races:", len(rows),
              "| actual:", sum(1 for r in rows if r["actual"] is not None),
              "| polls:", sum(1 for r in rows if r["polls"]))


if __name__ == "__main__":
    main()
