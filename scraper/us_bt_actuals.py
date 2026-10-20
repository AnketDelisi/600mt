#!/usr/bin/env python3
"""Rebuild the Senate backtest actuals from the national results tables and
patch the cached snapshots.

2022 uses the ratings table's Result column (State ... Result);
2024 uses the candidates table (State | Incumbent | Candidates).
The per-state article parser mangles New Hampshire-style tables and misses
several 2024 pages, so the national article is the source of truth here.

Usage: python scraper/us_bt_actuals.py 2022 2024
"""
import json
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

CACHE = Path(__file__).resolve().parent / ".cache"
H = {"User-Agent": "600mt/1.0"}


def pairs(result):
    d = r = 0.0
    for party, pct in re.findall(r"\(([^)]+)\)\s*([\d.]+)\s*%", result):
        p = party.lower()
        if p.startswith("democrat"):
            d += float(pct)
        elif p.startswith("republic"):
            r += float(pct)
    return d, r


def candidates_table(soup):
    """2024-style: header row State | Incumbent | Candidates."""
    for tbl in soup.find_all("table", class_="wikitable"):
        rows = tbl.find_all("tr")
        if not rows:
            continue
        hdr = [c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"])]
        if not hdr or hdr[0] != "State" or not any("candidate" in h.lower() for h in hdr):
            continue
        if len(rows) < 10:
            continue
        out = []
        for row in rows[1:]:
            cells = [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])]
            if len(cells) < 3 or cells[0] in ("Senator", "State"):
                continue
            state = re.sub(r"\s*\(Class\s+\d+\)$", "", cells[0]).strip()
            d, r = pairs(cells[-1])
            if d > 0 and r > 0 and d + r > 50:
                out.append((state, round((d - r) / (d + r) * 100.0, 2)))
        if out:
            return out
    return []


def ratings_table(soup):
    """2022-style: ratings table with a final Result column."""
    for tbl in soup.find_all("table", class_="wikitable"):
        rows = tbl.find_all("tr")
        start = None
        for i, row in enumerate(rows):
            cells = [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])]
            if len(cells) > 5 and cells[0] == "State" and "Result" in cells[-1]:
                start = i + 1
                break
        if start is None:
            continue
        out = []
        for row in rows[start:]:
            cells = [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])]
            if not cells or cells[0] in ("State",):
                continue
            state = re.sub(r"\s*\(Class\s+\d+\)$", "", cells[0]).strip()
            d, r = pairs(cells[-1])
            if d > 0 and r > 0 and d + r > 50:
                out.append((state, round((d - r) / (d + r) * 100.0, 2)))
        if out:
            return out
    return []


def national_actuals(cycle):
    url = ("https://en.wikipedia.org/wiki/%d_United_States_Senate_elections"
           % cycle)
    soup = BeautifulSoup(requests.get(url, headers=H, timeout=60).text, "lxml")
    return candidates_table(soup) or ratings_table(soup)


def main():
    cycles = [int(x) for x in sys.argv[1:]] or [2022, 2024]
    for cycle in cycles:
        rows = national_actuals(cycle)
        by_state = {}
        for st, m in rows:
            by_state.setdefault(st, []).append(m)
        path = CACHE / ("us_bt_%d.json" % cycle)
        races = json.loads(path.read_text(encoding="utf8"))
        used = {}
        patched = 0
        for r in races:
            st = r["state"]
            if st == "Alaska":
                r["actual"] = None
                continue
            lst = by_state.get(st)
            if not lst:
                continue
            i = used.get(st, 0)
            val = lst[min(i, len(lst) - 1)]
            used[st] = i + 1
            if r.get("actual") != val:
                r["_old_actual"] = r.get("actual")
                patched += 1
            r["actual"] = val
        path.write_text(json.dumps(races, indent=1), encoding="utf8")
        print(cycle, "actuals:", len(rows), "| patched", patched,
              "| races", len(races), "| missing:",
              [r["state"] for r in races if r.get("actual") is None])
        for r in races:
            if r.get("_old_actual") is not None and abs((r["_old_actual"] or 0) - (r["actual"] or 0)) > 1:
                print("  %-18s %+7.1f -> %+7.1f" % (r["state"], r["_old_actual"], r["actual"]))


if __name__ == "__main__":
    main()
