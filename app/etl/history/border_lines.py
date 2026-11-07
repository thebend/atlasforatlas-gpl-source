"""The borders the precise sources draw, as dated lines over the territory colours.

The colours are a field on a grid (fields_polygons.py), 0.05 to 0.25 degrees a cell; zoomed in, its
edges are a cell wide. Where a period's borders come from a surveyed source, its own lines can be drawn
as they are. Only there: no line is drawn crisper than its source (docs/design/policy.md).

  precise    CShapes 2.0 where it marks the border as defined (b_def = 1: crisp 1.0 in border_sides.py);
             OpenHistoricalMap relations (crisp 1.0); Europe's CShapes 1910-50 extract
  not drawn  Cliopatria (generalised by design: Seshat's outlines at year resolution), CShapes borders it
             marks as not clearly defined, paper claims (an OHM relation flagged as a claim), and every
             modelled or AI-research edge. Those stay as the field draws them, soft.

A line is drawn where two sides' precise polygons meet: side A's outline where it runs along side B's
territory, as A's source draws it. Coasts are never a meeting of two sides, so the shore stays the
terrain's. A side's own units (a colony and its owner) are one territory, as the colours draw them.

The commercial profile (etl/profile.py) has already rewritten the manifest's border sources by the time
this runs (CShapes -> Cliopatria), so a commercial build draws no CShapes line; the file names its
sources for etl/licences.py.

Slices are the fields' own (fields.json), so a line changes on the day the colours do. Writes
data/<scene>/borderlines.json: GeoJSON, each line with the two sides, its source and [y0, y1).

Run: ATLAS_SCENE=balkan-wars uv run --project .. python -m etl.history.border_lines
(fields_polygons.py runs it at its end.)
"""
from __future__ import annotations

import json

import shapely
from shapely.geometry import mapping, shape

from etl.common import CFG, OUT, SCENE, from_window, write_json

Y1 = CFG["years"][1]
PRECISE = {"cshapes2", "ohm"}
# the two sides' outlines are taken to meet within this (degrees: about 50 m); a source's shared edges
# coincide, so this only absorbs rounding
MEET = 5e-4
# vertices closer than this to the line through their neighbours are dropped (about 40 m: a quarter of a
# pixel at the map's deepest zoom, about 150 m a pixel), and coordinates kept to 4 decimals (about 10 m)
SIMPLIFY = 4e-4
GRID = 1e-4


def raw_outlines(feats: list[dict]) -> dict[tuple, object]:
    """The sources' own outlines, unsimplified (the fields' copies are simplified to a quarter of a cell,
    etl/fetch/borders.py and ohm.py), clipped to the same window: CShapes from its TopoJSON, whose shared
    arcs make two neighbours' edges the same line; OHM from the relations as fetched. Rows not found
    keep the fields' copy (simplified: never more detail than the source)."""
    from etl.fetch import borders as FB
    from etl.fetch import ohm as FO
    from etl.common import SCACHE, window_clip
    want = {f["row"] for f in feats if f.get("row")}
    out: dict[tuple, object] = {}
    if any(r[0] == "cshapes2" for r in want):
        topo = FB.SRC / "cshapes2" / "cshapes_2_gw.topojson"
        if topo.exists():
            for t in FB.topo_features(json.loads(topo.read_text())):
                p = t["properties"]
                k = ("cshapes2", p["gwcode"], p["start"])
                if k in want:
                    out[k] = FB.polys(window_clip(shapely.make_valid(shape(t["geometry"])), FB.WINDOW))
    raw = SCACHE / "geo" / "ohm.raw.json"
    if any(r[0] == "ohm" for r in want) and raw.exists():
        for e in json.loads(raw.read_text())["elements"]:
            k = ("ohm", f"ohm:r{e['id']}")
            if k in want:
                g, _ = FO.ohm_build(e)
                if g is not None:
                    out[k] = window_clip(shapely.make_valid(g), FO.WINDOW)
    return out


def precise(f: dict) -> bool:
    return f.get("source") in PRECISE and f.get("crisp", 0) >= 1.0 and not f.get("claim")


