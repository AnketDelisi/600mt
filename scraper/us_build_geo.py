#!/usr/bin/env python3
"""Build data/us/geo.json — the pre-projected US map (50 states + 435
congressional districts) used by us/index.html.

Source: Census TIGERweb Legislative MapServer, layer 0 = "120th Congressional
Districts; January 1, 2026 vintage" — the boundaries for the 2026-11-03
election, including the 2025-2026 mid-decade redistricting (Texas, California,
Missouri, North Carolina, Utah, Ohio, Virginia, Florida, Tennessee, Louisiana,
Alabama). The previous geo.json came from an older district vintage built by a
one-off script that was never committed; this rebuild is reproducible.

Projection: Albers equal-area conic for the lower 48, with the classic
Alaska (scaled, bottom-left) and Hawaii (bottom-centre) insets, fitted into
the same 975x610 viewBox the page expects. Output keys match the page:
  {w, h, nation, states:[{id,name,d,box}], districts:[{s,cd,d}]}

Usage: python scraper/us_build_geo.py [--force]
"""
import json
import math
import os
import sys

import requests
from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.ops import unary_union

sys.path.insert(0, os.path.dirname(__file__))
import build_map_svg as bm

ROOT = os.path.join(os.path.dirname(__file__), "..")
CACHE = os.path.join(ROOT, "scraper", ".cache")
OUT = os.path.join(ROOT, "data", "us", "geo.json")

TIGER = ("https://tigerweb.geo.census.gov/arcgis/rest/services/"
         "TIGERweb/Legislative/MapServer/0/query")

# lower-48 / AK / HI target rectangles inside the 975x610 viewBox. Alaska and
# Hawaii are deliberately large (readable at a glance); the shapely overlap
# check at the end of main() fails loudly if a rect grows into the lower-48.
CONUS_RECT = (73.0, 20.0, 975.0, 590.0)
AK_RECT = (0.0, 452.0, 330.0, 600.0)
HI_RECT = (232.0, 458.0, 420.0, 596.0)
# island trimming (deg^2): Alaska's Aleutian chain spans ~359 degrees of
# longitude and Hawaii's northwestern atolls stretch 24 degrees, both of
# which cap the inset scale; parts below these areas are dropped so the
# mainland + major islands fill the insets
ISLAND_MIN_AREA = {"02": 0.5, "15": 0.07}
W, H = 975, 610

FIPS = {
    "01": "Alabama", "02": "Alaska", "04": "Arizona", "05": "Arkansas",
    "06": "California", "08": "Colorado", "09": "Connecticut",
    "10": "Delaware", "12": "Florida", "13": "Georgia", "15": "Hawaii",
    "16": "Idaho", "17": "Illinois", "18": "Indiana", "19": "Iowa",
    "20": "Kansas", "21": "Kentucky", "22": "Louisiana", "23": "Maine",
    "24": "Maryland", "25": "Massachusetts", "26": "Michigan",
    "27": "Minnesota", "28": "Mississippi", "29": "Missouri",
    "30": "Montana", "31": "Nebraska", "32": "Nevada", "33": "New Hampshire",
    "34": "New Jersey", "35": "New Mexico", "36": "New York",
    "37": "North Carolina", "38": "North Dakota", "39": "Ohio",
    "40": "Oklahoma", "41": "Oregon", "42": "Pennsylvania",
    "44": "Rhode Island", "45": "South Carolina", "46": "South Dakota",
    "47": "Tennessee", "48": "Texas", "49": "Utah", "50": "Vermont",
    "51": "Virginia", "53": "Washington", "54": "West Virginia",
    "55": "Wisconsin", "56": "Wyoming",
}
AK_HI = {"02", "15"}


def fetch_state(fips, force):
    path = os.path.join(CACHE, "us_cd_%s.geojson" % fips)
    if force or not os.path.isfile(path):
        r = requests.get(TIGER, params={
            "where": "STATE='%s'" % fips, "outFields": "STATE,BASENAME",
            "returnGeometry": "true", "outSR": "4326", "f": "geojson"},
            headers={"User-Agent": "600-us-midterms/1.0"}, timeout=300)
        r.raise_for_status()
        open(path, "wb").write(r.content)
    return json.loads(open(path, encoding="utf8").read())


