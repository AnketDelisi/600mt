#!/usr/bin/env python3
"""Parse per-race polling averages for 2026 U.S. races from Wikipedia.

Preference order per race:
  1. "Aggregate polls" table on the state-specific articles
     (270toWin / DDHQ / Race to the WH / Silver Bulletin / FiftyPlusOne
     averages) — take the "Average" row if present, else first data row.
  2. Simple average of the latest direct candidate polls (up to 5) if no
     aggregate table exists.

Races are not always Democrat-vs-Republican: Nebraska (Dan Osborn), Idaho
(Todd Achilles), South Dakota (Brian Bengs) and Montana (Seth Bodnar) have a
serious INDEPENDENT, so tables can be (R)+(I) or (D)+(R)+(I). The parser
picks the main candidate column per party by highest average share, requires
at least two sides whose shares sum to >= 75 (fragment/jungle tables fall
back to ratings), and captures the candidate names from the race infobox.

Sources:
  https://en.wikipedia.org/wiki/2026_United_States_Senate_election_in_<State>
  .../2026_United_States_gubernatorial_election_in_<State>
  .../2026_United_States_House_of_Representatives_election_in_Alaska
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "us"
HEADERS = {"User-Agent": "600-us-midterms/1.0"}

RACE_ID_MAP = {
    # races whose state-article title differs from a plain "in <State>"
    "Florida": "2026_United_States_Senate_special_election_in_Florida",
    "Ohio": "2026_United_States_Senate_special_election_in_Ohio",
}

# House races: district-level polling comes from the per-state articles
# ("... elections in <State>", singular "election" for single-district
# states), whose "District N" sections carry the same matchup tables.
SINGLE_DISTRICT = {"Alaska", "Delaware", "North Dakota", "South Dakota",
                   "Vermont", "Wyoming"}


def fetch(url):
    resp = requests.get(url, headers=HEADERS, timeout=40)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "lxml")


def pct(s):
    m = re.match(r"\s*(\d{1,3}(?:\.\d+)?)\s*%", s)
    return float(m.group(1)) if m else None


def party_cols(header, rows):
    """Main (D)/(R)/(I) candidate columns by highest average share.

    Multi-candidate tables list the main candidates first but often add minor
    (D)/(R)/(I) candidates after them (Alaska's 9-candidate Senate field);
    the main column is the one with the highest average poll percentage.
    Races where the main challenger is an independent (Nebraska, Idaho,
    South Dakota) have (R)+(I) headers with no (D) at all.
    Returns a dict of the present parties (at least two) or None.
    """
    cand = {"D": [], "R": [], "I": []}
    for i, h in enumerate(header):
        hu = h.upper()
        if "(D" in hu:
            cand["D"].append(i)
        elif "(R" in hu:
            cand["R"].append(i)
        elif "(I" in hu:
            cand["I"].append(i)
    present = {k: v for k, v in cand.items() if v}
    if len(present) < 2:
        return None

    def best(idxs):
        if len(idxs) == 1:
            return idxs[0]
        mean = {}
        for i in idxs:
            vals = []
            for row in rows[1:]:
                cells = [c.get_text(" ", strip=True)
                         for c in row.find_all(["th", "td"])]
                if i < len(cells):
                    v = pct(cells[i])
                    if v is not None and v > 5:  # ignore minor-candidate crumbs
                        vals.append(v)
            mean[i] = sum(vals) / len(vals) if vals else -1
        return max(idxs, key=lambda i: mean[i])
    return {k: best(v) for k, v in present.items()}


def clean_name(s):
    """Drop Wikipedia footnote markers like '[ 116 ]' or '[ r ]'."""
    return re.sub(r"\[\s*[0-9a-zA-Z]{1,4}\s*\]", "", s or "").strip()


def key_of(party):
    return {"D": "dem", "R": "rep", "I": "ind"}[party]


def sponsor_of(cell):
    """Partisan sponsor marker from a pollster cell: 'D'/'R'/'I'/None.

    Wikipedia annotates partisan pollsters ("Public Policy Polling (D)",
    "co/efficient (R)", "Fabrizio Ward (R)/Impact Research (D)"), which the
    parsers used to strip and discard - exactly the polls whose house effect
    matters.
    """
    m = re.search(r"\((D|R|I)\)", cell or "")
    return m.group(1) if m else None


MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], 1)}
DATE_RE = re.compile(
    r"(january|february|march|april|may|june|july|august|september|"
    r"october|november|december)\s+(\d{1,2})?(?:\s*[–-]\s*(\d{1,2}))?"
    r",?\s*(\d{4})")


def date_key(s):
    """Sortable (year, month, day) from a Wikipedia poll date string.

    'September 24 - October 1, 2026' -> the last (end) date wins; strings
    without a month/day (e.g. 'July 2026') fall back to the 1st.
    """
    hits = DATE_RE.findall((s or "").lower())
    if not hits:
        return (0, 0, 0)
    mon, d1, d2, yr = hits[-1]
    return (int(yr), MONTHS[mon], int(d2 or d1 or 1))


def nominees(soup):
    """Nominee/candidate names from the race infobox -> {d, r, i}."""
    out = {}
    ib = soup.find("table", class_="infobox")
    if not ib:
        return out
    names_row = parties_row = None
    for tr in ib.find_all("tr"):
        cells = [c.get_text(" ", strip=True)
                 for c in tr.find_all(["th", "td"])]
        if not cells:
            continue
        if cells[0] in ("Nominee", "Candidate") and len(cells) > 1:
            names_row = cells[1:]
        elif cells[0] == "Party" and len(cells) > 1:
            parties_row = cells[1:]
    if not names_row or not parties_row:
        return out
    for nm, party in zip(names_row, parties_row):
        pl = (party or "").lower()
        if not nm:
            continue
        if pl.startswith("republic"):
            out["r"] = clean_name(nm)
        elif pl.startswith("democrat"):
            out["d"] = clean_name(nm)
        elif "independent" in pl:
            out["i"] = clean_name(nm)
    return out


def parse_aggregate(soup, tables=None):
    """Read the latest general-election 'Aggregate polls' table -> dict or None.

    A qualifying table has candidate headers annotated with party letters and
    an 'Average' data row. The latest such table in the article wins.
    """
    best = None
    for tbl in (tables if tables is not None
                else soup.find_all("table", class_="wikitable")):
        rows = tbl.find_all("tr")
        if len(rows) < 4:
            continue
        header = [c.get_text(" ", strip=True).replace("\u200b", "")
                  for c in rows[0].find_all(["th", "td"])]
        cols = party_cols(header, rows)
        if cols is None:
            continue
        chosen = None
        for row in rows[1:]:
            cells = [c.get_text(" ", strip=True)
                     for c in row.find_all(["th", "td"])]
            if not cells:
                continue
            if "average" in cells[0].lower():
                chosen = cells
        if chosen is None:
            continue
        # the Average row may skip merged 'Dates' columns -> realign by gap
        gap = len(header) - len(chosen)
        vals = {}
        for party, i in cols.items():
            i2 = i - gap
            if 0 <= i2 < len(chosen):
                v = pct(chosen[i2])
                if v is not None:
                    vals[party] = v
        # at least a clean two-way matchup: multi-candidate jungle races and
        # primary-era fragments leave most of the vote to other columns
        if len(vals) < 2 or not (75.0 <= sum(vals.values()) <= 100.0):
            continue
        out = {key_of(k): round(v, 1) for k, v in vals.items()}
        out["source"] = "Aggregate (Wikipedia)"
        best = out
    return best


def parse_direct(soup, tables=None):
    """Average of the latest 5 polls of the most current matchup table.

    Wikipedia articles can hold several tables (a stale Democrat-vs-
    Republican one plus the current Republican-vs-Independent one, e.g.
    South Dakota and Alaska); the table whose newest poll is the most recent
    wins, and the 5 newest polls by date are averaged.
    """
    best = None
    for tbl in (tables if tables is not None
                else soup.find_all("table", class_="wikitable")):
        rows = tbl.find_all("tr")
        if len(rows) < 4:
            continue
        header = [c.get_text(" ", strip=True).replace("\u200b", "")
                  for c in rows[0].find_all(["th", "td"])]
        cols = party_cols(header, rows)
        if cols is None:
            continue
        found = []
        for row in rows[1:]:
            cells = [c.get_text(" ", strip=True)
                     for c in row.find_all(["th", "td"])]
            if not cells or not cells[0] or cells[0].lower() in ("average", ""):
                continue
            vals = {}
            for party, i in cols.items():
                if i < len(cells):
                    v = pct(cells[i])
                    if v is not None:
                        vals[party] = v
            if len(vals) < 2 or sum(vals.values()) < 75:
                continue
            found.append((vals, cells[1] if len(cells) > 1 else "",
                          sponsor_of(cells[0])))
        if len(found) < 3:
            continue
        last = sorted(found, key=lambda x: date_key(x[1]))[-5:]
        # Sponsored (partisan) polls enter the average at equal weight.
        # The 2022 + 2024 backtests measured their house effect vs neutral
        # polls and found no stable direction (2022: D-sponsored +4.2 D,
        # R-sponsored +1.8 D; 2024: D-sponsored -1.3, R-sponsored -6.9 R)
        # and comparable absolute errors (better in 2024) - hard exclusion
        # or a 0.5x downweight both cost winner accuracy (2024 polled races
        # 87% -> 77%), so the honest treatment is recording and showing the
        # sponsorship, not correcting it.
        out = {}
        for party in ("D", "R", "I"):
            vs = [x[0][party] for x in last if party in x[0]]
            if vs:
                out[key_of(party)] = round(sum(vs) / len(vs), 1)
        out["source"] = "Simple avg (latest 5 polls)"
        out["n_polls"] = len(last)
        n_spon = sum(1 for x in last if x[2])
        if n_spon:
            out["n_sponsored"] = n_spon
        key = (date_key(last[-1][1]), len(found))
        if best is None or key > best[0]:
            best = (key, out)
    return best[1] if best else None


def parse_individual(soup, tables=None):
    """Individual polls from the most current matchup table (newest poll
    date wins, same rule as parse_direct), newest polls first."""
    best = None
    for tbl in (tables if tables is not None
                else soup.find_all("table", class_="wikitable")):
        rows = tbl.find_all("tr")
        if len(rows) < 4:
            continue
        header = [c.get_text(" ", strip=True).replace("\u200b", "")
                  for c in rows[0].find_all(["th", "td"])]
        cols = party_cols(header, rows)
        if cols is None:
            continue
        out = []
        for row in rows[1:]:
            cells = [c.get_text(" ", strip=True)
                     for c in row.find_all(["th", "td"])]
            if not cells:
                continue
            partisan = sponsor_of(cells[0])
            pollster = clean_name(cells[0].replace("(D)", "")
                                  .replace("(R)", "").replace("(I)", ""))
            dates = cells[1] if len(cells) > 1 else ""
            vals = {}
            for party, i in cols.items():
                if i < len(cells):
                    v = pct(cells[i])
                    if v is not None:
                        vals[party] = v
            if (len(vals) < 2 or sum(vals.values()) < 75 or not pollster
                    or pollster.lower() in ("average", "")):
                continue
            # skip aggregate tables and sample-size continuation rows
            if (
                "aggregation" in pollster.lower()
                or "through" in dates.lower()
                or "average" in pollster.lower()
                or re.search(r"\b(LV|RV|PV|±)\b", pollster)
                or pollster[0].isdigit()
                or pollster.startswith("1,")
            ):
                continue
            entry = {"pollster": pollster, "dates": dates}
            if partisan:
                entry["partisan"] = partisan
            entry.update({key_of(k): round(v, 1) for k, v in vals.items()})
            out.append(entry)
        if len(out) < 3:
            continue
        out.sort(key=lambda e: date_key(e["dates"]), reverse=True)
        key = (date_key(out[0]["dates"]), len(out))
        if best is None or key > best[0]:
            best = (key, out)
    return best[1] if best else []


def scrape_race(chamber, race, url):
    soup = fetch(url)
    if soup is None:
        return None
    agg = parse_aggregate(soup)
    ind = parse_individual(soup)
    res = agg or parse_direct(soup)
    if res is None:
        return None
    if ind:
        res["polls"] = ind
    names = nominees(soup)
    if names:
        res["names"] = names
    return res


def race_url(chamber, race):
    key = race["state"].replace(" ", "_")
    if chamber == "senate":
        tmpl = RACE_ID_MAP.get(key.split("_")[0])
        return "https://en.wikipedia.org/wiki/" + (
            tmpl or "2026_United_States_Senate_election_in_" + key)
    return ("https://en.wikipedia.org/wiki/2026_" + key
            + "_gubernatorial_election")


def header_names(tables):
    """Candidate names per party from the first qualifying table's header.

    The main-candidate column per party is chosen the same way party_cols
    does, so a multi-candidate header maps to the right names.
    """
    for tbl in tables:
        rows = tbl.find_all("tr")
        if len(rows) < 4:
            continue
        header = [c.get_text(" ", strip=True).replace("\u200b", "")
                  for c in rows[0].find_all(["th", "td"])]
        cols = party_cols(header, rows)
        if cols is None:
            continue
        out = {}
        for party, i in cols.items():
            nm = clean_name(re.sub(r"\s*\((D|R|I)\)\s*$", "", header[i]))
            if nm:
                out[party.lower()] = nm
        if out:
            return out
    return {}


def scrape_house_states():
    """District polling from every state's 2026 House article.

    Walks the document in order, tracking the current 'District N' heading,
    and parses each district's matchup tables with the same newest-table
    logic as the Senate/Governor races. Only districts with at least three
    clean two-way/three-way polls produce an entry.
    """
    base = json.loads((OUTPUT_DIR / "races.json").read_text(encoding="utf-8"))
    states = sorted({r["state"] for r in base["races"]["house"]})
    results = {}
    for state in states:
        key = state.replace(" ", "_")
        kind = "election" if state in SINGLE_DISTRICT else "elections"
        url = ("https://en.wikipedia.org/wiki/2026_United_States_House_of_"
               "Representatives_%s_in_%s" % (kind, key))
        soup = fetch(url)
        if soup is None:
            print("  %-14s no article" % state)
            continue
        by_district = {}
        # single-district states have no "District N" heading: the whole
        # article is the at-large race (Alaska, Delaware, ...)
        cur = "at-large" if state in SINGLE_DISTRICT else None
        for el in soup.find_all(["h2", "h3", "h4", "table"]):
            if el.name != "table":
                txt = el.get_text(" ", strip=True)
                m = re.match(r"District\s+(\d+)", txt, re.I)
                if m:
                    cur = m.group(1)
                elif re.match(r"At[\s\u2011-]*large", txt, re.I):
                    cur = "at-large"
                continue
            if cur is None or "wikitable" not in (el.get("class") or []):
                continue
            by_district.setdefault(cur, []).append(el)
        found = 0
        for dist, tbls in by_district.items():
            entry = parse_direct(soup, tbls)
            if entry is None:
                continue
            ind = parse_individual(soup, tbls)
            if ind:
                entry["polls"] = ind
            names = header_names(tbls)
            if names:
                entry["names"] = names
            label = "%s %s" % (state, dist)
            results[label] = entry
            found += 1
        print("  %-14s districts with polls: %d" % (state, found))
    return results


def scrape_races(chamber):
    base = json.loads((OUTPUT_DIR / "races.json").read_text(encoding="utf-8"))
    results = {}
    for race in base["races"][chamber]:
        label = race["state"].replace("_", " ")
        res = scrape_race(chamber, race, race_url(chamber, race))
        results[label] = res
        print(f"  {label}: {res}")
    return results


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Senate...")
    senate = scrape_races("senate")
    print("Governor...")
    governor = scrape_races("governor")
    print("House (per-state district polling)...")
    house = scrape_house_states()
    out = {
        "scraped_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "senate": senate,
        "governor": governor,
        "house": house,
    }
    out_file = OUTPUT_DIR / "polling.json"
    out_file.write_text(json.dumps(out, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    print(f"Wrote {out_file}")


if __name__ == "__main__":
    main()
