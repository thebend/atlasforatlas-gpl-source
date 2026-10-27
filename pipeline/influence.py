"""Influence engine v1: cost-distance areas of control, Sikh Empire ~1839 demo.

Not dot-connecting: each grid cell is assigned to the power that reaches it
cheapest over a friction surface built from real inputs. Borders emerge where
influences meet -- bending around mountains, stopping at rivers and treaties.

Inputs (all modern, verifiable, documented below -- NOT historical claims):
  - elevation: AWS Terrarium DEM tiles (z8; deccan z7), PUBLIC, no key;
    fetched on first use into data/dem/.
  - rivers/roads/deserts: hand polylines of MODERN physical geography
    (river courses shift over centuries -- historical courses are a known
    refinement; mountains at 5km cells are stable on human timescales).
  - control points + weights: researched (Sikh anchors) / conventional.
  - era constants: march rates, control thresholds (stated, adjustable).

Model: base 0.2 days per 0.05-degree cell (~25 km/day plains infantry),
slope + altitude multipliers (Tobler-flavored), river barriers x3.5,
Grand Trunk Road corridor x0.45, desert x2.0, Sutlej treaty segment BLOCKED
for Sikh sources (Treaty of Amritsar 1809, hard edge), power head-starts
(1-w)*8 days. Controlled <=10 days, contested 10-16d or <20% margin.

Run: python3 pipeline/influence.py   (needs numpy + PIL; ~1-2 min)
Writes: data/source_samples/engine_sikh_1839.geojson (deccan: engine_maratha_1800)
"""
from __future__ import annotations

import heapq
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
DEM = ROOT / "data" / "dem"

LON0, LON1, LAT0, LAT1, STEP = 69.0, 80.0, 28.0, 36.0, 0.05
NX, NY = int(round((LON1 - LON0) / STEP)), int(round((LAT1 - LAT0) / STEP))
DEM_Z = 8
OUT_FILE = "engine_sikh_1839.geojson"
REGION_RIVERS = None
REGION_DESERTS = None
REGION_ROAD = None
REGION_TREATY = None
REGION_CROSSINGS = None
REGION_POWERS = None
REGION_DATES = None
REGION_END = None


def set_region(name: str) -> None:
    """Swap module inputs per region; Punjab values stay the defaults."""
    global LON0, LON1, LAT0, LAT1, STEP, NX, NY, DEM_Z, OUT_FILE
    global REGION_RIVERS, REGION_DESERTS, REGION_ROAD, REGION_TREATY
    global REGION_CROSSINGS, REGION_POWERS, REGION_DATES, REGION_END
    if name == "deccan":
        LON0, LON1, LAT0, LAT1, STEP = 68.0, 87.0, 10.0, 29.0, 0.1
        NX, NY = int(round((LON1 - LON0) / STEP)), int(round((LAT1 - LAT0) / STEP))
        DEM_Z = 7
        OUT_FILE = "engine_maratha_1800.geojson"
        REGION_RIVERS = {
            "narmada": [(72.5, 22.2), (73.5, 21.9), (74.5, 21.8), (75.5, 21.8), (76.5, 21.9), (77.5, 22.0), (78.5, 22.1), (79.5, 22.2), (80.0, 22.3)],
            "tapti": [(72.8, 21.1), (74.0, 21.0), (75.5, 21.1), (76.5, 21.2)],
            "godavari": [(73.6, 19.9), (75.0, 19.8), (76.5, 19.5), (78.0, 18.9), (79.5, 18.3), (81.0, 17.5), (82.3, 16.9)],
            "krishna": [(73.8, 17.9), (75.0, 17.3), (76.5, 16.8), (78.0, 16.2), (79.5, 16.0), (80.5, 15.9)],
        }
        REGION_DESERTS = [[(69.5, 24.5), (71.5, 24.0), (73.0, 25.5), (72.5, 27.5), (70.5, 27.5), (69.0, 26.0)]]
        REGION_ROAD = None
        REGION_TREATY = []
        REGION_CROSSINGS = []
        REGION_POWERS = [
            ("Pune", 73.855, 18.521, 1.0, "maratha", 1728, "direct"),
            ("Satara", 74.006, 17.688, 0.4, "maratha", 1707, "direct"),
            ("Gwalior", 78.1775, 26.2125, 0.8, "maratha", 1780, "direct"),
            ("Ujjain", 75.78, 23.18, 0.6, "maratha", 1760, "direct"),
            ("Delhi", 77.21, 28.66, 0.6, "maratha", 1771, "direct", 1803),
            ("Delhi", 77.21, 28.66, 0.7, "british", 1803, "direct"),
            ("Indore", 75.855, 22.719, 0.6, "maratha", 1733, "direct"),
            ("Vadodara", 73.2, 22.3, 0.55, "maratha", 1730, "direct"),
            ("Vadodara", 73.2, 22.3, 0.5, "british", 1802, "tributary"),
            ("Pune", 73.855, 18.521, 0.5, "british", 1802, "tributary"),
            ("Nagpur", 79.08, 21.15, 0.6, "maratha", 1743, "direct"),
            ("Cuttack", 85.79, 20.52, 0.3, "maratha", 1751, "tributary", 1803),
            ("Cuttack", 85.79, 20.52, 0.6, "british", 1803, "direct"),
            ("Jhansi", 78.57, 25.45, 0.3, "maratha", 1742, "tributary"),
            ("Nashik", 73.79, 20.0, 0.4, "maratha", 1707, "direct"),
            ("Hyderabad", 78.47, 17.36, 0.5, "nizam", 1724, "direct"),
            ("Mumbai", 72.88, 19.08, 0.7, "british", 1668, "direct"),
            ("Chennai", 80.28, 13.08, 0.7, "british", 1640, "direct"),
            ("Kolkata", 88.37, 22.57, 0.7, "british", 1690, "direct"),
            ("Jaipur", 75.8, 26.9, 0.3, "rajput", 1727, "direct"),
            # Kutch: Jadeja Rajput state, independent till the 1815-19
            # settlements -- no treaty slice, no nearby point, hence the
            # west-Kutch double gap. Rajput side, Bhuj founded 1510.
            ("Bhuj", 69.67, 23.25, 0.4, "rajput", 1510, "direct"),
            ("Seringapatam", 76.704, 12.414, 0.85, "mysore", 1700, "direct", 1799),
            ("Mysore", 76.653, 12.309, 0.5, "mysore", 1700, "direct", 1799),
            ("Bangalore", 77.592, 12.979, 0.5, "mysore", 1700, "direct", 1799),
            # 1799 Partition of Mysore succession chain (treaty-grade): Gooty
            # + Gurramkonda districts were Mysore-held till the fall, allotted
            # to the Nizam in 1799, ceded with the other Ceded Districts
            # (Bellary, Anantapur, Cuddapah, Kurnool) to the Company in 1800.
            # Without this chain the Anantapur gap is nobody's land forever.
            # Band-granularity note: Nizam holds render through the 1800-1802
            # band (until 1801), overlapping British 1800 arrivals as genuine
            # transition contested rather than a hard 1800 cut.
            ("Mysore", 76.653, 12.309, 0.4, "mysore", 1799, "tributary"),
            ("Gooty", 77.65, 15.12, 0.5, "mysore", 1775, "direct", 1799),
            ("Gooty", 77.65, 15.12, 0.45, "nizam", 1799, "direct", 1801),
            ("Cuddapah", 78.83, 14.47, 0.45, "nizam", 1799, "direct", 1801),
            ("Bellary", 76.93, 15.14, 0.6, "british", 1800, "direct"),
            ("Cuddapah", 78.83, 14.47, 0.55, "british", 1800, "direct"),
        ]
        REGION_DATES = [1798, 1800, 1803, 1805]
        REGION_END = 1818

