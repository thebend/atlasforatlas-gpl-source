"""Europe 1910-1950 internal divisions (provinces, Länder, governorates...): download OpenHistoricalMap
admin boundaries and the heiDATA Russian Empire / USSR census GIS, then crop and convert.

Downloads (skipped when already cached) -> <CACHE>/scenes/europe/divisions/raw/
  ohm/ohm_admin_tags_l2-8.json   tags of every boundary=administrative relation, admin_level 2-8, in the
                                 window (28 Overpass queries over 10x10 deg tiles)
  ohm/geom/l<level>_<NNNN>.json.gz   member-way geometry ("out geom") of the relations with admin_level 2-6,
                                 start_date year <= 1950 and (no end_date or end year >= 1910); batches of
                                 10 ids (level 2) or 40 ids; OHM's shared Overpass server, >= 5 s apart
  heidata_10064/                 heiDATA doi:10.11588/data/10064 shapefiles (CC BY 4.0)

Outputs (<CACHE>/scenes/europe/divisions/, read by divisions.py):
  ohm_admin.geojson              OHM levels 3-6, cropped to the window, simplified 0.002 deg, 1e-5 grid;
                                 country = OHM level-2 polity containing the unit (most years of overlap)
  heidata_russia_1897.geojson    1897 census governorates (snapshot)
  heidata_ussr_1926.geojson      1926 census units (snapshot)
  coverage.json                  share of each CShapes 2.0 country covered per source/level on sample dates
                                 (needs geo/cshapes2_europe_1910_1950.geojson from borders.py)
  sources.json                   provenance, licences, hashes; raw/ohm/build_report.json lists repairs

OHM is a live, volunteer-edited database: a fresh download differs from an older one wherever
relations were added or edited since. Delete raw/ohm to refetch.

Run (from app): ATLAS_SCENE=europe uv run --project .. python -m etl.fetch.europe.divisions
"""
from __future__ import annotations

import glob
import gzip
import json
import re
from pathlib import Path


from shapely import set_precision  # noqa: E402
from shapely.geometry import GeometryCollection, LineString, MultiPolygon, Polygon, mapping, shape  # noqa: E402
from shapely.ops import linemerge, polygonize, snap, unary_union  # noqa: E402
from shapely.strtree import STRtree  # noqa: E402
from shapely.validation import make_valid  # noqa: E402

from etl.shp import read_dbf, read_shp
from etl import net, profile
from etl.fetch.europe import divisions_doc
from etl.fetch.europe.util import DIV, DIV_RAW, GEO, WINDOW, download, dump, log, overpass, retrieved, sha256

OHM = DIV_RAW / "ohm"
TAGS = OHM / "ohm_admin_tags_l2-8.json"
GEOM = OHM / "geom"
HEI = DIV_RAW / "heidata_10064"
HEI_API = "https://heidata.uni-heidelberg.de/api"
HEI_DOI = "doi:10.11588/data/10064"
# file name -> datafile id in heiDATA (as listed by the dataset API on 2026-10-24; the API is asked first)
HEI_FILES = {"1897RussianEmpire.cpg": 2082, "1897RussianEmpire.dbf": 2083, "1897RussianEmpire.prj": 2084,
             "1897RussianEmpire.shp": 2087, "1897RussianEmpire.shx": 2088, "1926SovietUnion.dbf": 2089,
             "1926SovietUnion.shp": 2092, "1926SovietUnion.shx": 2093, "Description.pdf": 2094, "update_read_me.TXT": 2095}
SIMPLIFY_DEG = 0.002           # ~150-220 m; topology-preserving per feature
LO, HI = 1910, 1950


def yr(x):
    m = re.match(r"^(-?\d{1,4})", x or "")
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------- fetch

def fetch_ohm_tags() -> list[dict]:
    if TAGS.exists():
        return json.loads(TAGS.read_text())
    allel = {}
    for la in range(33, 72, 10):
        for lo in range(-25, 45, 10):
            s, w, n, e = la, lo, min(la + 10, 72), min(lo + 10, 45)
            q = f'[out:json][timeout:180];rel["boundary"="administrative"]["admin_level"~"^[2-8]$"]({s},{w},{n},{e});out tags;'
            d = json.loads(overpass(q))
            for el in d["elements"]:
                allel[el["id"]] = el
            log("  ohm tags", s, w, len(d["elements"]), len(allel))
    TAGS.parent.mkdir(parents=True, exist_ok=True)
    dump(TAGS, list(allel.values()))
    return list(allel.values())