def albers(lon, lat, lat1, lat2, lon0):
    """Albers equal-area conic (sphere), lon/lat degrees -> raw x,y."""
    p1, p2, p0 = map(math.radians, (lat1, lat2, 0.0))
    lam, phi = math.radians(lon - lon0), math.radians(lat)
    n = (math.sin(p1) + math.sin(p2)) / 2
    c = math.cos(p1) ** 2 + 2 * n * math.sin(p1)
    rho = math.sqrt(c - 2 * n * math.sin(phi)) / n
    theta = n * lam
    # y positive = north (the textbook conic formula is south-positive; the
    # fit() y-flip below expects north-positive)
    return rho * math.sin(theta), -rho * math.cos(theta)


def fit(points, rect):
    """Uniform-fit a list of raw (x,y) into rect=(x0,y0,x1,y1), y down."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    tw, th = rect[2] - rect[0], rect[3] - rect[1]
    s = min(tw / (x1 - x0 or 1), th / (y1 - y0 or 1))
    ox = rect[0] + (tw - (x1 - x0) * s) / 2 - x0 * s
    oy = rect[1] + (th - (y1 - y0) * s) / 2 + y1 * s
    # flip y (map coordinates have north up; svg y is down)
    return (lambda x, y: (x * s + ox, oy - y * s))


def path_d(rings, eps):
    out = []
    for ring in rings:
        pts = bm.simplify(ring, eps)
        if len(pts) < 3:
            continue
        d = "M" + " ".join("%.1f,%.1f" % p for p in pts) + "Z"
        out.append(d)
    return "".join(out)


def ext_pts(geom):
    """All exterior coordinate tuples of a Polygon/MultiPolygon."""
    if isinstance(geom, Polygon):
        return list(geom.exterior.coords)
    if isinstance(geom, MultiPolygon):
        return [p for poly in geom.geoms for p in poly.exterior.coords]
    return []


def drop_small_parts(geom, thr):
    """Drop polygon parts below thr deg^2 (the Aleutians, NW Hawaiian atolls)."""
    if not thr or geom.geom_type != "MultiPolygon":
        return geom
    keep = [g for g in geom.geoms if g.area >= thr]
    if not keep:
        return geom
    return MultiPolygon(keep) if len(keep) > 1 else keep[0]


def main():
    force = "--force" in sys.argv
    os.makedirs(CACHE, exist_ok=True)

    raw = {}      # fips -> list of (cd, shapely geometry in lon/lat)
    counts = {}
    for fips, name in sorted(FIPS.items()):
        gj = fetch_state(fips, force)
        feats = []
        for f in gj.get("features", []):
            props = f.get("properties", {})
            base = str(props.get("BASENAME") or props.get("CD120") or "").strip()
            if base.isdigit():
                cd = base
            elif "at large" in base.lower():
                # at-large states (AK DE ND SD VT WY): BASENAME is
                # "Congressional District (at Large)" and CD120 is null
                cd = "0"
            else:
                # "Congressional Districts not defined" water/territory
                # features (CT, IL, NH have one each)
                continue
            geom = shape(f["geometry"])
            geom = drop_small_parts(geom, ISLAND_MIN_AREA.get(fips))
            feats.append((cd, geom))
        raw[fips] = feats
        counts[fips] = len(feats)
    total = sum(counts.values())
    print("districts fetched:", total)
    assert total == 435, "expected 435 districts, got %d" % total

    # projection per region: fit the conus first, then transform the insets
    conus_pts = []
    for fips, feats in raw.items():
        if fips in AK_HI:
            continue
        for cd, geom in feats:
            conus_pts.extend([albers(x, y, 29.5, 45.5, -96.0)
                              for x, y in ext_pts(geom)])
    conus_fit = fit(conus_pts, CONUS_RECT)

    def project(fips, x, y):
        if fips == "02":
            return ak_fit(*albers(x, y, 55.0, 65.0, -154.0))
        if fips == "15":
            return hi_fit(*albers(x, y, 8.0, 18.0, -157.0))
        return conus_fit(*albers(x, y, 29.5, 45.5, -96.0))

    # inset fits need the raw projected points first
    ak_pts = [albers(x, y, 55.0, 65.0, -154.0)
              for cd, g in raw["02"] for x, y in ext_pts(g)]
    hi_pts = [albers(x, y, 8.0, 18.0, -157.0)
              for cd, g in raw["15"] for x, y in ext_pts(g)]
    ak_fit = fit(ak_pts, AK_RECT)
    hi_fit = fit(hi_pts, HI_RECT)

    # transform every ring into svg space
    from shapely.geometry import Polygon, MultiPolygon
    from shapely.ops import transform as shp_transform

    def mk_tf(fips):
        return lambda x, y, z=None: project(fips, x, y)

    states = []
    districts = []
    for si, (fips, name) in enumerate(sorted(FIPS.items(), key=lambda kv: kv[1])):
        tf = mk_tf(fips)
        polys = []
        for cd, geom in raw[fips]:
            g2 = shp_transform(tf, geom)
            polys.append(g2)
            rings = ([g2.exterior] if isinstance(g2, Polygon)
                     else [p.exterior for p in g2.geoms]
                     if isinstance(g2, MultiPolygon) else [])
            holes = ([g2.interiors] if isinstance(g2, Polygon)
                     else [p.interiors for p in g2.geoms]
                     if isinstance(g2, MultiPolygon) else [])
            all_rings = [r.coords for r in rings] + \
                [r.coords for hs in holes for r in hs]
            cd_label = "at-large" if cd in ("00", "0") else str(int(cd))
            districts.append({"s": si, "cd": cd_label,
                              "d": path_d(all_rings, 0.15)})
        st = unary_union(polys)
        rings = ([st.exterior] if isinstance(st, Polygon)
                 else [p.exterior for p in st.geoms])
        holes = ([st.interiors] if isinstance(st, Polygon)
                 else [p.interiors for p in st.geoms])
        all_rings = [r.coords for r in rings] + \
            [r.coords for hs in holes for r in hs]
        xs = [p[0] for r in all_rings for p in r]
        ys = [p[1] for r in all_rings for p in r]
        box = [round(min(xs), 1), round(min(ys), 1),
               round(max(xs), 1), round(max(ys), 1)]
        states.append({"id": fips, "name": name,
                       "d": path_d(all_rings, 0.3), "box": box})

    nation = unary_union([shp_transform(mk_tf(f), g)
                          for f, feats in raw.items() for _, g in feats])
    nrings = ([nation.exterior] if isinstance(nation, Polygon)
              else [p.exterior for p in nation.geoms])
    nation_d = path_d([r.coords for r in nrings], 0.4)

    out = {"w": W, "h": H, "nation": nation_d,
           "states": states, "districts": districts}
    with open(OUT, "w", encoding="utf8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    size = os.path.getsize(OUT)
    print("wrote %s | %d states, %d districts | %.0f KB" %
          (OUT, len(states), len(districts), size / 1024))
    # inset safety: the Alaska/Hawaii shapes must not touch the lower-48
    conus_union = unary_union([shp_transform(mk_tf(f), g)
                               for f, feats in raw.items() if f not in AK_HI
                               for _, g in feats])
    for fips, nm2 in (("02", "Alaska"), ("15", "Hawaii")):
        ins = unary_union([shp_transform(mk_tf(fips), g)
                           for _, g in raw[fips]])
        if ins.buffer(1.5).intersects(conus_union):
            print("WARNING: %s inset overlaps the lower-48 - shrink its rect"
                  % nm2)
        else:
            print("  inset %s: no overlap with the lower-48" % nm2)
    for nm in ("Texas", "California", "North Carolina", "Ohio", "Missouri"):
        st = next(s for s in states if s["name"] == nm)
        n = sum(1 for d in districts if states[d["s"]]["name"] == nm)
        print("  %-14s districts=%d box=%s" % (nm, n, st["box"]))
    for nm in ("Alaska", "Hawaii"):
        st = next(s for s in states if s["name"] == nm)
        b = st["box"]
        print("  %-14s box=%s (%.0f x %.0f)" %
              (nm, b, b[2] - b[0], b[3] - b[1]))


if __name__ == "__main__":
    main()
