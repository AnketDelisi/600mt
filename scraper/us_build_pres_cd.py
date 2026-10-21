#!/usr/bin/env python3
"""Build the district presidential-lean lookup from The Downballot's
calculations (2024/2020 results by the 2026, 2024 and 2022 district lines).

The model uses the latest presidential result before the cycle:
  2026 -> 2024 results by the 2026 lines
  2024 -> 2020 results by the 2024 lines
  2022 -> 2020 results by the 2022 lines
  2018/2020 -> 2016 results by the 2018 lines (the 2020 House used them too)
The file is static (the results and lines do not change); the daily scraper
does not touch it.

Usage: python scraper/us_build_pres_cd.py
"""
import csv
import io
import json
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parent.parent / "data" / "us" / "pres_by_cd.json"
H = {"User-Agent": "600mt/1.0"}

# (spreadsheet id, gid, margin column index)
SOURCES = {
    "2026": ("1eZfaFI-c-PFOoKx1-zZA2MP0_dxRq_LVK0re3BOQqy0", "620838163", 5),
    "2024": ("1ng1i_Dm_RMDnEvauH44pgE6JCUsapcuu8F2pCfeLWFo", "620838163", 8),
    "2022": ("1CKngqOp8fzU22JOlypoxNsxL6KSAH920Whc-rd7ebuM", "1871835782", 5),
}
# Older Downballot sheets list Clinton/Trump rather than a margin column.
PAIR_SOURCES = {
    "2018": ("1zLNAuRqPauss00HDz4XbTH2HqsCzMe0pR8QmD1K8jk8", "0", 3, 4),
    "2020": ("1zLNAuRqPauss00HDz4XbTH2HqsCzMe0pR8QmD1K8jk8", "0", 3, 4),
}

STATE = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}


def fetch(sheet, gid):
    url = ("https://docs.google.com/spreadsheets/d/%s/export?format=csv&gid=%s"
           % (sheet, gid))
    resp = requests.get(url, headers=H, timeout=60)
    resp.raise_for_status()
    return list(csv.reader(io.StringIO(resp.text)))


def parse(rows, col):
    """{Full state + ' ' + district: presidential margin}."""
    out = {}
    started = False
    for row in rows:
        if not started:
            if row and row[0] == "District":
                started = True
            continue
        if not row or len(row) <= col or not row[0].strip():
            continue
        code = row[0].strip()
        if "-" not in code:
            continue
        st, dist = code.split("-", 1)
        if st not in STATE:
            continue
        if dist.upper() in ("AL", "00"):
            dist = "at-large"
        else:
            dist = str(int(dist))
        try:
            margin = float(row[col])
        except (TypeError, ValueError):
            continue
        out[STATE[st] + " " + dist] = margin
    return out


def parse_pair(rows, dcol, rcol):
    """{Full state + ' ' + district: 2016 margin} from Clinton/Trump."""
    out = {}
    started = False
    for row in rows:
        if not started:
            if row and row[0] == "CD":
                started = True
            continue
        if not row or len(row) <= max(dcol, rcol) or not row[0].strip():
            continue
        code = row[0].strip()
        if "-" not in code:
            continue
        st, dist = code.split("-", 1)
        if st not in STATE:
            continue
        if dist.upper() in ("AL", "00"):
            dist = "at-large"
        else:
            dist = str(int(dist))
        try:
            d = float(row[dcol])
            r = float(row[rcol])
        except (TypeError, ValueError):
            continue
        if d + r <= 0:
            continue
        out[STATE[st] + " " + dist] = (d - r) / (d + r) * 100
    return out


def main():
    data = {}
    for cycle, (sheet, gid, col) in SOURCES.items():
        rows = fetch(sheet, gid)
        data[cycle] = parse(rows, col)
        print(cycle, len(data[cycle]), "districts")
    for cycle, (sheet, gid, dcol, rcol) in PAIR_SOURCES.items():
        rows = fetch(sheet, gid)
        data[cycle] = parse_pair(rows, dcol, rcol)
        print(cycle, len(data[cycle]), "districts")
    OUT.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    print("wrote", OUT)
    for cyc in data:
        k = "Alabama 1" if "Alabama 1" in data[cyc] else next(iter(data[cyc]))
        print(cyc, k, data[cyc][k])


if __name__ == "__main__":
    main()
