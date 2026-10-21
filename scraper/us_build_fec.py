#!/usr/bin/env python3
"""Build Senate and House candidate-fundraising totals from FEC bulk data.

Downloads weball<cycle>.zip from the FEC bulk downloads (candidate financial
summaries), keeps the highest-receipts Democrat and Republican per
state/cycle (Senate) or state/district/cycle (House). No API key or rate limit.

Writes data/us/senate_fundraising.json and data/us/house_fundraising.json.
Run: python scraper/us_build_fec.py
"""
import json
import sys
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "scraper" / ".cache"
OUT = ROOT / "data" / "us" / "senate_fundraising.json"
HOUSE_OUT = ROOT / "data" / "us" / "house_fundraising.json"
CYCLES = (2018, 2020, 2022, 2024, 2026)
BASE = "https://www.fec.gov/files/bulk-downloads/%d/weball%02d.zip"

sys.path.insert(0, str(ROOT / "scraper"))
import us_build_pres_cd as bpc


def ensure_zip(cycle):
    path = CACHE / ("weball%02d.zip" % (cycle % 100))
    if path.is_file():
        return path
    url = BASE % (cycle, cycle % 100)
    print("downloading", url)
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as fh:
            for chunk in r.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
    return path


def parse_cycle(cycle):
    path = ensure_zip(cycle)
    with zipfile.ZipFile(path) as z:
        raw = z.read(z.namelist()[0]).decode("latin1")
    out = {}
    for line in raw.splitlines():
        parts = line.split("|")
        if len(parts) < 20 or not parts[0].startswith("S"):
            continue
        party = parts[4]
        if party not in ("DEM", "REP"):
            continue
        state = bpc.STATE.get(parts[18])
        if not state:
            continue
        try:
            receipts = float(parts[5] or 0.0)
        except ValueError:
            continue
        entry = out.setdefault(state, {})
        if receipts > entry.get(party, {}).get("receipts", -1):
            entry[party] = {
                "name": parts[1],
                "receipts": round(receipts, 2),
                "candidate_id": parts[0],
            }
    return out


def parse_house_cycle(cycle):
    path = ensure_zip(cycle)
    with zipfile.ZipFile(path) as z:
        raw = z.read(z.namelist()[0]).decode("latin1")
    out = {}
    for line in raw.splitlines():
        parts = line.split("|")
        if len(parts) < 20 or not parts[0].startswith("H"):
            continue
        party = parts[4]
        if party not in ("DEM", "REP"):
            continue
        state = bpc.STATE.get(parts[18])
        if not state:
            continue
        district = (parts[19] or "00").strip()
        try:
            district = "%02d" % int(district)
        except ValueError:
            district = "00"
        try:
            receipts = float(parts[5] or 0.0)
        except ValueError:
            continue
        entry = out.setdefault(state, {}).setdefault(district, {})
        if receipts > entry.get(party, {}).get("receipts", -1):
            entry[party] = {
                "name": parts[1],
                "receipts": round(receipts, 2),
                "candidate_id": parts[0],
            }
    return out


def main():
    data = {}
    house_data = {}
    for cycle in CYCLES:
        print("FEC Senate", cycle)
        data[str(cycle)] = parse_cycle(cycle)
        print("FEC House", cycle)
        house_data[str(cycle)] = parse_house_cycle(cycle)
        print("  states", len(data[str(cycle)]),
              "| house states", len(house_data[str(cycle)]))
    out = {
        "source": "FEC bulk weball<cycle>.zip (candidate financial summaries)",
        "method": "highest-receipts Democrat and Republican per state/cycle",
        "cycles": data,
    }
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False),
                   encoding="utf-8")
    house_out = {
        "source": out["source"],
        "method": ("highest-receipts Democrat and Republican per "
                   "state/district/cycle"),
        "cycles": house_data,
    }
    HOUSE_OUT.write_text(json.dumps(house_out, indent=1, ensure_ascii=False),
                         encoding="utf-8")
    print("wrote", OUT)
    print("wrote", HOUSE_OUT)


if __name__ == "__main__":
    main()