def fetch_ohm_geom(els: list[dict]) -> None:
    sel = {}
    for e in els:
        t = e["tags"]
        lv = t.get("admin_level")
        if lv not in ("2", "3", "4", "5", "6"):
            continue
        sy, ey = yr(t.get("start_date")), yr(t.get("end_date"))
        if sy is None or sy > HI or (ey is not None and ey < LO):
            continue
        sel.setdefault(lv, []).append(e["id"])
    GEOM.mkdir(parents=True, exist_ok=True)
    for lv in ["2", "3", "4", "5", "6"]:
        ids = sorted(sel.get(lv, []))
        bs = 10 if lv == "2" else 40
        for i in range(0, len(ids), bs):
            fn = GEOM / f"l{lv}_{i // bs:04d}.json.gz"
            if fn.exists():
                continue
            raw = overpass(f'[out:json][timeout:300];rel(id:{",".join(map(str, ids[i:i + bs]))});out geom;')
            tmp = fn.with_name(fn.name + ".part")
            with gzip.open(tmp, "wb") as f:
                f.write(raw)
            tmp.replace(fn)
            log("  ohm geom", lv, i, len(ids), len(raw))


def fetch_heidata() -> None:
    ids = dict(HEI_FILES)
    if not all((HEI / f).exists() for f in ids):
        try:
            listing = net.get_json(f"{HEI_API}/datasets/:persistentId/", {"persistentId": HEI_DOI}, tries=2)
            for f in listing["data"]["latestVersion"]["files"]:
                if f["dataFile"]["filename"] in ids:
                    ids[f["dataFile"]["filename"]] = f["dataFile"]["id"]
        except Exception as ex:  # noqa: BLE001 - fall back to the ids recorded above
            log("  heiDATA listing failed, using recorded ids:", ex)
    for name, fid in ids.items():
        download(f"{HEI_API}/access/datafile/{fid}", HEI / name)


# ---------------------------------------------------------------- geometry helpers

def polys_only(g):
    if g is None or g.is_empty:
        return None
    if isinstance(g, (Polygon, MultiPolygon)):
        return g
    if isinstance(g, GeometryCollection):
        ps = [p for p in g.geoms if isinstance(p, (Polygon, MultiPolygon))]
        if not ps:
            return None
        out = []
        for p in ps:
            out.extend(p.geoms if isinstance(p, MultiPolygon) else [p])
        return MultiPolygon(out)
    return None


def crop(g, simplify=SIMPLIFY_DEG):
    if not g.is_valid:
        g = make_valid(g)
    g = polys_only(g)
    if g is None or not g.intersects(WINDOW):
        return None
    g = polys_only(g.intersection(WINDOW))
    if g is None:
        return None
    if simplify:
        g = g.simplify(simplify, preserve_topology=True)
        if not g.is_valid:
            g = polys_only(make_valid(g))
    return g if g is not None and not g.is_empty else None


def rnd(coords, nd=5):
    if isinstance(coords, (list, tuple)) and coords and isinstance(coords[0], (int, float)):
        return [round(c, nd) for c in coords]
    return [rnd(c, nd) for c in coords]


def to_grid(g):
    """Round to 5 decimals, then snap to the 1e-5 grid with set_precision so every geometry stays valid."""
    m = mapping(g)
    g = shape({"type": m["type"], "coordinates": rnd(m["coordinates"])})
    g = polys_only(set_precision(g, 1e-5))
    if g is None:
        return None
    m = mapping(g)
    return {"type": m["type"], "coordinates": rnd(m["coordinates"])}


def write_fc(path: Path, feats, meta) -> int:
    fc = {"type": "FeatureCollection", "metadata": meta, "features": []}
    for props, g in feats:
        geom = to_grid(g)
        if geom is not None:
            fc["features"].append({"type": "Feature", "properties": props, "geometry": geom})
    dump(path, fc, ensure_ascii=False, separators=(",", ":"))
    return len(fc["features"])


# ---------------------------------------------------------------- heiDATA

