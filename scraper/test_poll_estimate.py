#!/usr/bin/env python3
"""Check that individual polls win over an aggregate, and the aggregate is
only a fallback. Run: python scraper/test_poll_estimate.py
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import us_scrape_model as m

ASOF = date(2024, 11, 5)
POLLS = [
    {"pollster": "A", "dates": "November 1, 2024", "dem": 50.0, "rep": 50.0},
    {"pollster": "B", "dates": "October 30, 2024", "dem": 50.0, "rep": 50.0},
    {"pollster": "C", "dates": "October 25, 2024", "dem": 50.0, "rep": 50.0},
]


def main():
    with_polls = {"dem": 60.0, "rep": 40.0, "source": "Aggregate (Wikipedia)",
                  "polls": POLLS}
    detail = m.poll_estimate_detail(with_polls, ASOF)
    assert detail is not None
    assert detail[3] == "direct", detail
    assert abs(detail[0]) < 0.01, detail

    aggregate_only = {"dem": 60.0, "rep": 40.0,
                      "source": "Aggregate (Wikipedia)"}
    detail = m.poll_estimate_detail(aggregate_only, ASOF)
    assert detail is not None and detail[3] == "aggregate", detail
    assert abs(detail[0] - 20.0) < 0.01, detail

    stale = {"dem": 60.0, "rep": 40.0, "source": "Aggregate (Wikipedia)",
             "polls": [{"pollster": "A", "dates": "November 1, 2018",
                        "dem": 90.0, "rep": 10.0}]}
    detail = m.poll_estimate_detail(stale, ASOF)
    assert detail is not None and detail[3] == "aggregate", detail

    capped = {"polls": [
        {"pollster": "A", "dates": "November 1, 2024", "dem": 50.0, "rep": 50.0},
        {"pollster": "A", "dates": "October 31, 2024", "dem": 50.0, "rep": 50.0},
        {"pollster": "A", "dates": "October 30, 2024", "dem": 50.0, "rep": 50.0},
        {"pollster": "B", "dates": "November 1, 2024", "dem": 55.0, "rep": 45.0},
    ]}
    detail = m.poll_estimate_detail(capped, ASOF, {"pollster_cap": 0.5})
    assert detail is not None and detail[3] == "direct", detail
    assert abs(detail[0] - 10.0 / 3.0) < 0.01, detail

    weighted = {"polls": [
        {"pollster": "A", "dates": "November 1, 2024", "dem": 50.0,
         "rep": 50.0, "sample": 100},
        {"pollster": "B", "dates": "November 1, 2024", "dem": 52.5,
         "rep": 47.5, "sample": 1200},
    ]}
    detail = m.poll_estimate_detail(weighted, ASOF,
                                   {"pollster_cap": 1.0, "sample_power": 0.25})
    assert detail is not None and detail[3] == "direct", detail
    assert 3.2 < detail[0] < 3.3, detail

    population = {"polls": [
        {"pollster": "A", "dates": "November 1, 2024", "dem": 50.0,
         "rep": 50.0, "sample": 600, "population": "LV"},
        {"pollster": "B", "dates": "November 1, 2024", "dem": 52.5,
         "rep": 47.5, "sample": 600, "population": "A"},
    ]}
    detail = m.poll_estimate_detail(population, ASOF,
                                   {"pollster_cap": 1.0, "sample_power": 0.0})
    assert detail is not None and detail[3] == "direct", detail
    assert abs(detail[0] - 5.0 * 0.75 / 1.75) < 0.01, detail
    print("poll estimator ok")


if __name__ == "__main__":
    main()
