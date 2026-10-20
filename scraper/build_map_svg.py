"""Build a constituency/district SVG from official boundary data.

Instead of hand-drawing one SVG per country/state, download official
boundaries and emit an SVG whose <path> identifiers match what the site's
map engine expects (js/app.js renderMapInto):

  default selector: path[id^="_"], nr = digits after the underscore
  -> id "_28" is Wahlkreis 28; conf.districts maps nr -> region name.
  selector 'label' -> data-label="<name>" (from inkscape:label)
  selector 'class' -> class="wkNNN"

Two input modes:
  --zip URL --shp inner/name.shp   shapefile archive (any CRS; projected
                                   coordinates are used as-is)
  --geojson URL                    GeoJSON file or geoBoundaries API URL
                                   (auto-resolves simplifiedGeometryGeoJSON,
                                   lon/lat -> Web Mercator)

Identifier conventions:
  --attr id|data-label|class       output attribute (default id)
  --id-prefix "_"                  prefix for id mode
  --class-pattern "wk{n}"          pattern for class mode
  --name-field shapeName           feature property holding the region name
  --name-map names.json            {feature name: output identifier}
  --fold                           fall back to ASCII-folded names

Default target: Landtagswahlkreise Mecklenburg-Vorpommern 2026 (36),
official KLWK250MV shapefile of the LAiV MV Amt fuer Geoinformation,
(c) GeoBasis-DE/M-V, CC BY 4.0.

Usage:
  python scraper/build_map_svg.py
  python scraper/build_map_svg.py --geojson https://www.geoboundaries.org/api/current/gbOpen/AUT/ADM1/ \
      --attr id --fold --out bmv/img/austria.gen.svg
"""
import argparse
import io
import json
import math
import os
import re
import struct
import sys
import urllib.request
import zipfile

ROOT = os.path.join(os.path.dirname(__file__), "..")
CACHE = os.path.join(ROOT, "scraper", ".cache")
DEFAULT_ZIP = ("https://www.laiv-mv.de/static/LAIV/Geoinformation/"
               "Dateien/Karten/LTwahl_Wahlkreise.zip")
DEFAULT_SHP = "LTwahl_Wahlkreise.shp"
DEFAULT_OUT = os.path.join(ROOT, "bmv", "img",
                           "mecklenburg_vorpommern.gen.svg")
ATTRIBUTION = ("Geometrien: (c) GeoBasis-DE/M-V / CC BY 4.0 — "
               "Amt fuer Geoinformation, Vermessungs- und Katasterwesen "
               "(LAiV MV), Sonderausgabe KLWK250MV")


def fetch_bytes(url, filename=None):
    """Download a URL (cached under scraper/.cache when filename given)."""
    path = None
    if filename:
        os.makedirs(CACHE, exist_ok=True)
        path = os.path.join(CACHE, filename)
        if os.path.exists(path):
            return open(path, "rb").read()
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    if path:
        with open(path, "wb") as f:
            f.write(data)
    return data


