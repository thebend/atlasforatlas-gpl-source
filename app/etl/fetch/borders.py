"""Worldwide border sources for any scene: CShapes 2.0 (1886-2019) and Cliopatria (3400 BCE-2024).

A scene names its border sources in its manifest (etl.borders), e.g.
  "borders": ["cshapes"]                                  states and their colonies from 1886
  "borders": ["cliopatria"]                               polities, coarse, any date
  "borders": ["cshapes", {"source": "cliopatria", "until": 1886}]

  "borders": [{"source": "cshapes", "carry_to": 2026}]   CShapes' last-day borders (2019) carried forward
  "borders": [{"source": "cliopatria", "carry_to": 2026, "drop": ["State of Israel"]}]
                                                          Cliopatria's last year (2024) carried forward; rows
                                                          another source draws here left out by name

Under a build profile that blocks CShapes (ATLAS_PROFILE=commercial, etl/profile.py) the manifest no
longer names it, and this step refuses to read it.

Downloads (once, shared by every scene) -> <CACHE>/sources/
  cshapes2/cshapes_2.0.tar.gz     https://icr.ethz.ch/data/cshapes/ (CC BY-NC-SA 4.0). The R package's
                                  TopoJSON is used rather than the CSV/GeoJSON: it is the same release
                                  but keeps the `status` (independent, colony, protectorate, mandate,
                                  occupied) and `owner` (GW code of the sovereign) fields, so a colony
                                  can be drawn as its owner's territory.
  cliopatria/cliopatria.geojson.zip   Seshat Cliopatria v0.2.1 (CC BY 4.0), pinned by SHA-256

Outputs per scene -> <CACHE>/scenes/<scene>/geo/
  cshapes2.geojson     country-periods overlapping the scene's years and window, clipped, with
                       name, gwcode, start, end (ISO dates, end inclusive), status, owner, b_def
  cliopatria.geojson   polity rows overlapping the years and window, clipped, with name, wikidata,
                       from/to years (inclusive), member_of (the composite empire a row belongs to)
  borders.json         provenance: sources, licences, hashes, counts

Run: ATLAS_SCENE=<scene> uv run --project .. python -m etl.fetch.borders
"""
from __future__ import annotations

import hashlib
import json
import lzma
import tarfile
import urllib.request
import warnings
import zipfile

import shapely
from shapely.geometry import box, mapping, shape

from etl import profile
from etl.common import CACHE, CFG, LAT0, LAT1, LON0, LON1, SCACHE, SCENE, UA, write_json

warnings.filterwarnings("ignore", category=RuntimeWarning)

SRC = CACHE / "sources"
CSHAPES_URL = "https://icr.ethz.ch/data/cshapes/cshapes_2.0.tar.gz"
CSHAPES_TOPO = "cshapes/inst/extdata/cshapes_2_gw.topojson.xz"
CLIO_URL = "https://github.com/Seshat-Global-History-Databank/cliopatria/raw/refs/tags/v0.2.1/cliopatria.geojson.zip"
CLIO_SHA256 = "e10a4e429fca708788ff9e7572a95fce801fae55852d217cffabc1c59cd4eed4"
Y0, Y1 = CFG["years"]
# clip window: a margin so polygons straddling the edge keep their true edge inside the scene
WINDOW = box(LON0 - 1, max(-90, LAT0 - 1), LON1 + 1, min(90, LAT1 + 1))
TOL = CFG["field_step"] / 4                     # simplification below the field grid's resolution


def download(url: str, dest, sha: str | None = None) -> None:
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        print("download", url, flush=True)
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        tmp = dest.with_suffix(dest.suffix + ".part")
        tmp.write_bytes(urllib.request.urlopen(req, timeout=600).read())
        tmp.replace(dest)
    if sha and hashlib.sha256(dest.read_bytes()).hexdigest() != sha:
        raise SystemExit(f"{dest.name}: SHA-256 does not match the pinned release; check the source before re-pinning")


def sha256(p) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ------------------------------------------------------------------ CShapes 2.0

def topo_features(topo: dict) -> list[dict]:
    """TopoJSON (unquantised, as CShapes ships it) -> GeoJSON-like features."""
    arcs = topo["arcs"]

    def arc(i: int) -> list:
        return arcs[i] if i >= 0 else arcs[~i][::-1]

    def ring(ix: list[int]) -> list:
        pts: list = []
        for i in ix:
            a = arc(i)
            pts.extend(a if not pts else a[1:])
        return pts

    out = []
    for g in next(iter(topo["objects"].values()))["geometries"]:
        if g["type"] == "Polygon":
            geom = {"type": "Polygon", "coordinates": [ring(r) for r in g["arcs"]]}
        elif g["type"] == "MultiPolygon":
            geom = {"type": "MultiPolygon", "coordinates": [[ring(r) for r in p] for p in g["arcs"]]}
        else:
            continue
        out.append({"properties": g["properties"], "geometry": geom})
    return out