def build(feats: list[dict], years: list[float]) -> dict:
    """The lines for the slices `years` from the polygons `feats` (fields_polygons.border_inputs())."""
    feats = [dict(f) for f in feats if precise(f)]
    raw = raw_outlines(feats)
    for f in feats:
        g = raw.get(f.get("row"))
        if g is not None and not g.is_empty:
            f["geom"] = g
        if not f["geom"].is_valid:
            f["geom"] = shapely.make_valid(f["geom"])
    union_cache: dict[tuple, object] = {}
    pair_cache: dict[tuple, object] = {}
    spans: dict[tuple, list[int]] = {}        # (a, b, wkb) -> the slices it is drawn in
    geoms: dict[tuple, object] = {}
    srcs: dict[tuple, str] = {}
    from etl.history.fields_polygons import active      # the colours' own test, so lines and colours change together
    for i, y in enumerate(years):
        by_side: dict[str, list[int]] = {}
        for k, f in enumerate(feats):
            if active(f["y0"], f["y1"], y):
                for sd, _ in f["sides"]:
                    by_side.setdefault(sd, []).append(k)
        unions = {}
        for sd, ks in by_side.items():
            key = (sd, tuple(ks))
            if key not in union_cache:
                g = shapely.union_all([feats[k]["geom"] for k in ks])
                union_cache[key] = (g, g.boundary, g.bounds)
            unions[sd] = (key, *union_cache[key])
        sides = sorted(unions)
        for ai, a in enumerate(sides):
            ka, ga, la, ba = unions[a]
            for b in sides[ai + 1:]:
                kb, gb, lb, bb = unions[b]
                if ba[0] > bb[2] + MEET or bb[0] > ba[2] + MEET or ba[1] > bb[3] + MEET or bb[1] > ba[3] + MEET:
                    continue
                pk = (ka, kb)
                if pk not in pair_cache:
                    line = la.intersection(gb.buffer(MEET))
                    line = shapely.line_merge(shapely.union_all([g for g in shapely.get_parts(line) if g.geom_type in ("LineString", "MultiLineString")])) if not line.is_empty else line
                    pair_cache[pk] = None if line.is_empty or line.length < 1e-6 else shapely.set_precision(line.simplify(SIMPLIFY), GRID)
                line = pair_cache[pk]
                if line is None or line.is_empty:
                    continue
                k = (a, b, line.wkb)
                spans.setdefault(k, []).append(i)
                geoms[k] = line
                src = {feats[j]["source"] for j in ka[1]} | {feats[j]["source"] for j in kb[1]}
                srcs[k] = "+".join(sorted(src))
    out = []
    for k, idx in spans.items():
        # consecutive slices in a run: one feature per run
        runs: list[list[int]] = []
        for i in idx:
            if runs and runs[-1][-1] == i - 1:
                runs[-1].append(i)
            else:
                runs.append([i])
        g = from_window(geoms[k])
        if g.is_empty:
            continue
        for r in runs:
            y0 = years[r[0]]
            y1 = years[r[-1] + 1] if r[-1] + 1 < len(years) else Y1 + 2.0
            out.append({"type": "Feature", "geometry": mapping(g),
                        "properties": {"a": k[0], "b": k[1], "src": srcs[k], "y0": round(y0, 4), "y1": round(y1, 4)}})
    sources = sorted({s for f in out for s in f["properties"]["src"].split("+")})
    return {"type": "FeatureCollection", "sources": sources, "features": out}


def write(feats: list[dict], years: list[float]) -> None:
    fc = build(feats, years)
    p = OUT / "borderlines.json"
    if not fc["features"]:
        p.unlink(missing_ok=True)
        print(f"{SCENE}: no precise borders to draw")
        return
    write_json(p, fc)
    print(f"{SCENE}: {len(fc['features'])} border lines from {', '.join(fc['sources'])}, {p.stat().st_size // 1024} KB")


def main() -> None:
    from etl.history.fields_polygons import border_inputs
    feats, _, _ = border_inputs()
    meta = json.loads((OUT / "fields.json").read_text())
    write(feats, meta["slices"])


if __name__ == "__main__":
    main()
