#!/usr/bin/env python3
"""Fetch Silver Bulletin's published state elasticity scores.

These are the CCES 2022/2024-based scores shown in the Silver Bulletin
polling-average methodology page (Datawrapper pcdxe/3). This is a fixed
structural input, not a poll; keeping the builder separate makes the source
and vintage explicit.

Writes data/us/state_elasticity.json.
Run: python scraper/us_build_elasticity.py
"""
import csv
import io
import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "us" / "state_elasticity.json"
URL = "https://datawrapper.dwcdn.net/pcdxe/3/dataset.csv"
SOURCE = ("Silver Bulletin, 2026 elasticity scores (CCES 2022/2024); "
          "https://www.natesilver.net/p/silver-bulletin-polling-average-methodology")

import sys
sys.path.insert(0, str(ROOT / "scraper"))
import us_build_pres_cd as bpc


def main():
    text = requests.get(URL, timeout=60,
                        headers={"User-Agent": "600mt/1.0"}).text
    rows = list(csv.reader(io.StringIO(text), delimiter="\t"))
    out = {}
    for row in rows:
        for i in range(0, len(row) - 1, 2):
            code = row[i].strip().upper()
            value = row[i + 1].strip()
            if code in bpc.STATE and value:
                try:
                    out[bpc.STATE[code]] = round(float(value), 2)
                except ValueError:
                    pass
    data = {
        "source": SOURCE,
        "method": "state elasticity from CCES microdata; 0.90 MS to 1.25 HI",
        "scores": out,
    }
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False),
                   encoding="utf-8")
    print("states", len(out), "| range", min(out.values()), max(out.values()))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