def extract(zip_path, shp_name):
    out = os.path.join(CACHE, "extract")
    os.makedirs(out, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(out)
    for root, _, files in os.walk(out):
        for fn in files:
            if fn.lower() == os.path.basename(shp_name).lower():
                return os.path.join(root, fn)
    sys.exit(f"{shp_name} not found in {zip_path}")


def read_dbf(dbf_path):
    """Return (field_names, records) for a dBase table."""
    raw = open(dbf_path, "rb").read()
    n_rec = struct.unpack_from("<I", raw, 4)[0]
    hdr = struct.unpack_from("<H", raw, 8)[0]
    rec_size = struct.unpack_from("<H", raw, 10)[0]
    fields, pos = [], 32
    while raw[pos] != 0x0D:
        name = raw[pos:pos + 11].split(b"\x00")[0].decode("ascii", "replace")
        fields.append((name, raw[pos + 16]))
        pos += 32
    enc = "utf-8"
    cpg = dbf_path[:-4] + ".cpg"
    if os.path.exists(cpg):
        enc = open(cpg, encoding="ascii").read().strip() or enc
    records = []
    for i in range(n_rec):
        off = hdr + i * rec_size + 1
        rec = {}
        for name, flen in fields:
            rec[name] = raw[off:off + flen].decode(enc, "replace").strip()
            off += flen
        records.append(rec)
    return [f[0] for f in fields], records


def read_shp(shp_path):
    """Yield (record_index, [ring, ...]) for polygon shapefiles."""
    raw = open(shp_path, "rb").read()
    off, i = 100, 0
    while off < len(raw):
        _, clen = struct.unpack_from(">ii", raw, off)
        st = struct.unpack_from("<i", raw, off + 8)[0]
        if st == 5:
            num_parts, num_points = struct.unpack_from("<ii", raw, off + 44)
            parts = struct.unpack_from(f"<{num_parts}i", raw, off + 52)
            p_off = off + 52 + 4 * num_parts
            pts = struct.unpack_from(f"<{2 * num_points}d", raw, p_off)
            rings = []
            for k in range(num_parts):
                a = parts[k]
                b = parts[k + 1] if k + 1 < num_parts else num_points
                rings.append([(pts[2 * j], pts[2 * j + 1])
                              for j in range(a, b)])
            yield i, rings
        i += 1
        off += 8 + clen * 2


def load_geojson(src):
    """Load GeoJSON from a path/URL, a zip containing it, or the
    geoBoundaries API (resolves simplifiedGeometryGeoJSON)."""
    if src.startswith("http"):
        safe = re.sub(r"[^A-Za-z0-9]+", "_", src).strip("_")
        raw = fetch_bytes(src, safe)
        if raw[:2] == b"PK":
            return _geojson_from_zip(raw)
        data = json.loads(raw)
        if isinstance(data, dict) and "simplifiedGeometryGeoJSON" in data:
            data = json.loads(fetch_bytes(
                data["simplifiedGeometryGeoJSON"],
                "gb_" + os.path.basename(
                    data["simplifiedGeometryGeoJSON"])))
        return data
    if src.lower().endswith(".zip"):
        return _geojson_from_zip(open(src, "rb").read())
    with open(src, encoding="utf8") as f:
        return json.load(f)


def _geojson_from_zip(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        name = next(n for n in z.namelist()
                    if n.lower().endswith(".geojson"))
        return json.loads(z.read(name))


def geojson_polygons(gj):
    """Yield (properties, [ring, ...]) for Polygon/MultiPolygon features."""
    for f in gj.get("features", []):
        geom = f.get("geometry") or {}
        rings = []
        if geom.get("type") == "Polygon":
            rings = geom.get("coordinates", [])
        elif geom.get("type") == "MultiPolygon":
            for poly in geom.get("coordinates", []):
                rings.extend(poly)
        if rings:
            yield f.get("properties") or {}, \
                [[(p[0], p[1]) for p in ring] for ring in rings]


def mercator(lon, lat):
    """Web Mercator in degrees (x = lon, y = log tan)."""
    lat = max(-85.0, min(85.0, lat))
    return lon, math.degrees(
        math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))


FOLD = {"İ": "i", "ı": "i", "ş": "s", "ğ": "g", "ü": "u", "ö": "o",
        "ç": "c", "ä": "a", "å": "a", "æ": "ae", "ø": "o", "é": "e",
        "è": "e", "ê": "e", "ë": "e", "á": "a", "à": "a", "â": "a",
        "í": "i", "ó": "o", "ú": "u", "ñ": "n", "č": "c", "ř": "r",
        "ž": "z", "š": "s", "ý": "y", "ů": "u", "ě": "e", "ť": "t",
        "ď": "d", "ň": "n", "ł": "l", "ą": "a", "ę": "e", "ś": "s",
        "ź": "z", "ż": "z", "ć": "c", "õ": "o", "î": "i", "û": "u",
        "ô": "o", "ã": "a", "õ": "o", "ç": "c"}


def fold(s):
    s = s.lower()
    for a, b in FOLD.items():
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9-]", "", s)


