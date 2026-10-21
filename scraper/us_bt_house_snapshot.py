#!/usr/bin/env python3
"""Cache the House backtest races (features + polls + actuals + the last
presidential result by the cycle's district lines).

Usage: python scraper/us_bt_house_snapshot.py [2022] [2024]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import us_backtest as bt

CACHE = Path(__file__).resolve().parent / ".cache"
CACHE.mkdir(exist_ok=True)
PRES = json.loads((Path(__file__).resolve().parent.parent / "data" / "us"
                   / "pres_by_cd.json").read_text(encoding="utf-8"))


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
        path = CACHE / ("us_house_bt_%d.json" % cycle)
        if path.is_file():
            print("cached", path)
            continue
        print("scraping", cycle, "House ...")
        races, env = bt.load_house(cycle)
        pres = PRES.get(str(cycle)) or {}
        rows = []
        for race in races:
            key = race["state"] + " " + str(race.get("district", ""))
            rows.append({
                "state": race["state"], "district": race.get("district"),
                "pvi": race.get("pvi"), "party": race.get("party"),
                "incumbent": race.get("incumbent"),
                "ratings": race.get("ratings"), "last": race.get("last"),
                "polls": clean_polls(race.get("_polls")),
                "actual": race.get("_actual"),
                "pres": pres.get(key), "env": env,
            })
        path.write_text(json.dumps(rows, indent=1), encoding="utf-8")
        print("wrote", path, "races:", len(rows),
              "| pres:", sum(1 for r in rows if r["pres"] is not None),
              "| actual:", sum(1 for r in rows if r["actual"] is not None))


if __name__ == "__main__":
    main()
