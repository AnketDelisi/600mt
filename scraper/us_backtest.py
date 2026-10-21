#!/usr/bin/env python3
"""Backtest the US midterms model against past Senate, House and governor
cycles.

Replays the model's real pipeline on the races of a cycle, using only what
was knowable then, then scores the predictions against the actual two-party
results: winner accuracy, margin MAE, Brier score and calibration bins.

Usage:
  python scraper/us_backtest.py --chamber senate --cycle 2024
  python scraper/us_backtest.py --chamber house --cycle 2022
  python scraper/us_backtest.py --chamber governor --cycle 2022
  python scraper/us_calibrate.py --grid    # cached Senate parameter grid
  python scraper/us_calibrate_house.py --grid  # cached House grid
"""
import argparse
import math
import os
import re
import sys
from datetime import date

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(__file__))
import us_scrape_model as m
import us_scrape_polls as p
import us_scrape_races as r

H = {"User-Agent": "600-us-midterms/1.0"}
CYCLES = {
    2018: {
        "senate": "https://en.wikipedia.org/wiki/"
                  "2018_United_States_Senate_elections",
        "house": "https://en.wikipedia.org/wiki/"
                 "2018_United_States_House_of_Representatives_elections",
        "ratings": "https://en.wikipedia.org/wiki/2018_United_States_House_"
                   "of_Representatives_election_ratings",
        "env_fallback": 8.5,    # final 2018 generic ballot, D+8.5
    },
    2020: {
        "senate": "https://en.wikipedia.org/wiki/"
                  "2020_United_States_Senate_elections",
        "house": "https://en.wikipedia.org/wiki/"
                 "2020_United_States_House_of_Representatives_elections",
        "ratings": "https://en.wikipedia.org/wiki/2020_United_States_House_"
                   "of_Representatives_election_ratings",
        "env_fallback": 6.8,    # final 2020 generic ballot, D+6.8
    },
    2022: {
        "senate": "https://en.wikipedia.org/wiki/"
                  "2022_United_States_Senate_elections",
        "house": "https://en.wikipedia.org/wiki/"
                 "2022_United_States_House_of_Representatives_elections",
        "ratings": "https://en.wikipedia.org/wiki/2022_United_States_House_"
                   "of_Representatives_election_ratings",
        "env_fallback": -1.0,   # final 2022 generic ballot, R+1.0
    },
    2024: {
        "senate": "https://en.wikipedia.org/wiki/"
                  "2024_United_States_Senate_elections",
        "house": "https://en.wikipedia.org/wiki/"
                 "2024_United_States_House_of_Representatives_elections",
        "ratings": "https://en.wikipedia.org/wiki/2024_United_States_House_"
                   "of_Representatives_election_ratings",
        "env_fallback": -0.1,   # final 2024 generic ballot, R+0.1
    },
}
ENV_2024 = -0.1   # default env when none is passed


def get(url):
    resp = requests.get(url, headers=H, timeout=60)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "lxml")


def actual_margin(soup):
    """Two-party-normalized D-minus-R margin from the results table.

    The party sits in cell 1 and the share in cell 4 ("52.64%" in some
    articles, bare "55.83" in others); fusion lines (Working Families) are
    ignored so the Democratic/Republican lines carry the margin. County
    tables are skipped because their cell 1 is a candidate name, not a
    party.
    """
    for tbl in soup.find_all("table", class_="wikitable"):
        txt = tbl.get_text(" ", strip=True)
        if "Democratic" not in txt or "Republican" not in txt:
            continue
        by_party = {}
        rows_with = 0
        for row in tbl.find_all("tr"):
            cells = [c.get_text(" ", strip=True)
                     for c in row.find_all(["th", "td"])]
            if len(cells) < 5:
                continue
            party = cells[1].lower()
            m2 = re.match(r"([\d.]+)\s*%?", cells[4])
            if not m2:
                continue
            if party.startswith("republic"):
                by_party["R"] = by_party.get("R", 0) + float(m2.group(1))
                rows_with += 1
            elif party.startswith("democrat"):
                by_party["D"] = by_party.get("D", 0) + float(m2.group(1))
                rows_with += 1
        if (rows_with >= 2 and "D" in by_party and "R" in by_party
                and by_party["D"] + by_party["R"] > 50):
            tot = by_party["D"] + by_party["R"]
            return (by_party["D"] - by_party["R"]) / tot * 100
    return None


