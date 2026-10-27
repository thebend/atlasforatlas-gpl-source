"""Shared paths, download and geometry helpers for the North America source data.

Raw downloads go to <CACHE>/scenes/north-america/raw/, converted GeoJSON to .../geo/, where CACHE is
etl/common.CACHE (env ATLAS_CACHE, default app/.cache). Hand-curated inputs that no
script can derive live in app/sources/north-america/ (committed).
"""
from __future__ import annotations

import json
import os
import shutil
import time
import urllib.request
import zipfile
from pathlib import Path

from shapely import set_precision
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, box, mapping
from shapely.validation import make_valid

from etl import common
from etl import shp  # noqa: F401  etl/shp.py, re-exported for the converters

BASE = common.CACHE / "scenes" / "north-america"
RAW = BASE / "raw"
GEO = BASE / "geo"
CURATED = common.PROTO / "sources" / "north-america"
WINDOW = box(-170, 7, -50, 75)  # lon/lat window
UA = common.UA


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- downloads

def download(url: str, dest: Path, *, headers: dict | None = None, pause: float = 1.0,
             retries: int = 4, timeout: int = 300) -> Path:
    """Fetch url to dest unless dest already exists (atomic: written to .part, then renamed)."""
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    hdrs = {"User-Agent": UA, **(headers or {})}
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f, 1 << 20)
            break
        except Exception as ex:  # noqa: BLE001 - network errors of every kind get a retry
            log("  retry", attempt + 1, url, ex)
            time.sleep(5 * (attempt + 1))
    else:
        raise SystemExit(f"download failed: {url}")
    os.replace(tmp, dest)
    log("  got", dest.relative_to(BASE), dest.stat().st_size, "bytes")
    time.sleep(pause)
    return dest


def get_json(url: str, dest: Path, **kw):
    return json.loads(download(url, dest, **kw).read_bytes())


def unzip(zpath: Path, outdir: Path, sentinel: str) -> Path:
    """Extract zpath into outdir unless outdir/sentinel exists. Rejects absolute or '..' member paths."""
    if (outdir / sentinel).exists():
        return outdir
    outdir.mkdir(parents=True, exist_ok=True)
    root = outdir.resolve()
    with zipfile.ZipFile(zpath) as z:
        for m in z.infolist():
            target = (outdir / m.filename).resolve()
            if not str(target).startswith(str(root) + os.sep) and target != root:
                raise SystemExit(f"unsafe path in {zpath.name}: {m.filename}")
        z.extractall(outdir)
    if not (outdir / sentinel).exists():
        raise SystemExit(f"{zpath.name}: expected {sentinel} after extraction")
    return outdir


# ---------------------------------------------------------------- geometry

def signed_area(ring):
    a = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        a += x1 * y2 - x2 * y1
    return a / 2


def rings_to_geom(rings, outer_cw=True):
    """Assemble ESRI-style rings (outer=clockwise, holes=counter-clockwise) into a (Multi)Polygon."""
    outers, holes = [], []
    for r in rings:
        if len(r) < 4:
            continue
        a = signed_area(r)
        if a == 0:
            continue
        is_outer = (a < 0) if outer_cw else (a > 0)
        (outers if is_outer else holes).append(r)
    polys = [Polygon(o) for o in outers]
    polys = [p if p.is_valid else make_valid(p) for p in polys]
    for h in holes:
        hp = Polygon(h)
        for i, p in enumerate(polys):
            if p.contains(hp.representative_point()):
                polys[i] = p.difference(hp)
                break
    return MultiPolygon([q for p in polys for q in _polys(p)])


def _polys(g):
    if g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    if isinstance(g, MultiPolygon):
        return list(g.geoms)
    if isinstance(g, GeometryCollection):
        return [q for x in g.geoms for q in _polys(x)]
    return []


def crop(geom, grid=1e-5):
    """Clip to WINDOW, repair, keep polygons only, snap to a ~1 m grid. Returns None if empty."""
    if geom is None or geom.is_empty:
        return None
    if not geom.is_valid:
        geom = make_valid(geom)
    g = geom.intersection(WINDOW)
    ps = _polys(g)
    if not ps:
        return None
    g = MultiPolygon(ps) if len(ps) > 1 else ps[0]
    g = set_precision(g, grid)
    ps = _polys(g)
    if not ps:
        return None
    return MultiPolygon(ps) if len(ps) > 1 else ps[0]


def feature(geom, **props):
    return {"type": "Feature", "properties": props, "geometry": mapping(geom)}


def write_fc(path: Path, feats):
    path.parent.mkdir(parents=True, exist_ok=True)
    fc = {"type": "FeatureCollection", "features": feats}
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(fc, ensure_ascii=False, separators=(",", ":")))
    os.replace(tmp, path)
    return len(feats)


def ymd(s: str):
    """'18670330' -> '1867-03-30'; leaves 'YYYY' / 'YYYY-MM' alone."""
    s = str(s).strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s
