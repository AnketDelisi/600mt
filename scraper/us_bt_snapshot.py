#!/usr/bin/env python3
"""Cache the Senate backtest races (features + polls + actuals) for fast
model iteration. Writes scraper/.cache/us_bt_<cycle>.json.

Usage: python scraper/us_bt_snapshot.py [2022] [2024]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import us_backtest as bt

CACHE = Path(__file__).resolve().parent / ".cache"
CACHE.mkdir(exist_ok=True)


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
        path = CACHE / ("us_bt_%d.json" % cycle)
        if path.is_file():
            print("cached", path)
            continue
        print("scraping", cycle, "Senate ...")
        races = bt.load_races(cycle)
        rows = []
        for race in races:
            rows.append({
                "state": race["state"], "pvi": race.get("pvi"),
                "party": race.get("party"), "incumbent": race.get("incumbent"),
                "ratings": race.get("ratings"), "last": race.get("last"),
                "polls": clean_polls(race.get("_polls")),
                "actual": race.get("_actual"),
            })
        path.write_text(json.dumps(rows, indent=1), encoding="utf-8")
        print("wrote", path, "races:", len(rows))


if __name__ == "__main__":
    main()
