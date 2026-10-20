#!/usr/bin/env python3
"""Backtest the US midterms model against the 2024 Senate election.

Replays the model's real pipeline — fundamentals prior (PVI + last result +
track-record-scaled personal vote), the consensus rating band, the poll blend
and the environment mean — on the 33 races of the 2024 cycle, using only what
was knowable then, then scores the predictions against the actual two-party
results: winner accuracy, margin MAE, Brier score and calibration bins.

Inputs:
  * the 2024 Senate article's "Predictions" table (PVI, incumbent, last
    election, Cook/IE/Sabato ratings) — same layout as 2026, so the live
    races scraper is reused with its URL swapped;
  * each state article's poll tables via the live polls parsers;
  * each state article's results table (Party | Candidate | Votes | %), the
    top two parties give the actual two-party margin.

The environment (generic ballot) is the final 2024 average, D+1.0.

Usage:
  python scraper/us_backtest.py            # score the current constants
  python scraper/us_backtest.py --sweep    # coarse constant sweep
"""
import argparse
import math
import os
import re
import sys

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(__file__))
import us_scrape_model as m
import us_scrape_polls as p
import us_scrape_races as r

H = {"User-Agent": "600-us-midterms/1.0"}
CYCLES = {
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
    by_state = {}
    for race in races:
        race["_actual"] = actuals.get(
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


def predict(race, chamber="senate", env=ENV_2024):
    """The model's expected D-minus-R margin and D win probability."""
    polls = race.get("_polls")
    margin = m.final_margin(race, polls, chamber)
    rated = m.consensus_band(race.get("ratings")) is not None
    mu = (m.ENV_WEIGHT[chamber] if rated
          else m.UNRATED_ENV_WEIGHT[chamber]) * env
    margin += mu
    p_win = 1.0 / (1.0 + math.exp(-margin / m.LOGISTIC_BETA[chamber]))
    return margin, p_win


def score(races, label="", chamber="senate", env=ENV_2024):
    n = win = 0
    mae = brier = 0.0
    bins = [(0.5, 0.6), (0.6, 0.7), (0.7, 0.85), (0.85, 1.01)]
    bin_stat = {b: [0, 0] for b in bins}
    for race in races:
        actual = race.get("_actual")
        if actual is None:
            continue
        margin, p_win = predict(race, chamber, env)
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


def sweep(races, chamber="senate", env=ENV_2024):
    """Coarse grid over the tunable constants."""
    base_consts = (m.POLL_WEIGHT, m.ENV_WEIGHT[chamber],
                   m.UNRATED_ENV_WEIGHT[chamber], m.INC_BONUS,
                   m.LOGISTIC_BETA[chamber])
    results = []
    for pw in (0.0, 0.35, 0.5, 0.65, 0.8, 1.0):
        for ew in (0.0, 0.25, 0.5, 1.0):
            for ib in (0.0, 1.5, 2.5):
                for beta in (3.5, 4.0, 4.5, 5.0):
                    m.POLL_WEIGHT = pw
                    m.ENV_WEIGHT[chamber] = ew
                    m.UNRATED_ENV_WEIGHT[chamber] = ew
                    m.INC_BONUS = ib
                    m.LOGISTIC_BETA[chamber] = beta
                    n = win = 0
                    mae = brier = 0.0
                    for race in races:
                        if race.get("_actual") is None:
                            continue
                        margin, p_win = predict(race, chamber, env)
                        n += 1
                        mae += abs(margin - race["_actual"])
                        dem_won = 1.0 if race["_actual"] > 0 else 0.0
                        brier += (p_win - dem_won) ** 2
                        win += 1 if (margin > 0) == (dem_won == 1.0) else 0
                    results.append((brier / n, mae / n, win, n, pw, ew, ib, beta))
    # restore
    (m.POLL_WEIGHT, m.ENV_WEIGHT[chamber], m.UNRATED_ENV_WEIGHT[chamber],
     m.INC_BONUS, m.LOGISTIC_BETA[chamber]) = base_consts
    results.sort()
    print("\n== sweep %s (best by Brier; check sensitivity, do not overfit)" % chamber)
    print("Brier   MAE   wins     poll_w env_w inc_b beta")
    for row in results[:12]:
        print("%.4f  %.2f  %d/%d   %.2f   %.2f  %.1f   %.1f" %
              (row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7]))
    base = [x for x in results
            if (x[4], x[5], x[6], x[7]) == (0.65, 0.25, 1.5, 4.0)]
    if base:
        b = base[0]
        print("current constants: Brier %.4f, MAE %.2f, wins %d/%d" %
              (b[0], b[1], b[2], b[3]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chamber", default="senate", choices=("senate", "house"))
    ap.add_argument("--cycle", type=int, default=2024, choices=(2022, 2024))
    ap.add_argument("--sweep", action="store_true")
    args = ap.parse_args()
    if args.chamber == "house":
        print("loading %d House races (50 state articles)..." % args.cycle)
        races, env = load_house(args.cycle)
    else:
        print("loading %d Senate races..." % args.cycle)
        races = load_races(args.cycle)
        env = CYCLES[args.cycle]["env_fallback"]
    print("environment (generic ballot, D-R points): %s" % env)
    with_polls = sum(1 for x in races if x.get("_polls"))
    print("races: %d | with polls: %d | with actual: %d" %
          (len(races), with_polls,
           sum(1 for x in races if x.get("_actual") is not None)))
    ch = args.chamber
    score(races, "all:", ch, env)
    score([x for x in races if x.get("_polls")], "polled:", ch, env)
    score([x for x in races if not x.get("_polls")], "unpolled:", ch, env)
    if args.sweep:
        sweep(races, ch, env)


if __name__ == "__main__":
    main()