def cshapes() -> list[dict]:
    if profile.blocked("cshapes"):
        raise SystemExit(f"profile {profile.NAME} blocks CShapes ({profile.CATALOGUE['cshapes']['licence']})")
    tgz = SRC / "cshapes2" / "cshapes_2.0.tar.gz"
    download(CSHAPES_URL, tgz)
    topo_path = SRC / "cshapes2" / "cshapes_2_gw.topojson"
    if not topo_path.exists():
        with tarfile.open(tgz) as t:
            topo_path.write_bytes(lzma.decompress(t.extractfile(CSHAPES_TOPO).read()))
    feats = topo_features(json.loads(topo_path.read_text()))
    lo, hi = f"{Y0:04d}-01-01", f"{Y1:04d}-12-31"
    # {"source": "cshapes", "carry_to": 2026}: the borders on CShapes' last day carried forward unchanged
    carry = next((b.get("carry_to") for b in CFG.get("borders", []) if isinstance(b, dict) and b.get("source") == "cshapes"), None)
    last = max(f["properties"]["end"] for f in feats)
    out = []
    for f in feats:
        p = f["properties"]
        carried = bool(carry) and p["end"] == last
        if carried:
            p = {**p, "end": f"{carry:04d}-12-31"}
        if p["end"] < lo or p["start"] > hi:
            continue
        g = shapely.make_valid(shape(f["geometry"]))
        if not g.intersects(WINDOW):
            continue
        g = polys(g.intersection(WINDOW).simplify(TOL))
        if g.is_empty:
            continue
        out.append({"type": "Feature", "geometry": mapping(shapely.set_precision(g, 1e-4)), "properties": {
            "name": p["country_name"], "gwcode": p["gwcode"], "start": p["start"], "end": p["end"],
            "status": p["status"], "owner": int(p["owner"]) if str(p["owner"]).lstrip("-").isdigit() else None,
            "b_def": p["b_def"], "capname": p["capname"], "source_id": "cshapes2", **({"carried_from": last} if carried else {})}})
    return out


# ------------------------------------------------------------------ Cliopatria

def cliopatria() -> list[dict]:
    z = SRC / "cliopatria" / "cliopatria.geojson.zip"
    download(CLIO_URL, z, CLIO_SHA256)
    with zipfile.ZipFile(z) as zf:
        d = json.loads(zf.read(next(n for n in zf.namelist() if n.endswith(".geojson"))))
    opt = next((b for b in CFG.get("borders", []) if isinstance(b, dict) and b.get("source") == "cliopatria"), {})
    carry, drop = opt.get("carry_to"), set(opt.get("drop", []))
    last = max(f["properties"]["ToYear"] for f in d["features"])
    out = []
    for f in d["features"]:
        p = f["properties"]
        # composite rows "(British Empire)" are unions of their member rows: keep the members
        if p["Type"] != "POLITY" or not f["geometry"] or p["Name"].startswith("(") or p["Name"] in drop:
            continue
        carried = bool(carry) and p["ToYear"] == last
        if carried:
            p = {**p, "ToYear": carry}
        if p["ToYear"] < Y0 or p["FromYear"] > Y1:
            continue
        g = shapely.make_valid(shape(f["geometry"]))
        if not g.intersects(WINDOW):
            continue
        g = polys(g.intersection(WINDOW).simplify(TOL))
        if g.is_empty:
            continue
        out.append({"type": "Feature", "geometry": mapping(shapely.set_precision(g, 1e-4)), "properties": {
            "name": p["Name"], "wikidata": p["Wikidata"] or None, "from": p["FromYear"], "to": p["ToYear"],
            "member_of": (p["MemberOf"] or "").strip("()") or None, "wikipedia": p["Wikipedia"] or None,
            "source_id": "cliopatria", **({"carried_from": last} if carried else {})}})
    return out


def polys(g):
    if g.geom_type in ("Polygon", "MultiPolygon"):
        return g
    ps = [x for x in getattr(g, "geoms", []) if x.geom_type in ("Polygon", "MultiPolygon")]
    return shapely.unary_union(ps) if ps else shapely.Polygon()


def main() -> None:
    names = [b if isinstance(b, str) else b["source"] for b in CFG.get("borders", [])]
    prov = {}
    for name, fn, path in (("cshapes", cshapes, SRC / "cshapes2" / "cshapes_2.0.tar.gz"),
                           ("cliopatria", cliopatria, SRC / "cliopatria" / "cliopatria.geojson.zip")):
        if name not in names:
            continue
        feats = fn()
        write_json(SCACHE / "geo" / f"{'cshapes2' if name == 'cshapes' else name}.geojson",
                   {"type": "FeatureCollection", "features": feats})
        prov[name] = {"file": path.name, "sha256": sha256(path), "features": len(feats)}
        print(SCENE, name, len(feats), "features", flush=True)
    write_json(SCACHE / "borders.json", prov)


if __name__ == "__main__":
    main()