def generic_ballot(soup):
    """Mean (D - R) margin from the 'Polling aggregates' table."""
    vals = []
    for tbl in soup.find_all("table", class_="wikitable"):
        rows = tbl.find_all("tr")
        hdr = di = ri = None
        for row in rows[:4]:   # the table has a title row before the header
            cells = [c.get_text(" ", strip=True)
                     for c in row.find_all(["th", "td"])]
            d = next((i for i, h in enumerate(cells)
                      if h.startswith("Democrat")), None)
            r = next((i for i, h in enumerate(cells)
                      if h.startswith("Republic")), None)
            if d is not None and r is not None:
                hdr, di, ri = row, d, r
                break
        if hdr is None:
            continue
        for row in rows[rows.index(hdr) + 1:]:
            cells = [c.get_text(" ", strip=True)
                     for c in row.find_all(["th", "td"])]
            if len(cells) <= max(di, ri):
                continue
            md = re.match(r"([\d.]+)\s*%?", cells[di])
            mr = re.match(r"([\d.]+)\s*%?", cells[ri])
            if md and mr:
                vals.append(float(md.group(1)) - float(mr.group(1)))
    return round(sum(vals) / len(vals), 1) if vals else None


def district_tables(soup):
    """{district_label: [tables]} by walking 'District N'/'At-large' headings."""
    out = {}
    cur = None
    for el in soup.find_all(["h2", "h3", "h4", "table"]):
        if el.name != "table":
            txt = el.get_text(" ", strip=True)
            m = re.match(r"District\s+(\d+)", txt, re.I)
            if m:
                cur = m.group(1)
            elif re.match(r"At[\s\u2011-]*large", txt, re.I):
                cur = "at-large"
            continue
        if cur is not None and "wikitable" in (el.get("class") or []):
            out.setdefault(cur, []).append(el)
    return out


def national_actuals(soup):
    """{state + ' ' + district: two-party margin} from a past cycle's
    national House article, whose result cells read
    '▌ Y Jerry Carl (Republican) 84.2% ▌ Alexander Remrey (Libertarian)
    15.8%'; Alaska-style RCV races use the Instant-runoff segment."""
    out = {}
    for tbl in soup.find_all("table", class_="wikitable"):
        for row in tbl.find_all("tr"):
            th = row.find("th")
            if not th:
                continue
            m = re.match(r"^([A-Za-z .']+?)(\d+|at-large)$",
                         th.get_text(strip=True))
            if not m:
                continue
            cells = [c.get_text(" ", strip=True)
                     for c in row.find_all("td")]
            if not cells:
                continue
            result = cells[-1]
            if "Instant runoff:" in result:
                result = result.split("Instant runoff:")[-1]
            d = rr = None
            for mm in re.finditer(r"\(([^)]+)\)\s*([\d.]+)%", result):
                party, pct = mm.group(1).lower(), float(mm.group(2))
                if party.startswith("democrat"):
                    d = (d or 0) + pct
                elif party.startswith("republic"):
                    rr = (rr or 0) + pct
            if d and rr and d + rr > 50:
                out[m.group(1).strip().title() + " " + m.group(2)] = \
                    (d - rr) / (d + rr) * 100
    return out


