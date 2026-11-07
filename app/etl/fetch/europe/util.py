"""Shared paths, downloads and geometry helpers for the Europe 1910-1950 source data.

Raw downloads go to <CACHE>/scenes/europe/raw/ (borders) and .../divisions/raw/ (provinces);
converted files to .../geo/, .../divisions/ and the scene folder itself. CACHE is
etl/common.CACHE (env ATLAS_CACHE, default app/.cache). Hand-curated inputs
that no script can derive live in app/sources/europe/ (committed).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path

import numpy as np
from shapely.geometry import box
from shapely.ops import transform

from etl import common, net

BASE = common.CACHE / "scenes" / "europe"
RAW = BASE / "raw"
GEO = BASE / "geo"
DIV = BASE / "divisions"
DIV_RAW = DIV / "raw"
CURATED = common.PROTO / "sources" / "europe"
WINDOW = box(-25, 33, 45, 72)  # lon -25..45, lat 33..72 (the scene bbox)


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- files

def write_text(path: Path, text: str) -> None:
    """Atomic write (tmp + rename) so an interrupted run never leaves a truncated output."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def dump(path: Path, obj, **kw) -> None:
    write_text(path, json.dumps(obj, **kw))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def retrieved(path: Path) -> str:
    """Local calendar date a cached download was fetched (its mtime)."""
    return dt.date.fromtimestamp(path.stat().st_mtime).isoformat()


# ---------------------------------------------------------------- downloads

def download(url: str, dest: Path, *, pause: float = 1.0, retries: int = 4, timeout: int = 600) -> Path:
    """Fetch url to dest unless dest already exists (written to .part, then renamed)."""
    if dest.exists():
        return dest
    try:
        net.download(url, dest, timeout=timeout, delay=pause, tries=retries, backoff=10, log=log)
    except Exception as ex:  # noqa: BLE001
        raise SystemExit(f"download failed: {url}: {ex}") from ex
    log("  got", dest.relative_to(BASE), dest.stat().st_size, "bytes")
    return dest


OVERPASS = "https://overpass-api.openhistoricalmap.org/api/interpreter"
OVERPASS_GAP = 6.0          # seconds between queries (OHM's shared server; >= 5 s as agreed)


def overpass(query: str, *, timeout: int = 400, retries: int = 4) -> bytes:
    """POST one Overpass QL query to the OpenHistoricalMap server, politely spaced, with backoff."""
    try:
        # an HTML error page or a truncated body is a failure (check)
        return net.fetch(OVERPASS, data={"data": query}, timeout=timeout, delay=OVERPASS_GAP, tries=retries, backoff=30,
                         check=json.loads, log=log)
    except Exception as ex:  # noqa: BLE001
        raise SystemExit("overpass query failed after retries:\n" + query[:300]) from ex


# ---------------------------------------------------------------- geometry

R_E = 6371.0088


def laea(x, y):
    """Lambert azimuthal equal-area centred on 10E 52N, in km (for areas)."""
    lon = np.radians(x)
    lat = np.radians(y)
    l0, p0 = math.radians(10), math.radians(52)
    k = np.sqrt(2 / (1 + np.sin(p0) * np.sin(lat) + np.cos(p0) * np.cos(lat) * np.cos(lon - l0)))
    return (R_E * k * np.cos(lat) * np.sin(lon - l0),
            R_E * k * (np.cos(p0) * np.sin(lat) - np.sin(p0) * np.cos(lat) * np.cos(lon - l0)))


def to_km(g):
    return transform(laea, g)


def km2(g) -> float:
    return 0.0 if g.is_empty else to_km(g).area


def clean(g):
    return g if g.is_valid else g.buffer(0)
