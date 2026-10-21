#!/usr/bin/env python3
"""Build the state-legislative lean component.

Uses the lower chamber (STATE HOUSE) general-election results from the
NickCrews/election-data parquet release, 2018/2020/2022. For each state and
year, the lean is the two-party vote margin across contested districts minus
the national contested-district margin. Uncontested seats are excluded; a
state needs at least five contested seats.

Requires pyarrow (pip install pyarrow). The 143 MB source parquet is cached in
scraper/.cache/election_data_cleaned.parquet.

Writes data/us/state_legislative.json.
Run: python scraper/us_build_state_leg.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "scraper" / ".cache"
SOURCE = CACHE / "election_data_cleaned.parquet"
OUT = ROOT / "data" / "us" / "state_legislative.json"
URL = ("https://github.com/NickCrews/election-data/releases/download/"
       "v2024-08-29_0/cleaned.parquet")
YEARS = (2018, 2020, 2022)
MIN_SEATS = 5

sys.path.insert(0, str(ROOT / "scraper"))
import us_build_pres_cd as bpc


def ensure_source():
    if SOURCE.is_file():
        return
    import requests
    print("downloading", URL)
    with requests.get(URL, stream=True, timeout=300) as r:
        r.raise_for_status()
        SOURCE.parent.mkdir(parents=True, exist_ok=True)
        with SOURCE.open("wb") as fh:
            for chunk in r.iter_content(chunk_size=1 << 20):
                fh.write(chunk)


def build():
    import pyarrow.dataset as ds
    import pandas as pd

    ensure_source()
    dataset = ds.dataset(str(SOURCE), format="parquet")
    filt = (
        ds.field("year").isin(list(YEARS))
        & (ds.field("office") == "STATE HOUSE")
        & (ds.field("stage") == "GEN")
        & (ds.field("special") == False)
    )
    table = dataset.to_table(
        columns=["year", "state_po", "district", "party_simplified", "votes"],
        filter=filt)
    df = table.to_pandas()
    df["votes"] = pd.to_numeric(df["votes"], errors="coerce").fillna(0.0)
    df = df[df["party_simplified"].isin(["DEMOCRAT", "REPUBLICAN"])]
    by_seat = df.groupby(
        ["year", "state_po", "district", "party_simplified"],
        as_index=False)["votes"].sum()
    wide = by_seat.pivot_table(
        index=["year", "state_po", "district"],
        columns="party_simplified", values="votes", fill_value=0.0).reset_index()
    wide.columns.name = None
    wide["contested"] = (wide.get("DEMOCRAT", 0) > 0) & (
        wide.get("REPUBLICAN", 0) > 0)
    wide = wide[wide["contested"]].copy()
    wide["margin"] = ((wide["DEMOCRAT"] - wide["REPUBLICAN"])
                      / (wide["DEMOCRAT"] + wide["REPUBLICAN"]) * 100.0)
    agg = wide.groupby(["year", "state_po"]).agg(
        d=("DEMOCRAT", "sum"), r=("REPUBLICAN", "sum"),
        seats=("district", "count")).reset_index()
    agg["margin"] = (agg.d - agg.r) / (agg.d + agg.r) * 100.0
    agg = agg[agg.seats >= MIN_SEATS].copy()
    national = {}
    for year in YEARS:
        sel = agg[agg.year == year]
        national[str(year)] = round(
            (sel.d.sum() - sel.r.sum()) / (sel.d.sum() + sel.r.sum()) * 100.0, 2)
    agg["lean"] = agg.margin - agg.year.map(
        {int(y): v for y, v in national.items()})
    states = {}
    for full in bpc.STATE.values():
        rows = agg[agg.state_po.map(bpc.STATE) == full]
        if rows.empty:
            continue
        entry = {}
        for year in YEARS:
            hit = rows[rows.year == year]
            if not hit.empty:
                entry[str(year)] = {
                    "lean": round(float(hit.iloc[0].lean), 2),
                    "seats": int(hit.iloc[0].seats),
                }
        if entry:
            states[full] = entry
    return {
        "source": "NickCrews/election-data, STATE HOUSE general elections",
        "method": ("contested lower-chamber two-party vote margin minus the "
                   "national contested-district margin; uncontested seats "
                   "excluded; states need >=%d contested seats" % MIN_SEATS),
        "years": list(YEARS),
        "national_margin": national,
        "states": states,
    }


def main():
    out = build()
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False),
                   encoding="utf-8")
    print("national", out["national_margin"],
          "| states", len(out["states"]),
          "| years", {y: sum(1 for s in out["states"].values() if str(y) in s)
                      for y in YEARS})
    print("wrote", OUT)


if __name__ == "__main__":
    main()
