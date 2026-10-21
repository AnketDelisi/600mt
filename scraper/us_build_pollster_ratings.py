#!/usr/bin/env python3
"""Fetch Silver Bulletin pollster ratings.

The Datawrapper table behind the Silver Bulletin pollster-ratings page. We use
the predictive plus-minus as a relative poll weight; negative is better.

Writes data/us/pollster_ratings.json.
Run: python scraper/us_build_pollster_ratings.py
"""
import csv
import io
import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "us" / "pollster_ratings.json"
URL = "https://datawrapper.dwcdn.net/GiFps/3/dataset.csv"


def main():
    r = requests.get(URL, headers={"User-Agent": "600mt/1.0"}, timeout=60)
    r.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(r.text), delimiter="\t"))
    scores = {}
    for row in rows:
        name = (row.get("pollster") or "").strip()
        if not name:
            continue
        key = " ".join(name.lower().split())
        try:
            ppm = float(row.get("predictiveplusminus") or 0.0)
        except ValueError:
            ppm = 0.0
        try:
            n = int(float(row.get("numpolls") or 0))
        except ValueError:
            n = 0
        scores[key] = {
            "name": name,
            "grade": (row.get("grade") or "").split("@@")[0].strip(),
            "ppm": round(ppm, 3),
            "n": n,
        }
    out = {
        "source": "Silver Bulletin pollster ratings (Datawrapper GiFps/3)",
        "scores": scores,
    }
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False),
                   encoding="utf-8")
    print("pollsters", len(scores), "| wrote", OUT)


if __name__ == "__main__":
    main()