def load_house(cycle=2024):
    """House races with district polls and actual results.

    Polls come from the per-state articles (same parsers as the live
    scraper); the actual two-party results come from the national article's
    result cells, which exist for past cycles.
    """
    r.WIKI["house"] = CYCLES[cycle]["house"]
    r.WIKI["house_ratings"] = CYCLES[cycle]["ratings"]
    races = r.scrape_house()
    ratings_soup = get(CYCLES[cycle]["ratings"])
    env = generic_ballot(ratings_soup)
    if env is None:
        env = CYCLES[cycle]["env_fallback"]
    actuals = national_actuals(get(CYCLES[cycle]["house"]))
    pres_map = m.PRES_BY_CD.get(str(cycle)) or {}
    by_state = {}
    for race in races:
        race["_actual"] = actuals.get(
            race["state"] + " " + str(race.get("district", "")))
        race["pres"] = pres_map.get(
            race["state"] + " " + str(race.get("district", "")))
        by_state.setdefault(race["state"], []).append(race)
    for state, state_races in by_state.items():
        key = state.replace(" ", "_")
        kind = ("election" if state in p.SINGLE_DISTRICT else "elections")
        url = ("https://en.wikipedia.org/wiki/%d_United_States_House_of_"
               "Representatives_%s_in_%s" % (cycle, kind, key))
        try:
            soup = get(url)
        except Exception:
            continue
        dt = district_tables(soup)
        for race in state_races:
            dist = str(race.get("district", ""))
            tbls = dt.get(dist)
            if not tbls:
                continue
            polls = p.parse_direct(soup, tbls)
            if polls:
                ind = p.parse_individual(soup, tbls)
                if ind:
                    polls["polls"] = ind
                names = p.header_names(tbls)
                if names:
                    polls["names"] = names
            race["_polls"] = polls
    return races, env


def load_governors(cycle=2022):
    """Governor races of a cycle with polls and actual results."""
    url = ("https://en.wikipedia.org/wiki/%d_United_States_gubernatorial_"
           "elections" % cycle)
    soup = get(url)
    tbl = None
    for t in soup.find_all("table", class_="wikitable"):
        rows = t.find_all("tr")
        hdr = None
        for row in rows[:3]:
            cells = [c.get_text(" ", strip=True)
                     for c in row.find_all(["th", "td"])]
            if cells and cells[0] == "State" and any(
                    "Cook" in h for h in cells):
                hdr = cells
                break
        if hdr:
            tbl = (t, hdr)
            break
    if tbl is None:
        raise RuntimeError("no governor ratings table in %s" % url)
    table, hdr = tbl
    col = {}
    for i, h in enumerate(hdr):
        hl = h.lower()
        if "pvi" in hl:
            col["pvi"] = i - 1
        elif "incumbent" in hl:
            col["incumbent"] = i - 1
        elif "last" in hl:
            col["last"] = i - 1
        elif "cook" in hl:
            col["cook"] = i - 1
        elif hl.startswith("ie") or "inside" in hl:
            col["ie"] = i - 1
        elif "sabato" in hl:
            col["sabato"] = i - 1
    races = []
    for row in table.find_all("tr"):
        th = row.find("th")
        tds = row.find_all("td")
        if th is None or len(tds) < 8:
            continue
        cells = [c.get_text(strip=True) for c in tds]
        state = re.sub(r"\[.*?\]", "", re.sub(r"\(.*?\)", "", th.get_text(strip=True))).strip().title()
        if not state or state.lower().startswith("overall"):
            continue
        try:
            pvi = r.parse_pvi(cells[col["pvi"]])
        except Exception:
            continue
        incumbent = r.strip_footnote(cells[col["incumbent"]])
        last_res = r.parse_last_result(cells[col["last"]])
        rating = {}
        for k in ("cook", "ie", "sabato"):
            idx = col.get(k)
            if idx is not None and idx < len(cells):
                rating[k] = cells[idx]
        party = last_res["party"] if last_res else None
        if party is None:
            for v in rating.values():
                mm = re.search(r"\b([RD])\b", v)
                if mm:
                    party = mm.group(1)
                    break
        races.append({
            "state": state, "pvi": pvi,
            "pvi_label": cells[col["pvi"]],
            "incumbent": incumbent,
            "inc_status": r.inc_status(incumbent),
            "party": party, "last": last_res, "ratings": rating,
        })
    for race in races:
        state = race["state"].replace(" ", "_")
        surl = ("https://en.wikipedia.org/wiki/%d_%s_"
                "gubernatorial_election" % (cycle, state))
        try:
            rsoup = get(surl)
        except Exception:
            race["_actual"] = None
            race["_polls"] = None
            continue
        race["_actual"] = actual_margin(rsoup)
        try:
            polls = p.scrape_race("governor", race, surl)
        except Exception:
            polls = None
        race["_polls"] = polls
    return races