# ---------------------------------------------------------------- inputs
# Modern river courses (coarse, named, verifiable). Historical courses
# (notably the Indus/Sutlej avulsions) are a documented refinement.
RIVERS = {
    "indus": [(73.0, 35.0), (72.4, 34.2), (72.24, 33.9), (71.7, 32.8), (71.2, 31.9), (70.9, 31.0), (70.5, 29.5), (70.3, 28.5)],
    "jhelum": [(74.8, 34.1), (73.9, 34.3), (73.47, 34.37), (73.3, 33.8), (73.6, 33.2), (73.73, 32.93), (73.0, 32.0), (72.5, 31.6), (72.15, 31.15)],
    "chenab": [(75.77, 33.3), (75.3, 32.9), (74.9, 32.5), (74.5, 32.0), (74.0, 31.6), (73.0, 31.3), (72.15, 31.15)],
    "ravi": [(76.5, 32.3), (75.8, 32.0), (75.0, 31.9), (74.5, 31.75), (74.0, 31.5), (73.4, 31.2), (73.0, 30.9)],
    "beas": [(77.2, 32.0), (76.5, 31.8), (75.8, 31.6), (75.2, 31.4), (74.9, 31.15)],
    "sutlej": [(78.5, 32.0), (77.5, 31.7), (76.9, 31.3)] + [[76.563, 31.149], [76.561, 31.129], [76.569, 31.11], [76.58, 31.091], [76.563, 31.079], [76.548, 31.064], [76.531, 31.051], [76.527, 31.03], [76.539, 31.014], [76.529, 30.996], [76.51, 30.985], [76.484, 30.982], [76.462, 30.982], [76.441, 30.983], [76.422, 30.972], [76.404, 30.963], [76.383, 30.958], [76.364, 30.967], [76.348, 30.98], [76.329, 30.988], [76.309, 30.994], [76.292, 31.007], [76.272, 31.014], [76.252, 31.012], [76.233, 31.004], [76.213, 31.011], [76.193, 31.003], [76.173, 30.997], [76.153, 30.99], [76.132, 30.986], [76.112, 30.993], [76.092, 30.988], [76.071, 30.999], [76.047, 31.0], [76.025, 31.0], [75.998, 31.009], [75.978, 31.011], [75.956, 31.007], [75.933, 31.007], [75.915, 31.017], [75.889, 31.013], [75.869, 31.004], [75.851, 30.992], [75.83, 30.996], [75.809, 30.998], [75.789, 30.996], [75.769, 30.99], [75.75, 30.998], [75.732, 31.011], [75.712, 31.012], [75.703, 30.994], [75.688, 30.977], [75.668, 30.979], [75.648, 30.98], [75.628, 30.981], [75.608, 30.975], [75.588, 30.974], [75.568, 30.975], [75.548, 30.977], [75.528, 30.973], [75.508, 30.982], [75.492, 30.968], [75.473, 30.961], [75.452, 30.967], [75.434, 30.976], [75.413, 30.973], [75.393, 30.982], [75.375, 30.992], [75.355, 30.994], [75.336, 31.004], [75.322, 31.02], [75.302, 31.023], [75.281, 31.032], [75.261, 31.036], [75.241, 31.037], [75.221, 31.038], [75.199, 31.04], [75.19, 31.059], [75.175, 31.073], [75.155, 31.077], [75.142, 31.094], [75.128, 31.109], [75.121, 31.129], [75.102, 31.136], [75.08, 31.137], [75.061, 31.13], [75.044, 31.141], [75.024, 31.139], [75.002, 31.144], [74.952, 31.149], [74.935, 31.138], [74.915, 31.134], [74.895, 31.14], [74.847, 31.149], [74.828, 31.14], [74.813, 31.126], [74.793, 31.128], [74.77, 31.13], [74.75, 31.124], [74.735, 31.11], [74.722, 31.094], [74.711, 31.077], [74.691, 31.071], [74.675, 31.086], [74.658, 31.075], [74.642, 31.087]] + [(74.0, 30.5), (73.2, 30.0), (72.0, 29.6), (71.0, 29.3), (70.5, 29.0)],
    "kabul": [(69.18, 34.53), (70.0, 34.4), (70.9, 34.0), (71.8, 33.95), (72.24, 33.9)],
}
# Treaty of Amritsar 1809: Sutlej line Rupar->Ferozepur, impassable southward for Sikh power.
# The 1809 treaty fixed the SUTLEJ itself as the boundary -- so this follows
# the real river course (OSM waterway relation 325142, modern factual course;
# river migrations since 1809 are a documented refinement, far smaller than
# the old straight chord's ~20km deviations).
TREATY_SEG = [[76.563, 31.149], [76.561, 31.129], [76.569, 31.11], [76.58, 31.091], [76.563, 31.079], [76.548, 31.064], [76.531, 31.051], [76.527, 31.03], [76.539, 31.014], [76.529, 30.996], [76.51, 30.985], [76.484, 30.982], [76.462, 30.982], [76.441, 30.983], [76.422, 30.972], [76.404, 30.963], [76.383, 30.958], [76.364, 30.967], [76.348, 30.98], [76.329, 30.988], [76.309, 30.994], [76.292, 31.007], [76.272, 31.014], [76.252, 31.012], [76.233, 31.004], [76.213, 31.011], [76.193, 31.003], [76.173, 30.997], [76.153, 30.99], [76.132, 30.986], [76.112, 30.993], [76.092, 30.988], [76.071, 30.999], [76.047, 31.0], [76.025, 31.0], [75.998, 31.009], [75.978, 31.011], [75.956, 31.007], [75.933, 31.007], [75.915, 31.017], [75.889, 31.013], [75.869, 31.004], [75.851, 30.992], [75.83, 30.996], [75.809, 30.998], [75.789, 30.996], [75.769, 30.99], [75.75, 30.998], [75.732, 31.011], [75.712, 31.012], [75.703, 30.994], [75.688, 30.977], [75.668, 30.979], [75.648, 30.98], [75.628, 30.981], [75.608, 30.975], [75.588, 30.974], [75.568, 30.975], [75.548, 30.977], [75.528, 30.973], [75.508, 30.982], [75.492, 30.968], [75.473, 30.961], [75.452, 30.967], [75.434, 30.976], [75.413, 30.973], [75.393, 30.982], [75.375, 30.992], [75.355, 30.994], [75.336, 31.004], [75.322, 31.02], [75.302, 31.023], [75.281, 31.032], [75.261, 31.036], [75.241, 31.037], [75.221, 31.038], [75.199, 31.04], [75.19, 31.059], [75.175, 31.073], [75.155, 31.077], [75.142, 31.094], [75.128, 31.109], [75.121, 31.129], [75.102, 31.136], [75.08, 31.137], [75.061, 31.13], [75.044, 31.141], [75.024, 31.139], [75.002, 31.144], [74.952, 31.149], [74.935, 31.138], [74.915, 31.134], [74.895, 31.14], [74.847, 31.149], [74.828, 31.14], [74.813, 31.126], [74.793, 31.128], [74.77, 31.13], [74.75, 31.124], [74.735, 31.11], [74.722, 31.094], [74.711, 31.077], [74.691, 31.071], [74.675, 31.086], [74.658, 31.075], [74.642, 31.087]]
# Fordable crossings exempt from the river barrier (Attock: the Indus crossing
# armies actually used; the barrier table, not the river, decides hardness).
CROSSINGS = [(72.24, 33.9)]
# Grand Trunk Road corridor (Delhi->Peshawar axis, ancient route).
GT_ROAD = [(77.21, 28.61), (76.98, 29.39), (76.78, 30.38), (75.85, 30.9), (75.58, 31.33), (74.87, 31.63), (74.35, 31.55), (74.19, 32.16), (74.12, 32.44), (73.73, 32.93), (73.05, 33.6), (72.4, 33.9), (71.98, 34.0), (71.58, 34.01)]
# Approximate desert extents (modern landcover; century-scale drift noted).
DESERTS = [
    [(71.0, 29.8), (72.0, 29.8), (72.3, 30.8), (72.0, 31.8), (71.2, 31.8), (70.8, 30.8)],
    [(70.0, 28.5), (72.5, 28.5), (73.5, 29.0), (73.8, 29.5), (72.0, 29.5), (70.5, 29.0)],
]
# (lon, lat, weight, side). Sikh weights: capital > garrison towns > forts >
# tributaries. Neighbors conventional. Kabul/Kandahar/Sindh outside grid noted.
# (lon, lat, weight, side, since, authority). Authority is evidence class,
# not strength: direct = administered/garrisoned (Lahore, Peshawar fort,
# Kangra annexed); tributary = acknowledged rule through intermediaries
# (Jammu Dogras, Ladakh). Presence comes from cost; authority from documents.
# Annexation/conquest dates from the anchor research; a point only projects
# power in runs on/after its year. Treaty cantonments are hard presence:
# Ludhiana (1809) firmly British; Ferozepur (1834) sits exactly at parity ->
# contested, the 1845 tripwire.
POWERS = [
    ("Lahore", 74.35, 31.55, 1.0, "sikh", 1799, "direct"), ("Amritsar", 74.87, 31.63, 0.55, "sikh", 1799, "direct"),
    ("Peshawar", 71.58, 34.01, 0.7, "sikh", 1834, "direct"), ("Multan", 71.5, 30.2, 0.6, "sikh", 1818, "direct"),
    ("Srinagar", 74.81, 34.08, 0.55, "sikh", 1819, "direct"), ("Attock", 72.24, 33.9, 0.5, "sikh", 1813, "direct"),
    ("Kangra", 76.27, 32.1, 0.4, "sikh", 1809, "direct"), ("Jamrud", 71.4, 34.0, 0.35, "sikh", 1837, "direct"),
    ("Jammu", 74.86, 32.73, 0.3, "sikh", 1822, "tributary"), ("Mankera", 71.44, 31.38, 0.3, "sikh", 1822, "direct"),
    ("Dera Ismail Khan", 71.1, 31.83, 0.3, "sikh", 1832, "direct"), ("Kishtwar", 75.77, 33.32, 0.25, "sikh", 1834, "direct"),
    ("Leh", 77.58, 34.15, 0.15, "sikh", 1835, "tributary"),
    ("Delhi", 77.21, 28.61, 0.85, "british", 1803, "direct"), ("Ludhiana", 75.85, 30.9, 0.8, "british", 1809, "direct"),
    ("Ferozepur", 74.63, 30.93, 0.7, "british", 1834, "direct"),
    ("Kabul", 69.18, 34.53, 0.45, "afghan", 1799, "direct"), ("Jalalabad", 70.45, 34.43, 0.3, "afghan", 1799, "direct"),
    ("Bahawalpur", 71.68, 29.4, 0.25, "bahawalpur", 1799, "direct"),
]
# Snapshot years: control sets change at conquest/treaty dates. Each feature
# spans [date, next date); the last holds to the First Anglo-Sikh War.
RUN_DATES = [1799, 1809, 1813, 1818, 1819, 1834, 1837, 1839]
RUN_END = 1845
TREATY_FROM = 1809