def esri_rings(parts):
    # ESRI: outer rings clockwise, holes counter-clockwise; build by even-odd containment
    polys = [Polygon(p) for p in parts if len(p) >= 4]
    polys = [p if p.is_valid else p.buffer(0) for p in polys]
    g = None
    for p in polys:
        g = p if g is None else g.symmetric_difference(p)
    return g


def heidata_one(stem, namefield, rusfield, date, country, out, note) -> None:
    feats = []
    for i, (g, r) in enumerate(zip(read_shp(HEI / f"{stem}.shp"), read_dbf(HEI / f"{stem}.dbf"))):
        gg = esri_rings(g)
        if gg is None:
            continue
        gg = crop(gg)
        if gg is None:
            continue
        feats.append(({"name": r[namefield], "name_ru": r[rusfield], "start": date, "end": date,
                       "date_kind": "snapshot", "country": country, "level": 1,
                       "source_id": f"heidata:10064:{stem}:{i}", "note": note}, gg))
    n = write_fc(DIV / out, feats, {
        "source": "heiDATA doi:10.11588/data/10064 (Transcultural Empire GIS, 1897 & 1926 censuses)",
        "licence": "CC BY 4.0", "window": [-25, 33, 45, 72], "simplify_deg": 0.002})
    log(out, n)


def heidata() -> None:
    heidata_one("1897RussianEmpire", "NAMEENG", "NAMERUS", "1897-02-09", "Russian Empire", "heidata_russia_1897.geojson",
                "Boundaries as of the 1897 Imperial census (9 Feb 1897 NS). Dataset gives no validity range; known later "
                "change before 1917: Kholm Governorate carved from Lublin/Siedlce 1912.")
    heidata_one("1926SovietUnion", "NameENG", "NameRUS", "1926-12-17", "Soviet Union", "heidata_ussr_1926.geojson",
                "Units as of the 17 Dec 1926 All-Union census. Mixed levels: Ukrainian and Belorussian SSRs are single "
                "units (no internal okrugs); RSFSR split into gubernias/oblasts/ASSRs/krais.")


# ---------------------------------------------------------------- OpenHistoricalMap

def ohm_rings(ways):
    lines = [LineString([(p["lon"], p["lat"]) for p in w]) for w in ways if len(w) >= 2]
    if not lines:
        return None, 0
    merged = linemerge(lines)
    parts = merged.geoms if hasattr(merged, "geoms") else [merged]
    g, open_ = None, 0
    for ln in parts:
        if ln.is_ring and len(ln.coords) >= 4:
            p = Polygon(ln.coords)
            p = p if p.is_valid else p.buffer(0)
            g = p if g is None else g.symmetric_difference(p)
        else:
            open_ += 1
    if open_:  # fall back to polygonize to salvage closed faces
        faces = list(polygonize(unary_union(lines)))
        if faces:
            g2 = unary_union(faces)
            if g is None or g2.area > g.area:
                g = g2
    return g, open_


def ohm_build(rel):
    """Relation -> (polygon, flag): flag 0 = clean, n > 0 = n unclosed outer chains polygonized, -1 = gaps snapped."""
    members = rel.get("members", [])
    outer = [m["geometry"] for m in members if m["type"] == "way" and m.get("role", "outer") in ("outer", "") and "geometry" in m]
    inner = [m["geometry"] for m in members if m["type"] == "way" and m.get("role") == "inner" and "geometry" in m]
    g, open_o = ohm_rings(outer)
    if g is None:
        # last resort: close gaps of <= 1e-4 deg (~10 m) only, then polygonize
        lines = [LineString([(p["lon"], p["lat"]) for p in w]) for w in outer if len(w) >= 2]
        if lines:
            u = unary_union(lines)
            faces = list(polygonize(unary_union([snap(ln, u, 1e-4) for ln in lines])))
            if faces:
                g = unary_union(faces)
                open_o = -1
        if g is None:
            return None, open_o
    if inner:
        h, _ = ohm_rings(inner)
        if h is not None:
            g = g.difference(h)
    return g, open_o