def load_races(cycle=2024):
    """Senate races of a cycle with polls and actual results."""
    r.WIKI["senate"] = CYCLES[cycle]["senate"]
    races = r.scrape_senate_or_gov("senate")
    out = []
    for race in races:
        # the live scraper's 2026 special-election party override (FL/OH)
        # is not meaningful for past cycles; the last result carries the
        # incumbent's party
        if race.get("last"):
            race["party"] = race["last"]["party"]
        state = race["state"].replace(" ", "_")
        url = ("https://en.wikipedia.org/wiki/%d_United_States_Senate_"
               "election_in_%s" % (cycle, state))
        soup = get(url)
        polls = p.scrape_race("senate", race, url)
        race["_polls"] = polls
        race["_actual"] = actual_margin(soup)
        out.append(race)
    return out


def predict(race, chamber="senate", env=ENV_2024, asof=date(2024, 11, 5)):
    """The model's expected D-minus-R margin and D win probability."""
    polls = race.get("_polls")
    # the backtest cycles are 2022/2024; the honest lean is the 2020
    # presidential result, not the 2024 one the live 2026 model uses
    margin = m.final_margin(race, polls, chamber, env, asof, lean_year="2020")
    p_win = 1.0 / (1.0 + math.exp(-margin / m.LOGISTIC_BETA[chamber]))
    return margin, p_win


def score(races, label="", chamber="senate", env=ENV_2024,
          asof=date(2024, 11, 5)):
    n = win = 0
    mae = brier = 0.0
    bins = [(0.5, 0.6), (0.6, 0.7), (0.7, 0.85), (0.85, 1.01)]
    bin_stat = {b: [0, 0] for b in bins}
    for race in races:
        actual = race.get("_actual")
        if actual is None:
            continue
        margin, p_win = predict(race, chamber, env, asof)
        n += 1
        mae += abs(margin - actual)
        dem_won = 1.0 if actual > 0 else 0.0
        brier += (p_win - dem_won) ** 2
        pred_dem = margin > 0
        win += 1 if pred_dem == (dem_won == 1.0) else 0
        for b in bins:
            if b[0] <= p_win < b[1]:
                bin_stat[b][0] += 1
                bin_stat[b][1] += 1 if dem_won == 1.0 else 0
    print("%s n=%d | winner %d/%d (%.0f%%) | margin MAE %.2f | Brier %.4f" %
          (label, n, win, n, 100.0 * win / max(n, 1), mae / max(n, 1),
           brier / max(n, 1)))
    for b in bins:
        cnt, won = bin_stat[b]
        if cnt:
            print("   p in [%.2f,%.2f): %3d races, %.0f%% Dem wins" %
                  (b[0], b[1], cnt, 100.0 * won / cnt))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chamber", default="senate",
                    choices=("senate", "house", "governor"))
    ap.add_argument("--cycle", type=int, default=2024, choices=(2022, 2024))
    args = ap.parse_args()
    if args.chamber == "house":
        print("loading %d House races (50 state articles)..." % args.cycle)
        races, env = load_house(args.cycle)
    elif args.chamber == "governor":
        print("loading %d governor races..." % args.cycle)
        races = load_governors(args.cycle)
        env = CYCLES[args.cycle]["env_fallback"]
    else:
        print("loading %d Senate races..." % args.cycle)
        races = load_races(args.cycle)
        env = CYCLES[args.cycle]["env_fallback"]
    asof = date(2024, 11, 5) if args.cycle == 2024 else date(2022, 11, 8)
    print("environment (generic ballot, D-R points): %s" % env)
    with_polls = sum(1 for x in races if x.get("_polls"))
    print("races: %d | with polls: %d | with actual: %d" %
          (len(races), with_polls,
           sum(1 for x in races if x.get("_actual") is not None)))
    ch = args.chamber
    score(races, "all:", ch, env, asof)
    score([x for x in races if x.get("_polls")], "polled:", ch, env, asof)
    score([x for x in races if not x.get("_polls")], "unpolled:", ch, env, asof)


if __name__ == "__main__":
    main()