# ---------------------------------------------------------------- DEM
_tiles: dict = {}
TERRARIUM = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"


def dem_tile(z: int, x: int, y: int) -> Path:
    """data/dem/z<z>/t_<x>_<y>.png, downloaded once from AWS Terrarium."""
    p = DEM / f"z{z}" / f"t_{x}_{y}.png"
    if not p.exists():
        import urllib.request
        p.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(TERRARIUM.format(z=z, x=x, y=y),
                                     headers={"User-Agent": "OpenWorld-influence/0.1"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read()
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(body)
        tmp.replace(p)
    return p


def elev_grid() -> np.ndarray:
    N = 2 ** DEM_Z
    H = np.zeros((NY, NX))
    for ix in range(NX):
        for iy in range(NY):
            lon, lat = LON0 + (ix + 0.5) * STEP, LAT0 + (iy + 0.5) * STEP
            tx = int((lon + 180) / 360 * N)
            r = math.radians(lat)
            ty = int((1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * N)
            key = (DEM_Z, tx, ty)
            if key not in _tiles:
                p = dem_tile(DEM_Z, tx, ty)
                a = np.asarray(Image.open(p).convert("RGB")).astype(float)
                _tiles[key] = a[:, :, 0] * 256 + a[:, :, 1] + a[:, :, 2] / 256 - 32768
            arr = _tiles[key]
            fx = ((lon + 180) / 360 * N - tx) * 256
            fy = ((1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * N - ty) * 256
            H[iy, ix] = arr[max(0, min(255, int(fy))), max(0, min(255, int(fx)))]
    return H


def seg_dist(lons: np.ndarray, lats: np.ndarray, poly: list) -> np.ndarray:
    out = np.full_like(lons, 1e9)
    for (x1, y1), (x2, y2) in zip(poly[:-1], poly[1:], strict=False):
        dx, dy = x2 - x1, y2 - y1
        denom = dx * dx + dy * dy or 1e-12
        t = np.clip(((lons - x1) * dx + (lats - y1) * dy) / denom, 0, 1)
        out = np.minimum(out, np.hypot(lons - (x1 + t * dx), lats - (y1 + t * dy)))
    return out


# Unification rule: sourced treaty slices win where they exist; the heuristic
# fills the silences. Engine CONTROLLED cores inside a same-power treaty
# polygon for an overlapping year are dropped at build time (they would
# double-paint the treaty fill). Contested/fringe/points always survive:
# gradients and anchors are what treaties can't express. Sides with no OHM
# treaty slices (sikh, maratha, mysore, nizam, rajput, bahawalpur) never defer.
DEFER_TO_SOURCED = {
    "british": ["Q2001966", "Q129286", "Q2629708"],  # Company/British Raj, Punjab Province
    "afghan": ["Q1335260"],  # Emirate of Kabul
}

# Treaty-slice power map for the weak-fringe rule below. Unknown qids
# (Awadh, Rajputana, Nepal...) count as "not your side": the treaty is the
# only claim there, so a foreign band-1 fringe defers to it.
SLICE_SIDE = {
    "Q2001966": "british", "Q129286": "british", "Q2629708": "british",
    "Q2225895": "maratha", "Q1335260": "afghan",
}

_SLICES = None
def _sourced_rings():
    global _SLICES
    if _SLICES is None:
        _SLICES = {}
        try:
            b = json.loads((ROOT / "data/borders.geojson").read_text())
            for f in b.get("features", []):
                p = f.get("properties", {})
                g = f.get("geometry") or {}
                pp = g.get("coordinates") or []
                if g.get("type") == "Polygon":
                    pp = [pp]
                rings = [poly[0] for poly in pp if poly]
                _SLICES.setdefault(str(p.get("qid")), []).append(
                    (int(p.get("yearStart")), int(p.get("yearEnd")), rings,
                     str(p.get("title") or "")))
        except Exception:
            pass
    return _SLICES


# Display names for engine sides (pipeline-owned: UI reads sideName/side2Name
# props, never hardcodes these). Where a same-power treaty slice covers the
# ground, its title wins (Company Raj, not "british hold"); otherwise the
# display name + engine-estimate suffix. Codes stay in side/side2 for logic.
SIDE_DISPLAY = {
    "sikh": "Sikh Empire",
    "british": "British",
    "afghan": "Afghan",
    "bahawalpur": "Bahawalpur",
    "maratha": "Maratha Confederacy",
    "mysore": "Kingdom of Mysore",
    "nizam": "Hyderabad (Nizam)",
    "rajput": "Rajputana",
}


def _treaty_name(side, lon, lat, year):
    own = DEFER_TO_SOURCED.get(side, ())
    if not own:
        return None
    lo, la = np.array([lon]), np.array([lat])
    best = None
    for qid in own:
        for (s, e, rr, title) in _sourced_rings().get(qid, []):
            if s <= year <= e and any(bool(in_poly(lo, la, r)[0]) for r in rr):
                if best is None or s > best[0]:
                    best = (s, title)
    return best[1] if best else None


def _suppress_redundant(side: str, band: int, polys: list, y0: int, y1: int) -> list:
    own = DEFER_TO_SOURCED.get(side, ())
    rings_own: list = []
    rings_foreign: list = []
    for qid, slices in _sourced_rings().items():
        for (s, e, rr, _t) in slices:
            if s <= y1 and y0 <= e:
                if qid in own:
                    rings_own.extend(rr)
                elif SLICE_SIDE.get(qid) != side:
                    rings_foreign.extend(rr)
    if not rings_own and not (band == 1 and rings_foreign):
        return polys
    keep = []
    for ring in polys:
        cx = sum(c[0] for c in ring) / len(ring)
        cy = sum(c[1] for c in ring) / len(ring)
        lon = np.array([cx])
        lat = np.array([cy])
        if rings_own and any(bool(in_poly(lon, lat, r)[0]) for r in rings_own):
            continue
        # Weak-fringe rule (burden of proof): a band-1 spill inside somebody
        # else's treaty polygon is low-confidence noise, not debate. Strong
        # bands (2-3) and contested survive: genuine disagreement stays loud.
        # Bombay 1810 (maratha fringe over long-British treaty ground) dies;
        # Poona's maratha core and Delhi-1799 style contests are untouched.
        if band == 1 and rings_foreign and any(bool(in_poly(lon, lat, r)[0]) for r in rings_foreign):
            continue
        keep.append(ring)
    return keep

def in_poly(lons: np.ndarray, lats: np.ndarray, poly: list) -> np.ndarray:
    inside = np.zeros(lons.shape, bool)
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        cond = ((y1 > lats) != (y2 > lats)) & (lons < (x2 - x1) * (lats - y1) / (y2 - y1 + 1e-12) + x1)
        inside ^= cond
    return inside


_FCACHE = ROOT / "data" / ".friction_cache.npz"


CODE_VERSION = "v3-water-sides"

def _fingerprint() -> str:
    import hashlib
    h = hashlib.sha256()
    h.update(CODE_VERSION.encode())
    h.update(repr([REGION_RIVERS or RIVERS, GT_ROAD, REGION_DESERTS or DESERTS,
                   REGION_CROSSINGS, REGION_TREATY, TREATY_SEG, LON0, LON1, LAT0, LAT1, STEP]).encode())
    return h.hexdigest()[:16]


def friction() -> tuple[np.ndarray, np.ndarray]:
    import time as _t
    t0 = _t.perf_counter()
    fp = _fingerprint()
    if _FCACHE.exists():
        try:
            z = np.load(_FCACHE, allow_pickle=True)
            if str(z["fp"]) == fp:
                print(f"friction cache hit ({_t.perf_counter() - t0:.1f}s)", flush=True)
                return z["F"], z["treaty"]
        except Exception:
            pass
    print("loading DEM...", flush=True)
    H = elev_grid()
    xs = LON0 + (np.arange(NX) + 0.5) * STEP
    ys = LAT0 + (np.arange(NY) + 0.5) * STEP
    LONS, LATS = np.meshgrid(xs, ys)
    gy, gx = np.gradient(H, STEP, STEP)
    slope = np.hypot(gx / 111320 / np.cos(np.radians(LATS)), gy / 110540)
    F = 0.2 * (1 + 6 * slope)
    F = np.where(H > 4500, F * 12, np.where(H > 3500, F * 5, np.where(H > 2500, F * 2.5, F)))
    # Sub-sea-level (ocean tiles in-bbox, e.g. Bay of Bengal corner): land
    # power stops at water. Naval projection is a documented future factor.
    F = np.where(H < 0, F * 25, F)
    rd = np.full(LONS.shape, 1e9)
    for poly in (REGION_RIVERS or RIVERS).values():
        rd = np.minimum(rd, seg_dist(LONS, LATS, poly))
    gap = np.full(LONS.shape, 1e9)
    for cx, cy in (REGION_CROSSINGS if REGION_CROSSINGS is not None else CROSSINGS):
        gap = np.minimum(gap, np.hypot(LONS - cx, LATS - cy))
    F = np.where((rd < 0.08) & (gap >= 0.04), F * 3.5, F)
    _road = REGION_ROAD if REGION_ROAD is not None else GT_ROAD
    F = np.where(seg_dist(LONS, LATS, _road) < 0.06, F * 0.45, F)
    desert = np.zeros(LONS.shape, bool)
    for poly in (REGION_DESERTS or DESERTS):
        desert |= in_poly(LONS, LATS, poly)
    F = np.where(desert, F * 2.0, F)
    _tseg = REGION_TREATY if REGION_TREATY is not None else TREATY_SEG
    treaty = seg_dist(LONS, LATS, _tseg) < 0.03 if _tseg else np.zeros(LONS.shape, bool)
    print(f"elev {H.min():.0f}..{H.max():.0f}m; river cells {(rd < 0.08).sum()}; treaty cells {treaty.sum()}", flush=True)
    import time as _t2
    np.savez_compressed(_FCACHE, F=F, treaty=treaty, fp=np.array(fp))
    print(f"friction built in {_t2.perf_counter() - t0:.1f}s", flush=True)
    return F, treaty


# ---------------------------------------------------------------- spread
# British cantonments north of the Sutlej (treaty enclaves): power projects
# only within this radius; beyond it the treaty binds them as it binds Sikhs.
CANTONMENTS = [(75.85, 30.9), (74.63, 30.93)]
CANTON_R = 0.15


EXPLORE_CAP = 12.0


def spread(F: np.ndarray, blocks: dict, powers: list) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    best = np.full((NY, NX), 1e9)
    second = np.full((NY, NX), 1e9)
    win = np.full((NY, NX), -1, dtype=np.int16)
    win2 = np.full((NY, NX), -1, dtype=np.int16)
    for pi, _p in enumerate(powers):
        (_, lon, lat, w, side, _, _auth), _until = (_p[:7], _p[7] if len(_p) > 7 else None)
        ix = min(NX - 1, max(0, int((lon - LON0) / STEP)))
        iy = min(NY - 1, max(0, int((lat - LAT0) / STEP)))
        pq = [((1 - w) * 8.0, ix, iy)]
        seen = {}
        blocked = blocks.get(side)
        while pq:
            cost, x, y = heapq.heappop(pq)
            if (x, y) in seen:
                continue
            seen[(x, y)] = cost
            if cost < best[y, x]:
                second[y, x] = best[y, x]
                win2[y, x] = win[y, x]
                best[y, x] = cost
                win[y, x] = pi
            elif cost < second[y, x]:
                second[y, x] = cost
                win2[y, x] = pi
            if cost >= EXPLORE_CAP:
                continue
            # 8-connectivity with √2 diagonal costs: armies move diagonally.
            # The old 4-connectivity imposed a Manhattan metric whose L1 balls
            # rendered as giant geometric diamonds (the Baroda-Goa zigzag
            # soup). Octagonal fronts + terrain friction read as terrain.
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < NX and 0 <= ny < NY and (nx, ny) not in seen:
                    if blocked is not None and blocked[ny, nx]:
                        continue
                    dm = 1.41421356 if (dx and dy) else 1.0
                    heapq.heappush(pq, (cost + F[ny, nx] * dm, nx, ny))
    return best, second, win, win2


# ---------------------------------------------------------------- polygonize (marching squares)
def _dp_mask(ring: list, tol: float, mask: np.ndarray, expect_inside: bool) -> list:
    # Plain Douglas-Peucker first (fast), then a mask-oracle repair pass:
    # steering the recursion with the oracle made big rings 10-50x slower
    # (rejected long chords subdivide logarithmically-deep). Repair instead:
    # any kept edge longer than 4 cells whose midpoint leaves the expected
    # side of the mask reverts to its original subchain. Two passes max.
    # Plain DP straightens stair-steps; the oracle guarantees no kept edge
    # annexes water (or surrenders land) -- e.g. the open-sea triangle SW
    # of Kutch. Closed rings: strip the duplicate end, simplify open, reclose.
    closed = len(ring) >= 4 and ring[0] == ring[-1]
    work = ring[:-1] if closed else ring
    if len(work) < 3:
        return ring
    keep = [False] * len(work)
    keep[0] = keep[-1] = True
    stack = [(0, len(work) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = work[a][:2]
        bx, by = work[b][:2]
        dx, dy = bx - ax, by - ay
        denom = math.hypot(dx, dy) or 1e-12
        dmax, idx = 0.0, a
        for i in range(a + 1, b):
            px, py = work[i][:2]
            d = abs(dy * px - dx * py + bx * ay - by * ax) / denom
            if d > dmax:
                dmax, idx = d, i
        if dmax > tol:
            keep[idx] = True
            stack.append((a, idx))
            stack.append((idx, b))
    def chord_ok(a: int, b: int) -> bool:
        mx = (work[a][0] + work[b][0]) / 2
        my = (work[a][1] + work[b][1]) / 2
        ix = int((mx - LON0) / STEP)
        iy = int((my - LAT0) / STEP)
        if not (0 <= ix < NX and 0 <= iy < NY):
            return False
        return bool(mask[iy, ix]) == expect_inside
    for _ in range(2):
        kept = [i for i, k in enumerate(keep) if k]
        changed = False
        for j in range(len(kept) - 1):
            a, b = kept[j], kept[j + 1]
            if b - a <= 1:
                continue
            ax, ay = work[a][:2]
            bx, by = work[b][:2]
            if math.hypot(bx - ax, by - ay) / STEP <= 4:
                continue
            if chord_ok(a, b):
                continue
            for i in range(a + 1, b):
                keep[i] = True
            changed = True
        if not changed:
            break
    out = [p for p, k in zip(work, keep, strict=True) if k]
    if len(out) < 3:
        return ring
    return out + [out[0]] if closed else out


def _assemble(rings: list) -> list:
    # trace() returns flat rings: exteriors and hole boundaries mixed, with
    # no nesting. A mask loop around unheld cells (the Gulf-of-Kutch lagoon:
    # Rann column + Saurashtra coast + mainland) must cut a hole, not paint
    # a filled polygon over the sea. Big-first; each ring joins the first
    # exterior containing its centroid (skipping rings nested in an existing
    # hole -- those are islands, own polygons), else starts its own polygon.
    def _area(r) -> float:
        s = 0.0
        for i in range(len(r) - 1):
            s += r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1]
        return abs(s) / 2
    def _pip(pt, ring) -> bool:
        x, y = pt
        inside = False
        n = len(ring)
        for i in range(n):
            x1, y1 = ring[i]
            x2, y2 = ring[(i + 1) % n]
            if ((y1 > y) != (y2 > y)) and (x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1):
                inside = not inside
        return inside
    polys: list = []
    for r in sorted(rings, key=_area, reverse=True):
        cx = sum(c[0] for c in r) / len(r)
        cy = sum(c[1] for c in r) / len(r)
        for poly in polys:
            if any(_pip((cx, cy), h) for h in poly[1:]):
                continue
            if _pip((cx, cy), poly[0]):
                poly.append(r)
                break
        else:
            polys.append([r])
    return polys


def trace(mask: np.ndarray) -> list:
    h, w = mask.shape
    F = np.pad(mask.astype(float), 1)
    segs = []

    def V(y: int, x: int) -> float:
        return F[y, x]

    for y in range(1, h + 1):
        for x in range(1, w + 1):
            a, b, c, d = V(y, x), V(y, x + 1), V(y + 1, x + 1), V(y + 1, x)
            idx = (8 if a > 0.5 else 0) | (4 if b > 0.5 else 0) | (2 if c > 0.5 else 0) | (1 if d > 0.5 else 0)
            if idx in (0, 15):
                continue
            # edge midpoints in cell coords
            T, R, B, L = (x + 0.5, y), (x + 1, y + 0.5), (x + 0.5, y + 1), (x, y + 0.5)
            avg = (a + b + c + d) / 4
            table = {1: [(L, B)], 2: [(B, R)], 3: [(L, R)], 4: [(T, R)], 5: [(L, T), (B, R)] if avg > 0.5 else [(L, B), (T, R)],
                     6: [(T, B)], 7: [(L, T)], 8: [(L, T)], 9: [(T, B)], 10: [(L, B), (T, R)] if avg > 0.5 else [(L, T), (B, R)],
                     11: [(T, R)], 12: [(L, R)], 13: [(B, R)], 14: [(L, B)]}
            segs.extend(table[idx])
    # chain by shared endpoints (grid snapped)
    key = lambda p: (round(p[0], 6), round(p[1], 6))
    adj: dict = {}
    for j, (p1, p2) in enumerate(segs):
        adj.setdefault(key(p1), []).append(j)
        adj.setdefault(key(p2), []).append(j)
    used = [False] * len(segs)
    rings = []
    for j, (p1, p2) in enumerate(segs):
        if used[j]:
            continue
        used[j] = True
        ring = [p1, p2]
        while True:
            k = key(ring[-1])
            cand = [u for u in adj.get(k, []) if not used[u]]
            if not cand:
                break
            u = cand[0]
            used[u] = True
            a, b = segs[u]
            ring.append(b if key(a) == k else a)
            if key(ring[-1]) == key(ring[0]):
                break
            if len(ring) > len(segs) + 5:
                break
        if len(ring) >= 4:
            rings.append(ring)
    # grid -> lon/lat (pad offset -1), then de-jaggy with the mask oracle.
    # Ring type comes from the mask itself: an exterior's centroid sits in
    # won cells, a hole's in unheld ones (crescents may misread -- worst case
    # they just skip smoothing, never corrupt).
    tol = STEP * 0.6
    out = []
    for r in rings:
        cx = sum(p[0] for p in r) / len(r) - 1
        cy = sum(p[1] for p in r) / len(r) - 1
        ix, iy = int(round(cx)), int(round(cy))
        expect_inside = bool(mask[iy, ix]) if (0 <= ix < NX and 0 <= iy < NY) else True
        ring = [[LON0 + (px - 1) * STEP, LAT0 + (py - 1) * STEP] for px, py in r]
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        out.append(_dp_mask(ring, tol, mask, expect_inside))
    return out


def main(region: str = "punjab") -> int:
    set_region(region)
    F, treaty = friction()
    _powers = REGION_POWERS or POWERS
    _dates = REGION_DATES or RUN_DATES
    _end = REGION_END or RUN_END
    _tseg = REGION_TREATY if REGION_TREATY is not None else TREATY_SEG
    xs = LON0 + (np.arange(NX) + 0.5) * STEP
    ys = LAT0 + (np.arange(NY) + 0.5) * STEP
    LONS, LATS = np.meshgrid(xs, ys)
    # Land power stops at water: sea cells (H<0) can never be won, so zones
    # can't bridge gulfs (the Surat-Baroda sea triangle). Naval projection
    # stays a documented future factor. Tiles are cached by friction().
    LAND = elev_grid() >= 0
    # Masks may not touch the domain edge: marching squares closes rings
    # along the boundary, and a straight boundary run between two mask
    # stretches encloses never-won sea (the Rann-column slide filled open
    # Arabian Sea). One arbitrary-cutoff cell is a fair price; sea lagoons
    # fully enclosed by mask still cut out as holes via _assemble.
    INNER = np.ones((NY, NX), bool)
    INNER[0, :] = INNER[-1, :] = INNER[:, 0] = INNER[:, -1] = False
    near_canton = np.zeros(LONS.shape, bool)
    for cx, cy in CANTONMENTS:
        near_canton |= (np.hypot(LONS - cx, LATS - cy) < CANTON_R)
    # Treaty binds line-SIDES within its lon range (not a band): Sikhs stay
    # north, British stay south except cantonment enclaves. Beyond the segment
    # ends (hills/desert) the frontier is genuinely ambiguous -- left open.
    # Side tested against the nearest treaty node (the course meanders).
    txs = np.array([pt[0] for pt in TREATY_SEG])
    tys = np.array([pt[1] for pt in TREATY_SEG])
    best = np.full(LONS.shape, 1e18)
    tlat = np.zeros(LONS.shape)
    for tx, ty in zip(txs, tys, strict=True):
        d2 = (LONS - tx) ** 2 + (LATS - ty) ** 2
        m = d2 < best
        best[m] = d2[m]
        tlat[m] = ty
    in_rng = (LONS >= txs.min()) & (LONS <= txs.max())
    sikh_block = in_rng & (LATS < tlat)
    brit_base = in_rng & (LATS > tlat) & ~near_canton
    feats = []
    for ri, rd in enumerate(_dates):
        end = (_dates[ri + 1] - 1) if ri + 1 < len(_dates) else _end
        def _active(x, rd=rd):
            if not (x[5] <= rd):
                return False
            until = x[7] if len(x) > 7 else None
            return until is None or rd < until
        active = [x for x in _powers if _active(x)]
        blocks = {}
        if _tseg and rd >= TREATY_FROM:
            blocks = {"sikh": sikh_block, "british": brit_base}
        import time as _t3
        _ts = _t3.perf_counter()
        best, second, win, win2 = spread(F, blocks, active)
        _dt = _t3.perf_counter() - _ts
        sides = [x[4] for x in active]
        auths = [x[6] for x in active]
        warr = np.array(sides)[np.maximum(win, 0)]
        aarr = np.array(auths)[np.maximum(win, 0)]
        s2arr = np.array(sides)[np.maximum(win2, 0)]
        margin = (second - best) / np.maximum(best, 1e-6)
        # Burden of proof on doubt: a close race between two control points
        # of the SAME side is model noise, not practical debate -- contested
        # needs a different side running second (Delhi 1799 maratha/british
        # survives; same-side fringes don't).
        w2ok = (win2 >= 0) & (np.array(sides)[np.maximum(win2, 0)] != warr)
        contested = (win >= 0) & (best <= 10) & (margin < 0.2) & w2ok

        def majority(mask: Any, _aarr: Any = aarr) -> str:
            vals, counts = np.unique(_aarr[mask], return_counts=True)
            return str(vals[int(np.argmax(counts))]) if len(vals) else "direct"

        n_side0 = 0
        _sides_sorted = sorted(set(sides))
        for side in _sides_sorted:
            mine = (win >= 0) & (warr == np.array(side)) & ~contested & LAND & INNER
            for band, lim in ((3, 4.0), (2, 7.0), (1, 10.0)):
                m = mine & (best <= lim)
                polys = _suppress_redundant(side, band, trace(m), rd, end)
                if polys:
                    _cx = sum(c[0] for _r in polys for c in _r) / max(1, sum(len(_r) for _r in polys))
                    _cy = sum(c[1] for _r in polys for c in _r) / max(1, sum(len(_r) for _r in polys))
                    _polity = _treaty_name(side, _cx, _cy, (rd + end) // 2) or SIDE_DISPLAY.get(side, side)
                    feats.append({"type": "Feature",
                                  "geometry": {"type": "MultiPolygon", "coordinates": _assemble(polys)},
                                  "properties": {"title": f"{_polity} -- control ~{rd} (engine estimate)",
                                                 "featureType": "border", "side": side,
                                                 "sideName": SIDE_DISPLAY.get(side, side), "zone": "controlled",
                                                 "band": band, "authority": majority(m),
                                                 "licenseClass": "engine-computed",
                                                 "yearStart": rd, "yearEnd": end,
                                                 "start_date": str(rd), "end_date": str(end),
                                                 "provenance": {"source": "engine-computed",
                                                                "method": "cost-distance over DEM+rivers+road+treaty"}}})
            if side == _sides_sorted[0]:
                n_side0 = int((mine & (best <= 10)).sum())
            cm = contested & (warr == np.array(side)) & LAND & INNER
            # Partition the doubt by WHO it's with: cells grouped by
            # runner-up side, each group traced separately, so one polygon
            # never claims two pairings (Mysore's 1799 frontier splits into
            # mysore×british in the west, mysore×nizam in the north).
            # Abutting groups share real polygon edges, not votes.
            for run2v in sorted(set(s2arr[cm].tolist())):
                run2 = str(run2v)
                sub = cm & (s2arr == run2v)
                polys = trace(sub)
                if not polys:
                    continue
                polys = _suppress_redundant(side, 0, polys, rd, end)
                if not polys:
                    continue
                _d1, _d2 = SIDE_DISPLAY.get(side, side), SIDE_DISPLAY.get(run2, run2)
                feats.append({"type": "Feature",
                              "geometry": {"type": "MultiPolygon", "coordinates": _assemble(polys)},
                              "properties": {"title": f"{_d1} x {_d2} -- contested ~{rd} (engine estimate)",
                                             "featureType": "border", "side": side, "side2": run2,
                                             "sideName": _d1, "side2Name": _d2, "zone": "contested",
                                             "band": 0, "authority": majority(sub),
                                             "licenseClass": "engine-computed",
                                             "yearStart": rd, "yearEnd": end,
                                             "start_date": str(rd), "end_date": str(end),
                                             "provenance": {"source": "engine-computed",
                                                            "method": "cost-distance over DEM+rivers+road+treaty"}}})
        print(f"run {rd}->{end}: {_sides_sorted[0]} cells {n_side0} (~{n_side0 * (STEP * 111) ** 2:,.0f} km2) spread {_dt:.1f}s", flush=True)
    # Timeless inputs, emitted once: control points (dots rendering) + treaty
    # edges as lines (agreed lines of control, first-class -- not area claims).
    for _p in _powers:
        name, lon, lat, w, side, since, auth = _p[:7]
        _until = _p[7] if len(_p) > 7 else _end
        feats.append({"type": "Feature",
                      "geometry": {"type": "Point", "coordinates": [lon, lat]},
                      "properties": {"title": f"{name} ({SIDE_DISPLAY.get(side, side)}, {auth})",
                                     "featureType": "border", "side": side,
                                     "sideName": SIDE_DISPLAY.get(side, side), "zone": "point",
                                     "band": 3, "authority": auth, "weight": w,
                                     "licenseClass": "engine-computed",
                                     "yearStart": since, "yearEnd": _until,
                                     "start_date": str(since), "end_date": str(_until),
                                     "provenance": {"source": "engine-computed", "method": "control point"}}})
    if _tseg:
        feats.append({"type": "Feature",
                      "geometry": {"type": "LineString", "coordinates": [list(pt) for pt in _tseg]},
                  "properties": {"title": "Treaty of Amritsar line 1809 (agreed control)",
                                 "featureType": "border", "side": "treaty", "zone": "treaty",
                                 "band": 3, "authority": "direct",
                                 "licenseClass": "engine-computed",
                                 "yearStart": TREATY_FROM, "yearEnd": _end,
                                 "start_date": str(TREATY_FROM), "end_date": str(_end),
                                 "provenance": {"source": "wikipedia treaty text",
                                                "method": "Sutlej line Rupar-Ferozepur"}}})
    out = {"type": "FeatureCollection", "features": feats}
    # Source tree, not app/static: publish.py mirrors data/ -> app/static/
    # and sweeps orphans, so anything written straight to app/static gets
    # deleted on the next publish.
    p = ROOT / "data/source_samples" / OUT_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out))
    print(f"wrote {len(feats)} features -> {p}", flush=True)
    return 0


if __name__ == "__main__":
    import sys as _sys

    raise SystemExit(main(_sys.argv[1] if len(_sys.argv) > 1 else "punjab"))
