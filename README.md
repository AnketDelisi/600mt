# 600mt — 2026 U.S. Midterms

The 600 midterms model, on its own street: a race-by-race forecast for the
**Senate, House and governorships** — and a map you can paint yourself.

- **Forecast** (`index.html`) — win probabilities, expected seats, seat
  distributions, and every race with its polling. The model blends district
  partisan lean (PVI + last result), the Cook / Inside Elections / Sabato
  rating band, per-race polling averages and a national-swing Monte Carlo.
- **Map builder** (`map.html`) — a YAPMS-style painter: pick a shade, click
  districts/senate seats/governorships, watch the tally. Load the 600
  forecast as a starting point, undo, share the map by link, export a PNG.

Live at <https://anketdelisi.github.io/600mt/>.

## Data pipeline

```
data/us/races.json      # races, ratings, PVI, incumbents, current composition
data/us/polling.json    # per-race polling averages (senate, governor)
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
districts change); `scraper/us_backtest.py` replays the model on 2024.

## Notes

- Sources: Wikipedia (2026 Senate / House / gubernatorial election and
  ratings articles), generic-ballot aggregates, Elections sources linked in
  the articles.
- The forecast is a model, not a prophecy. The map is yours.
- Sibling site: [600](https://anketdelisi.github.io/600/) — 43 country
  election models.
