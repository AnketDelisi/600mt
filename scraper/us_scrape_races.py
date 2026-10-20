#!/usr/bin/env python3
"""Scrape 2026 U.S. midterm race data — races, ratings, PVI, incumbents — from
Wikipedia into data/us/races.json.

Sources
-------
* Senate  : https://en.wikipedia.org/wiki/2026_United_States_Senate_elections
            ("Predictions" table: State, PVI, incumbent, last election, ratings)
* House   : https://en.wikipedia.org/wiki/2026_United_States_House_of_Representatives_elections
            (per-state tables: District, CPVI, incumbent, party, first elected, status)
            + https://en.wikipedia.org/wiki/..._election_ratings
            (Cook / IE / Sabato ratings for competitive districts)
* Governor: https://en.wikipedia.org/wiki/2026_United_States_gubernatorial_elections
            ("Predictions" table like Senate)

Ratings use: Cook Political Report, Inside Elections, Sabato (as published on
Wikipedia). PVI column: positive = Republican-leaning, negative = Dem-leaning.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "us"
HEADERS = {"User-Agent": "600-us-midterms/1.0"}

WIKI = {
    "senate": "https://en.wikipedia.org/wiki/2026_United_States_Senate_elections",
    "house": "https://en.wikipedia.org/wiki/2026_United_States_House_of_Representatives_elections",
    "house_ratings": "https://en.wikipedia.org/wiki/2026_United_States_House_of_Representatives_election_ratings",
    "governor": "https://en.wikipedia.org/wiki/2026_United_States_gubernatorial_elections",
}


def fetch(url):
    resp = requests.get(url, headers=HEADERS, timeout=60)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "lxml")


def section_table(soup, heading_text, heading_level="h2"):
    """Return the first table inside a <h2>/<h3> section."""
    for hd in soup.find_all(heading_level):
        if heading_text in hd.get_text(strip=True):
            cur = hd.find_next()
            while cur is not None and getattr(cur, "name", None) != heading_level:
                if getattr(cur, "name", None) == "table":
                    return cur
                cur = cur.find_next()
    return None


def parse_pvi(text):
    """R+15 -> 15 (Republican margin), D+4 -> -4, '' -> 0."""
    text = text.strip()
    if not text:
        return 0
    m = re.match(r"([RD])\+?(\d+(?:\.\d+)?)", text)
    if not m:
        return 0
    party, n = m.group(1), float(m.group(2))
    return n if party == "R" else -n


def parse_last_result(text):
    """'60.10% R' / '54.6% D' -> {'pct':60.1,'party':'R'} else None."""
    text = text.strip()
    m = re.match(r"([\d.]+)\s*%\s*([RD])", text)
    if not m:
        return None
    return {"pct": float(m.group(1)), "party": m.group(2)}


def strip_footnote(text):
    return re.sub(r"\[\d+\]", "", text).strip()


def inc_status(incumbent, status=""):
    """'running' | 'open' from the incumbent name + status text.

    Open = retiring / term-limited / not seeking / lost renomination /
    vacancy / new seat. An empty incumbent or an unrecognized status with a
    named incumbent defaults to running (the common case).
    """
    s = ((incumbent or "") + " " + (status or "")).lower()
    if any(w in s for w in ("retiring", "term-limited", "term limited",
                            "not seeking", "lost renomination",
                            "none (new seat)", "vacancy", "vacant")):
        return "open"
    if not (incumbent or "").strip():
        return "open"
    return "running"


def clean_ratings(soup):
    """Ratings table -> list of row dicts.

    The sticky-header tables have two header rows; first row is the group
    ("State | PVI | Incumbent | Ratings"), second row is the actual column
    names. Data rows start below.
    """
    out = []
    header_row = None
    for row in soup.find_all("tr"):
        ths = row.find_all("th")
        if ths and len(ths) >= 3 and "Ratings" in ths[-1].get_text(strip=True):
            header_row = [th.get_text(" ", strip=True) for th in ths]
            continue
        tds = row.find_all("td")
        if not tds:
            continue
        # data row: first 4 cells are Constituency/PVI/Incumbent/Last election
        texts = [c.get_text(strip=True) for c in tds]
        if len(texts) < 8:
            continue
        out.append({"header": header_row, "cells": texts})
    return out


def find_ratings_columns(header_row):
    """Return index of Cook / IE / Sabato columns in header row."""
    idx = {}
    for i, h in enumerate(header_row):
        hl = h.lower()
        if "cook" in hl:
            idx.setdefault("cook", i)
        elif "ie" == hl or hl.startswith("ie ") or hl == "ie[1]" or "inside" in hl:
            idx.setdefault("ie", i)
        elif "sabato" in hl:
            idx.setdefault("sabato", i)
    return idx


def scrape_senate_or_gov(key):
    url = WIKI[key]
    soup = fetch(url)
    tbl = section_table(soup, "Predictions")
    if tbl is None:
        # the 2022 cycle article titles the section "Final pre-election
        # predictions"
        tbl = section_table(soup, "Final pre-election predictions")
    if tbl is None:
        raise RuntimeError(f"no Predictions table in {url}")

    # second header row defines columns: State | PVI | Incumbent | Last | <ratings>
    header = None
    for row in tbl.find_all("tr")[1:3]:
        ths = [th.get_text(" ", strip=True) for th in row.find_all("th")]
        if ths and "Cook" in " ".join(ths):
            header = ths
            break
    if header is None:
        raise RuntimeError(f"no ratings header in {url}")

    # locate ratings columns inside header: data rows start at PVI (index 0),
    # header starts at State (index 0) -> data index = header index - 1
    col = {}
    for i, h in enumerate(header):
        hl = h.lower()
        if "cook" in hl:
            col["cook"] = i - 1
        elif hl.startswith("ie") or "inside" in hl:
            col["ie"] = i - 1
        elif "sabato" in hl:
            col["sabato"] = i - 1
    col["pvi"] = 0
    col["incumbent"] = 1
    col["last"] = 2

    races = []
    for row in tbl.find_all("tr"):
        th = row.find("th")
        tds = row.find_all("td")
        if th is None or len(tds) < 8:
            continue
        cells = [c.get_text(strip=True) for c in tds]
        state = re.sub(r"\[.*?\]", "", re.sub(r"\(.*?\)", "", th.get_text(strip=True))).strip().title()
        if not state or state.lower().startswith("overall"):
            continue
        pvi = parse_pvi(cells[col["pvi"]])
        incumbent = strip_footnote(cells[col["incumbent"]])
        last_res = parse_last_result(cells[col["last"]])
        rating = {}
        for k in ("cook", "ie", "sabato"):
            idx = col.get(k)
            if idx is not None and idx < len(cells):
                rating[k] = cells[idx]
        party = None
        if last_res:
            party = last_res["party"]
        # interim appointee specials: seat holder party is a verifiable fact
        if key == "senate" and state in ("Florida", "Ohio"):
            party = "R"
        if party is None:
            for v in rating.values():
                m = re.search(r"\b([RD])\b", v)
                if m:
                    party = m.group(1)
                    break
        races.append({
            "state": state,
            "pvi": pvi,
            "pvi_label": cells[col["pvi"]],
            "incumbent": incumbent,
            "inc_status": inc_status(incumbent),
            "party": party,
            "last": last_res,
            "ratings": rating,
        })
    return races


SKIP_STATES = {
    "Contents", "Retirements", "Incumbents_defeated", "Opinion_polling",
    "Crossover_seats", "Mid-decade_redistricting_changes", "Election_ratings",
    "Special_elections", "Non-voting_delegates", "See also", "Notes", "References",
}


def state_tables(soup):
    """Yield (state_name, first_wikitable) for each state section."""
    for h in soup.find_all("h2"):
        sid = h.get("id")
        if not sid or sid in SKIP_STATES:
            continue
        nxt = h.find_next()
        while nxt is not None and getattr(nxt, "name", None) != "h2":
            if getattr(nxt, "name", None) == "table" and "wikitable" in (nxt.get("class") or []):
                yield sid, nxt
                break
            nxt = nxt.find_next()


def scrape_house():
    """435 districts from state sections + ratings overlay."""
    soup = fetch(WIKI["house"])
    races = []
    for state, tbl in state_tables(soup):
        for row in tbl.find_all("tr"):
            th = row.find("th")
            tds = row.find_all("td")
            # district lives in the first th of each district block
            dist = None
            if th is not None:
                m = re.match(r"^([A-Za-z ]+?)(\d+|at-large)$", th.get_text(strip=True))
                dist = m.group(2) if m else None
            if dist is None:
                continue
            if len(tds) < 4:
                continue
            cells = [c.get_text(strip=True) for c in tds]
            # normalize state name (h2 ids carry underscores: New_Hampshire)
            # PVI cell: first cell matching R+/D+
            pvi = 0
            pvi_label = ""
            for c in cells[:4]:
                if re.match(r"^[RD]\+?\d+(\.\d+)?$", c):
                    pvi = parse_pvi(c)
                    pvi_label = c
                    break
            # incumbent member + party
            inc = ""
            if cells[1] and "None" not in cells[1]:
                inc = strip_footnote(cells[1])
            elif cells[1] and "None" in cells[1]:
                inc = "None (new seat)" if "new seat" in cells[1].lower() else "Vacancy"
            party = None
            if "Democratic" in cells[2]:
                party = "D"
            elif "Republican" in cells[2]:
                party = "R"
            # status: 'Retiring'/'Incumbent renominating'/'Open seat'/'Running'
            status = ""
            for c in cells[4:7]:
                cl = c.lower()
                if any(w in cl for w in ("retir", "renominat", "open", "running", "lost", "seek", "interest", "new", "term", "vacan", "appoint")):
                    status = strip_footnote(c)
                    break
            if not inc:
                inc = "Vacancy"
            races.append({
                "state": state.replace("_", " "),
                "district": dist,
                "pvi": pvi,
                "pvi_label": pvi_label,
                "incumbent": inc,
                "inc_status": inc_status(inc, status),
                "party": party,
                "status": status,
                "ratings": {},
            })
    # overlay ratings
    soup2 = fetch(WIKI["house_ratings"])
    tbl = soup2.find("table", class_="wikitable")
    # column positions in the data row (td): 0 CPVI, 1 Incumbent, 2 Last result,
    # 3 Cook, 4 IE, 5 Sabato, ...
    col = {"cook": 3, "ie": 4, "sabato": 5}
    # map ratings rows to races by state+district key
    race_by_key = {}
    for race in races:
        race_by_key[race["state"].title() + " " + (race["district"] if race["district"] != "at-large" else "at-large")] = race
    for row in tbl.find_all("tr"):
        th = row.find("th")
        tds = row.find_all("td")
        if th is None or len(tds) < 8:
            continue
        m = re.match(r"^([A-Za-z ]+?)(\d+|at-large)$", th.get_text(strip=True))
        if not m:
            continue
        state = m.group(1).title()
        key = state + " " + m.group(2)
        race = race_by_key.get(key)
        if race is None:
            continue
        cells = [c.get_text(strip=True) for c in tds]
        race["ratings"] = {
            "cook": cells[col["cook"]],
            "ie": cells[col["ie"]],
            "sabato": cells[col["sabato"]],
        }
        # the same table carries the seat's last result ("54.6% D"), which the
        # main per-state tables do not: it feeds the last-result blend and the
        # track-record-scaled personal-vote term for rated districts
        if race.get("last") is None:
            race["last"] = parse_last_result(cells[2])
    return races


def partisan_composition(soup):
    """Pre-election chamber composition from the infobox 'Current seats' rows.

    Returns {'r': <rep seats>, 'd': <dem seats>, 'i': <independents>} if found.
    """
    ib = soup.find("table", class_="infobox")
    if ib is None:
        return {}
    seats_rows = []
    for row in ib.find_all("tr"):
        ths = [th.get_text(" ", strip=True) for th in row.find_all("th")]
        if " ".join(ths).strip().lower() not in ("current seats", "currentseats"):
            continue
        nums = []
        for t in row.find_all(["th", "td"]):
            m = re.match(r"^\s*(\d+)", t.get_text(strip=True))
            if m:
                nums.append(int(m.group(1)))
        if nums:
            seats_rows.append(nums)
    if not seats_rows:
        return {}
    main = seats_rows[0]
    out = {"r": main[0], "d": main[1], "i": 0}
    for nums in seats_rows[1:]:
        if len(nums) == 1:
            out["i"] = nums[0]
    return out


def scrape_generic_ballot():
    """Generic-congressional-ballot polling table from the House article."""
    soup = fetch(WIKI["house"])
    # the article renamed this section (was "Opinion polling"); try the
    # current title first, keep the old one as fallback
    tbl = section_table(soup, "Generic congressional ballot")
    if tbl is None:
        tbl = section_table(soup, "Opinion polling")
    if tbl is None:
        return None
    # locate Dem / Rep columns from the header row
    demo = rep = None
    for row in tbl.find_all("tr"):
        cells = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
        for i, c in enumerate(cells):
            cl = c.lower()
            if cl.startswith("republic") or cl.startswith("rep"):
                rep = i
            if cl.startswith("democrat") or cl.startswith("dem"):
                demo = i
        if demo is not None and rep is not None:
            break

    def num(s):
        m = re.match(r"(\d{1,3}(?:\.\d+)?)\s*%?", s)
        return float(m.group(1)) if m else None

    out = []
    for row in tbl.find_all("tr")[1:]:
        cells = [c.get_text(strip=True) for c in row.find_all("td")]
        if demo is None or rep is None or len(cells) <= max(demo, rep):
            continue
        pd, pr = num(cells[demo]), num(cells[rep])
        if pd is None or pr is None:
            continue
        pollster = strip_footnote(cells[0])
        if not pollster or pollster.lower() == "average":
            # 'Average' row drops merged 'Dates' columns and realigns the
            # percentages; skip it (the environment uses the aggregator rows).
            continue
        dates = cells[1] if len(cells) > 1 else ""
        out.append({"pollster": pollster, "dates": dates, "dem": pd, "rep": pr})
    return out[:60] or None


def scrape_compositions():
    """Current chamber composition (D, R seats) before the 2026 election."""
    out = {}
    for key in ("senate", "house"):
        soup = fetch(WIKI[key])
        comp = partisan_composition(soup)
        if comp:
            out[key] = comp
    # governors: current holder counts limited to the 36 states on the ballot
    gov_holder = scrape_senate_or_gov("governor")
    out["governor"] = {
        "r": sum(1 for r in gov_holder if r["party"] == "R"),
        "d": sum(1 for r in gov_holder if r["party"] == "D"),
    }
    return out, gov_holder


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    senate = scrape_senate_or_gov("senate")
    governor = scrape_senate_or_gov("governor")
    house = scrape_house()
    composition, _gov_holder = scrape_compositions()
    ballot = scrape_generic_ballot()

    print(f"Senate: {len(senate)} | House: {len(house)} | Governor: {len(governor)}")
    assert len(senate) >= 30, "senate parse failed"
    assert len(house) >= 400, f"house parse failed: {len(house)}"
    assert len(governor) >= 30, "governor parse failed"

    out = {
        "scraped_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": WIKI,
        "composition": composition,
        "generic_ballot": ballot,
        "races": {
            "senate": senate,
            "house": house,
            "governor": governor,
        },
    }
    out_file = OUTPUT_DIR / "races.json"
    out_file.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {out_file}")

    # sample output
    for c in ["senate", "house", "governor"]:
        rs = out["races"][c]
        print(f"\n--- {c.upper()} ({len(rs)}) ---")
        for r in rs[:6]:
            print(" ", r)


if __name__ == "__main__":
    main()