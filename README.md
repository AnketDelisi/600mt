# 600mt — 2026 U.S. Midterms

The 600 midterms model, on its own street: a race-by-race forecast for the
**Senate, House and governorships** — and a map you can paint yourself.

- **Forecast** (`index.html`) — win probabilities, expected seats, seat
  distributions, and every race with its polling. Senate races start from the
  state's presidential lean, the national environment (scaled by the state's
  historical elasticity), incumbency and trend; House races use the district's
  last presidential margin, the last House result and the rating band;
  governors use the state's last presidential lean, the rating band and
  incumbency. Polls are rebuilt from the individual surveys with
  recency/partisan/sample-size/population weights, a per-firm flood cap,
  strong pollster house effects and an outlier guard, then blended, and a
  correlated national/region/state Monte Carlo with a cycle poll-bias term
  produces the seat distribution.
- **Map builder** (`map.html`) — a YAPMS-style painter: pick a shade, click
  districts/senate seats/governorships, watch the tally. Load the 600
  forecast as a starting point, undo, share the map by link, export a PNG.

Live at <https://anketdelisi.github.io/600mt/>.

## Data pipeline

```
data/us/races.json      # races, ratings, PVI, incumbents, current composition
data/us/polling.json    # per-race polling averages (senate, governor)
data/us/state_swing.json # state presidential margins 2008-24, elasticity, trend
data/us/pres_by_cd.json # district presidential margins (2026/2024/2022 lines)
data/us/pollster_effects.json # shrunk pollster house effects (2018-22 fit)
data/us/state_legislative.json # lower-chamber state leans, 2018-22
data/us/state_elasticity.json  # Silver Bulletin/CCES elasticity scores
data/us/forecast.json   # model output: probabilities, distributions, maps of races
data/us/geo.json        # pre-projected states + 435 districts (Census TIGERweb, 2026 vintage)
```

Daily refresh (also via GitHub Actions, 07:00 UTC):

```bash
pip install -r scraper/requirements.txt
python scraper/us_scrape_races.py
python scraper/us_scrape_polls.py
python scraper/us_scrape_model.py
```

`scraper/us_build_geo.py` rebuilds the boundaries (only needed when the
districts change). `scraper/us_build_swing.py` rebuilds the static state
swing data (county presidential results 2008-24); `scraper/us_build_pres_cd.py`
rebuilds the district presidential lookup from The Downballot's tables.
`scraper/us_calibrate.py` scores the Senate model on the cached 2018-24
backtest (and `--grid` / `--diag`); `scraper/us_calibrate_house.py` scores the
House model on 2018-24; `scraper/us_calibrate_governor.py` scores the governor
model on 2018-24. Grid selection uses 2018-2022 only; 2024 is the holdout.
`scraper/us_seat_report.py` reports expected vs actual seats by cycle.
`scraper/us_build_poll_effects.py` refits the shrunk pollster house effects
from the 2018-22 snapshots. `scraper/us_build_state_leg.py` builds the
2018-22 lower-chamber leans (requires `pyarrow`); `scraper/us_build_elasticity.py`
fetches the Silver Bulletin/CCES scores; `scraper/us_house_seat_calibration.py`
replays historical House seat distributions. `scraper/us_backtest.py` replays
a live cycle (`--chamber senate|house|governor --cycle 2022|2024`).

Backtest caches are gitignored; rebuild them with:

```bash
python scraper/us_bt_snapshot.py 2018 2020 2022 2024
python scraper/us_bt_actuals.py 2018 2020 2022 2024
python scraper/us_bt_house_snapshot.py 2018 2020 2022 2024
python scraper/us_bt_governor_snapshot.py 2018 2020 2022 2024
```

## Notes

- The state-legislative lean and Silver/CCES elasticity inputs are built and
  tested but are not in the live model: neither improved the 2024 holdout.
  The 2020 House result remains outside the model's 90% seat interval.
- Sources: Wikipedia (2026 Senate / House / gubernatorial election and
  ratings articles), The Downballot's district presidential results,
  generic-ballot aggregates, Elections sources linked in the articles.
- The forecast is a model, not a prophecy. The map is yours.
- Sibling site: [600](https://anketdelisi.github.io/600/) — 43 country
  election models.