def simplify(pts, eps):
    """Douglas-Peucker simplification (iterative)."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        x1, y1 = pts[i]
        x2, y2 = pts[j]
        dx, dy = x2 - x1, y2 - y1
        l2 = dx * dx + dy * dy
        best, bestd = -1, -1.0
        for k in range(i + 1, j):
            px, py = pts[k]
            if l2 == 0:
                d = (px - x1) ** 2 + (py - y1) ** 2
            else:
                t = max(0.0, min(1.0, ((px - x1) * dx +
                                       (py - y1) * dy) / l2))
                d = (px - (x1 + t * dx)) ** 2 + (py - (y1 + t * dy)) ** 2
            if d > bestd:
                best, bestd = k, d
        if bestd > eps * eps:
            keep[best] = True
            stack.append((i, best))
            stack.append((best, j))
    return [p for p, k in zip(pts, keep) if k]


def add_inset(main_svg, source_svg, ids, width, at, label=None, pad=4):
    """Place a magnified copy of paths from another rendered SVG into an SVG.

    For maps with tiny dense districts (Metro Vancouver, Greater London,
    Montreal): render the dense area separately at its own scale (so the
    simplification is fine) and drop it into an empty corner of the main map.
    Ids are preserved, so the app's fills/tooltips work on both copies.
    `width` is the inset's width in main-SVG px, `at` its top-left.
    """
    src = open(source_svg, encoding="utf8").read()
    svb = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', src)
    if not svb:
        print("  inset: source has no viewBox")
        return
    sw, sh = float(svb.group(1)), float(svb.group(2))
    k = width / sw
    paths = {}
    for m in re.finditer(r'<path id="([^"]+)" d="([^"]*)"/>', src):
        paths[m.group(1)] = m.group(2)
    tx, ty = at
    parts = ['<g transform="translate(%.1f,%.1f) scale(%.4f)" '
             'fill="#E5E7EB" stroke-width="%.3f">' % (tx, ty, k, 1.0 / k)]
    n = 0
    for pid in ids:
        if pid in paths:
            parts.append('<path id="%s" d="%s"/>' % (pid, paths[pid]))
            n += 1
    parts.append("</g>")
    parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" '
                 'fill="none" stroke="#111827" stroke-width="1.5" '
                 'opacity="0.5"/>'
                 % (tx - pad, ty - pad, width + 2 * pad, sh * k + 2 * pad))
    if label:
        parts.append('<text x="%.1f" y="%.1f" font-size="13" '
                     'font-weight="700" fill="#111827" '
                     'font-family="Source Code Pro,monospace">%s</text>'
                     % (tx - pad, ty - pad - 7, label))
    text = open(main_svg, encoding="utf8").read()
    text = text.replace("</svg>", "\n".join(parts) + "\n</svg>")
    open(main_svg, "w", encoding="utf8").write(text)
    print("  inset: %d paths, width %.0fpx at (%.0f,%.0f) from %s"
          % (n, width, tx, ty, os.path.basename(source_svg)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", default=DEFAULT_ZIP)
    ap.add_argument("--shp", default=DEFAULT_SHP,
                    help="shapefile name inside the zip")
    ap.add_argument("--geojson", help="GeoJSON path/URL (or geoBoundaries API)")
    ap.add_argument("--id-field", default="WkNr",
                    help="shapefile dbf field for the identifier")
    ap.add_argument("--name-field", default="shapeName",
                    help="GeoJSON property for the region name")
    ap.add_argument("--name-map", help="JSON {feature name: identifier}")
    ap.add_argument("--fold", action="store_true",
                    help="ASCII-fold names when not in --name-map")
    ap.add_argument("--attr", choices=["id", "data-label", "class"],
                    default="id")
    ap.add_argument("--id-prefix", default="_")
    ap.add_argument("--no-prefix", action="store_true",
                    help="shorthand for --id-prefix ''")
    ap.add_argument("--lstrip-zeros", action="store_true",
                    help="strip leading zeros from the identifier")
    ap.add_argument("--dissolve", action="store_true",
                    help="union features sharing the same identifier "
                         "(needs shapely)")
    ap.add_argument("--class-pattern", default="wk{n}")
    ap.add_argument("--project", choices=["auto", "none", "mercator"],
                    default="auto")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--attribution", default=ATTRIBUTION)
    ap.add_argument("--simplify", type=float, default=0.0005,
                    help="DP tolerance as a fraction of the bbox diagonal")
    ap.add_argument("--width", type=int, default=1000)
    ap.add_argument("--force", action="store_true", help="re-download")
    args = ap.parse_args()
    if args.no_prefix:
        args.id_prefix = ""

    geoms = []          # list of (identifier, [ring, ...])
    if args.geojson:
        gj = load_geojson(args.geojson)
        name_map = {}
        if args.name_map:
            with open(args.name_map, encoding="utf8") as f:
                name_map = json.load(f)

        def ident_of(props):
            raw = str(props.get(args.name_field, "")).strip()
            ident = name_map.get(raw) or (fold(raw) if args.fold else raw)
            return ident.lstrip("0") if args.lstrip_zeros else ident

        feats = list(geojson_polygons(gj))
        if args.project == "mercator":
            project = True
        elif args.project == "none":
            project = False
        else:  # auto: lon/lat -> Mercator, projected coords used as-is
            x0, y0 = feats[0][1][0][0] if feats else (0, 0)
            project = abs(x0) <= 180 and abs(y0) <= 90

        if args.dissolve:
            from shapely.geometry import mapping, shape
            from shapely.ops import unary_union
            groups, order = {}, []
            for f in gj.get("features", []):
                geom = f.get("geometry")
                if not geom:
                    continue
                ident = ident_of(f.get("properties") or {})
                if ident not in groups:
                    groups[ident] = []
                    order.append(ident)
                groups[ident].append(shape(geom))
            for ident in order:
                merged = mapping(unary_union(groups[ident]))
                rings = []
                polys = ([merged["coordinates"]]
                         if merged["type"] == "Polygon"
                         else merged["coordinates"])
                for poly in polys:
                    rings.extend([[tuple(p) for p in ring]
                                  for ring in poly])
                if project:
                    rings = [[mercator(x, y) for x, y in r]
                             for r in rings]
                geoms.append((ident, rings))
        else:
            for props, rings in feats:
                ident = ident_of(props)
                if project:
                    rings = [[mercator(x, y) for x, y in r]
                             for r in rings]
                geoms.append((ident, rings))
    else:
        zip_path = os.path.join(CACHE, os.path.basename(args.zip))
        if args.force or not os.path.exists(zip_path):
            os.makedirs(CACHE, exist_ok=True)
            with open(zip_path, "wb") as f:
                f.write(fetch_bytes(args.zip,
                                    os.path.basename(args.zip)))
        shp_path = extract(zip_path, args.shp)
        fields, records = read_dbf(shp_path[:-4] + ".dbf")
        if args.id_field not in fields:
            sys.exit(f"id field '{args.id_field}' not in {fields}")
        raw_geoms = [(records[idx][args.id_field], rings)
                     for idx, rings in read_shp(shp_path)]
        if args.project == "none":
            proj = False
        elif args.project == "mercator":
            proj = True
        else:  # auto: lon/lat -> Mercator, projected coords used as-is
            px, py = raw_geoms[0][1][0][0]
            proj = abs(px) <= 180 and abs(py) <= 90
        for ident, rings in raw_geoms:
            if proj:
                rings = [[mercator(x, y) for x, y in r] for r in rings]
            geoms.append((ident, rings))

    xs = [x for _, rings in geoms for r in rings for x, _ in r]
    ys = [y for _, rings in geoms for r in rings for _, y in r]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    eps = args.simplify * math.hypot(x1 - x0, y1 - y0)
    pad = 20
    scale = (args.width - 2 * pad) / (x1 - x0)
    height = round((y1 - y0) * scale + 2 * pad, 1)

    paths, pts_in, pts_out, ids = [], 0, 0, []
    for ident, rings in geoms:
        ids.append(ident)
        if args.attr == "data-label":
            attr = f'data-label="{ident}"'
        elif args.attr == "class":
            attr = f'class="{args.class_pattern.format(n=ident)}"'
        else:
            attr = f'id="{args.id_prefix}{ident}"'
        d = []
        for ring in rings:
            pts_in += len(ring)
            s = simplify(ring, eps)
            pts_out += len(s)
            d.append("M" + "L".join(
                f"{(x - x0) * scale + pad:.1f},{(y1 - y) * scale + pad:.1f}"
                for x, y in s) + "Z")
        paths.append(f'<path {attr} d="{" ".join(d)}"/>')

    svg = "\n".join([
        f"<!-- {args.attribution} -->",
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {args.width} '
        f'{height}" width="{args.width}" height="{height}">',
        '<g fill="#E5E7EB" stroke="#111827" stroke-width="1" '
        'stroke-linejoin="round" fill-rule="evenodd">',
        *paths,
        "</g>",
        "</svg>",
        "",
    ])
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf8") as f:
        f.write(svg)
    print(f"{len(paths)} paths | points {pts_in} -> {pts_out} | "
          f"{os.path.getsize(args.out)} bytes | wrote {args.out}")


if __name__ == "__main__":
    main()