def ohm(ret: str) -> None:
    rels = {}
    for fn in sorted(glob.glob(str(GEOM / "*.json.gz"))):
        for el in json.load(gzip.open(fn))["elements"]:
            if el["type"] == "relation":
                rels[el["id"]] = el
    log("ohm relations", len(rels))

    built, problems, repairs = {}, [], {}
    for rid, rel in rels.items():
        t = rel["tags"]
        try:
            g, open_ = ohm_build(rel)
        except Exception as ex:  # noqa: BLE001 - one broken relation must not stop the build
            problems.append((rid, t.get("name"), f"error {ex}"))
            continue
        if g is None or g.is_empty:
            problems.append((rid, t.get("name"), "no closed rings"))
            continue
        if open_ == -1:
            problems.append((rid, t.get("name"), "gaps <=1e-4 deg snapped, polygonized"))
        elif open_:
            problems.append((rid, t.get("name"), f"{open_} unclosed outer chains (polygonize fallback)"))
        if g.area < 1e-6:
            problems.append((rid, t.get("name"), "degenerate area after repair; dropped"))
            continue
        built[rid] = g
        repairs[rid] = open_

    # countries: OHM admin_level=2, unsimplified, for containment tests
    countries = []
    for rid, g in built.items():
        t = rels[rid]["tags"]
        if t.get("admin_level") != "2":
            continue
        cg = polys_only(g.intersection(WINDOW)) if g.is_valid else polys_only(g.buffer(0).intersection(WINDOW))
        if cg is None:
            continue
        countries.append((rid, t.get("name:en") or t.get("name"), yr(t.get("start_date")), yr(t.get("end_date")), cg))
    tree = STRtree([c[4] for c in countries])

    def country_of(g, sy, ey):
        pt = g.representative_point()
        best = {}
        for idx in tree.query(pt):
            _cid, cname, csy, cey, cg = countries[idx]
            lo = max(sy, csy if csy is not None else -9999)
            hi = min(ey if ey is not None else 2100, cey if cey is not None else 2100)
            if hi < lo or not cg.contains(pt):
                continue
            best[cname] = best.get(cname, 0) + (hi - lo + 1)
        if not best:
            return None, []
        ranked = sorted(best, key=lambda k: -best[k])
        return ranked[0], ranked

    feats = []
    for rid, g in built.items():
        t = rels[rid]["tags"]
        lv = t.get("admin_level")
        if lv not in ("3", "4", "5", "6"):
            continue
        sy, ey = yr(t.get("start_date")), yr(t.get("end_date"))
        cg = crop(g)
        if cg is None:
            continue
        cname, call = country_of(g if g.is_valid else g.buffer(0), sy, ey if ey is not None else 2100)
        props = {"name": t.get("name"), "start": t.get("start_date"), "end": t.get("end_date"),
                 "country": cname, "level": int(lv), "source_id": f"ohm:r{rid}"}
        if t.get("name:en"):
            props["name_en"] = t["name:en"]
        if len(call) > 1:
            props["countries_over_time"] = call
        if t.get("wikidata"):
            props["wikidata"] = t["wikidata"]
        if repairs.get(rid):
            props["geom_repair"] = "snapped<=1e-4deg" if repairs[rid] == -1 else "polygonized from unclosed ways (may be partial)"
        if t.get("source"):
            props["ohm_source"] = t["source"][:200]
        if t.get("license"):
            props["ohm_license_tag"] = t["license"][:120]
        feats.append((props, cg))

    feats.sort(key=lambda f: (f[0]["level"], str(f[0]["country"]), str(f[0]["start"])))
    n = write_fc(DIV / "ohm_admin.geojson", feats, {
        "source": "OpenHistoricalMap via overpass-api.openhistoricalmap.org, boundary=administrative admin_level 3-6, start<=1950 and (end>=1910 or open)",
        "licence": "CC0 1.0 (OpenHistoricalMap data); some relations carry their own source/license tags (kept as ohm_source/ohm_license_tag)",
        "country_assignment": "OHM admin_level=2 relation containing representative point, ranked by years of overlap",
        "window": [-25, 33, 45, 72], "simplify_deg": 0.002, "retrieved": ret})
    dump(OHM / "build_report.json",
         {"problems": problems, "countries_level2": [(c[0], c[1], c[2], c[3]) for c in countries]},
         ensure_ascii=False, indent=0)
    log("ohm features", n, "problems", len(problems))


# ---------------------------------------------------------------- coverage audit, sources

COVERAGE_DATES = ["1910-07-01", "1914-07-01", "1920-07-01", "1925-07-01", "1930-07-01", "1935-07-01", "1938-07-01",
                  "1941-07-01", "1944-07-01", "1946-07-01", "1950-07-01"]
OUTPUTS = ["ohm_admin.geojson", "heidata_russia_1897.geojson", "heidata_ussr_1926.geojson"]


def coverage() -> None:
    """Per CShapes country x sample date: share of its area covered by divisions valid on that date."""
    def norm(d, end=False):
        if not d:
            return None
        m = re.match(r"^(-?\d{4})(?:-(\d{2}))?(?:-(\d{2}))?", d)
        if not m:
            return None
        y, mo, da = m.group(1), m.group(2), m.group(3)
        return f"{y}-{mo or '12'}-{da or '28'}" if end else f"{y}-{mo or '01'}-{da or '01'}"

    def load(fn):
        return [(norm(f["properties"]["start"]), norm(f["properties"]["end"], True), f["properties"].get("level"), shape(f["geometry"]))
                for f in json.loads((DIV / fn).read_text())["features"]]

    cs_path = GEO / "cshapes2_europe_1910_1950.geojson"
    if not cs_path.exists():
        raise SystemExit(f"{cs_path} missing: run sources/europe_borders.py first")
    sources = {fn: load(fn) for fn in OUTPUTS}
    res = {}
    for c in json.loads(cs_path.read_text())["features"]:
        p = c["properties"]
        cg = shape(c["geometry"])
        if p.get("area_km2_in_window", 0) < 3000:
            continue
        for d in COVERAGE_DATES:
            if not (p["start"] <= d <= p["end"]):
                continue
            row = {}
            for fn, feats in sources.items():
                for lv in sorted({f[2] for f in feats}):
                    gs = [f[3] for f in feats if f[2] == lv and (f[0] is None or f[0] <= d) and (f[1] is None or d <= f[1])
                          and f[3].intersects(cg)]
                    if not gs:
                        continue
                    share = unary_union(gs).intersection(cg).area / cg.area
                    if share >= 0.02:
                        row[f"{fn.replace('.geojson', '')}:L{lv}"] = [round(share, 2), len(gs)]
            res.setdefault(p["name"], {})[d] = row
    dump(DIV / "coverage.json", res, indent=1, ensure_ascii=False)
    log("coverage countries", len(res))


def write_sources(ret: str) -> None:
    def fi(p):
        fp = DIV / p
        return {"path": p, "bytes": fp.stat().st_size, "sha256": sha256(fp)}

    gz = sorted(GEOM.glob("*.json.gz"))
    geom_files = {"path": "raw/ohm/geom/l{2..6}_NNNN.json.gz", "count": len(gz), "bytes": sum(f.stat().st_size for f in gz)}
    heidata_files = [fi("raw/heidata_10064/" + f.name) for f in sorted(HEI.iterdir()) if not f.name.endswith(".part")]
    out = {"generated": ret, "window": {"lon": [-25, 45], "lat": [33, 72]}, "period": [1910, 1950],
           "outputs": {"ohm_admin.geojson": "ohm", "heidata_russia_1897.geojson": "heidata_10064",
                       "heidata_ussr_1926.geojson": "heidata_10064"},
           "coverage_audit": "coverage.json (share of each CShapes 2.0 country area covered by divisions valid on sample dates, "
                             "per source:level; produced by etl/fetch/europe/divisions.py)",
           "scripts": "app/etl/fetch/europe/divisions.py (Overpass + heiDATA fetch, conversion, coverage, "
                      "this file). Run from app: ATLAS_SCENE=europe uv run --project .. python -m etl.fetch.europe.divisions",
           "raw_total_bytes": sum(f.stat().st_size for f in DIV_RAW.rglob("*") if f.is_file()),
           "sources": divisions_doc.sources(fi, geom_files, heidata_files, ret)}
    dump(DIV / "sources.json", out, indent=1, ensure_ascii=False)
    log("divisions sources.json written; raw bytes", out["raw_total_bytes"])


def main() -> None:
    log("europe divisions: fetch ->", DIV_RAW)
    fetch_heidata()
    fetch_ohm_geom(fetch_ohm_tags())
    ret = retrieved(TAGS)
    heidata()
    ohm(ret)
    if not profile.blocked("cshapes"):     # the coverage audit measures against CShapes (a check, not served)
        coverage()
    write_sources(ret)


if __name__ == "__main__":
    main()
