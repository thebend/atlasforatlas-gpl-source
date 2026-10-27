"""Territory fields for scenes whose borders come from dated polygon datasets.

Observed layer: every dated polygon (CShapes country-periods; US states and
territories; treaty cessions; colonial-claim snapshots) is rasterised with 3x3
supersampling into a 0..1 coverage grid and assigned to one or more polity
sides with a claim weight (a paper claim over land others hold is weaker than
a homeland or an organised state). Each side keeps the max over its polygons,
so overlapping claims render as contested ground instead of one source
silently winning. A per-source crispness feeds the observed-coverage channel:
academic boundary data draws crisp, approximate snapshot data softer.

Research layer ('air' variant): verified/partially verified AI-research
control claims seed a cost-distance field per polity (de-facto control). It is
kept at near full strength inside other sides' mapped polygons, so occupation
and annexation the de-jure data omits renders as contested ground rather than
silently replacing the source.

Variants written: obs (= base: observed only) and air (observed + research).
Layout 'tiled' (<= 64 sides): tiles packed in a COLS x ROWS grid (4 per tile,
last tile = metadata: R observed coverage, G research strength).
Layout 'topk' (any number of sides): three panels of width nx per slice —
[top-4 side ids, low byte][their strengths][R observed, G research,
B/A high nibbles of the ids]; ids are 1-based, 0 = empty.

Run: ATLAS_SCENE=europe uv run --project .. python -m etl.history.fields_polygons
"""
from __future__ import annotations

import datetime as dt
import heapq
import json
import math
import re

import numpy as np
import shapely
from PIL import Image
from shapely.geometry import shape

from etl.common import CFG, LAT0, LAT1, LON0, LON1, OUT, PROTO, RCACHE, RESEARCH_NAMES, SCACHE, SCENE, grid, write_json

STEP = CFG["field_step"]
Y0, Y1 = CFG["years"]
COLS = 4


def dec_year(s: str | int | float | None) -> float | None:
    if s is None or s == "":
        return None
    if isinstance(s, (int, float)):
        return float(s)
    m = re.match(r"(-?\d{1,6})(?:-(\d{2}))?(?:-(\d{2}))?", str(s))
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2) or 1), int(m.group(3) or 1)
    try:
        a = dt.date(y, mo, d)
    except ValueError:
        return float(y)
    start = dt.date(y, 1, 1)
    return y + (a - start).days / 365.25


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


# ------------------------------------------------------------------ scene configs
EU_NAMES = {
    "United Kingdom": ("britain", "United Kingdom"), "Germany (Prussia)": ("germany", "Germany"),
    "Russia (Soviet Union)": ("russia", "Russia / Soviet Union"), "Turkey (Ottoman Empire)": ("ottoman", "Ottoman Empire / Turkey"),
    "Italy/Sardinia": ("italy", "Italy"), "Rumania": ("romania", "Romania"),
    "German Federal Republic": ("west-germany", "West Germany"), "German Democratic Republic": ("east-germany", "East Germany"),
    "Iran (Persia)": ("iran", "Persia / Iran"),
}
EU_RESEARCH_ALIAS = {"ussr": "russia", "turkey": "ottoman", "us": "usa", "free-city-danzig": "danzig"}


def europe_sources() -> list[dict]:
    d = json.loads((SCACHE / "geo" / "cshapes2_europe_1910_1950.geojson").read_text())
    feats = []
    for f in d["features"]:
        p = f["properties"]
        sid, name = EU_NAMES.get(p["name"], (slug(p["name"]), p["name"]))
        feats.append({"side": sid, "name": name, "y0": dec_year(p["start"]), "y1": dec_year(p["end"]) + 1 / 365.25,
                      "geom": shape(f["geometry"]), "sides": [(sid, 1.0)], "crisp": 1.0, "source": "cshapes2"})
    return feats


def europe_slice_years() -> list[float]:
    ch = json.loads((SCACHE / "changes.json").read_text())
    ys = {float(Y0)}
    for c in ch:
        if c.get("border_change", True):
            y = dec_year(c.get("date") or c.get("from"))
            if y is not None and Y0 <= y <= Y1 + 1:
                ys.add(round(y, 3))
    return sorted(ys)


from etl.history import border_sides
from etl.history.na_sides import north_america_sources, north_america_slice_years, na_alias


ANT_CLAIMS = PROTO / "sources" / "antarctica" / "claims.json"


def antarctica_sources() -> list[dict]:
    """National claims as their instruments define them: sectors of meridians between two
    parallels. Paper claims (none was ever control in the usual sense), so they draw hatched;
    where two overlap (Britain, Chile, Argentina) the ground reads as contested."""
    d = json.loads(ANT_CLAIMS.read_text())
    # one label per claimant: its latest territory's English name, then the state
    # ("Ross Dependency (New Zealand)"); map labels drop the bracket, the legend keeps it
    label: dict[str, str] = {}
    for c in sorted(d["claims"], key=lambda c: c["from"]):
        m = re.match(r"^(.*?) \((.*)\)$", c["name"])
        terr = m.group(2) if m and not re.search(r"\d|,", m.group(2)) else c["name"]
        state = re.sub(r"\s*\(.*\)$", "", c["state"])
        label[c["side"]] = f"{terr} ({state})"
    feats = []
    for c in d["claims"]:
        w, e = float(c["west_lon"]), float(c["east_lon"])
        n, s = float(c["north_lat"]), float(c.get("south_lat") if c.get("south_lat") is not None else -90)
        lo, hi = min(n, s), max(n, s)
        boxes = [shapely.box(w, lo, e, hi)] if w < e else [shapely.box(w, lo, 180, hi), shapely.box(-180, lo, e, hi)]
        geom = shapely.union_all(boxes)
        for x in c.get("exclusions") or []:
            xw, xe = float(x["west_lon"]), float(x["east_lon"])
            xn = float(x["north_lat"]) if x.get("north_lat") is not None else hi
            xs = float(x["south_lat"]) if x.get("south_lat") is not None else lo
            geom = geom.difference(shapely.box(xw, min(xn, xs), xe, max(xn, xs)))
        y1 = dec_year(c.get("to"))
        feats.append({"side": c["side"], "name": c.get("name") or c["state"], "names": {c["side"]: label[c["side"]]},
                      "y0": dec_year(c["from"]), "y1": (y1 if y1 is not None else Y1 + 1),
                      "geom": geom, "sides": [(c["side"], 0.45)], "crisp": 1.0, "source": "claims",
                      "kind": "state", "claim": True})
    return feats


def antarctica_slice_years() -> list[float]:
    ys = {float(Y0)}
    for f in antarctica_sources():
        for y in (f["y0"], f["y1"]):
            if Y0 <= y <= Y1 + 1:
                ys.add(round(y, 3))
    return sorted(ys)


class _Alias(dict):
    """dict-like alias whose misses go through a canonicaliser."""
    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def get(self, k, default=None):
        return self.fn(k)


# border sources a manifest can name (etl.borders): polygons, slice years, research polity alias.
# "cshapes" and "cliopatria" serve any scene (etl/fetch/borders.py); the others are one scene's own data.
SCENE_FNS = {"europe": (europe_sources, europe_slice_years, EU_RESEARCH_ALIAS),
             "north-america": (north_america_sources, north_america_slice_years, _Alias(na_alias)),
             "antarctica": (antarctica_sources, antarctica_slice_years, {})}


def border_inputs() -> tuple[list[dict], list[float], dict]:
    """Polygons, slice years and research alias for the border sources the scene names."""
    names = [b if isinstance(b, str) else b["source"] for b in CFG.get("borders", [])]
    if len(names) == 1 and names[0] in SCENE_FNS:                 # a scene's own source
        fs, ys, al = SCENE_FNS[names[0]]
        return fs(), ys(), al
    feats = []
    for b in CFG.get("borders", []):
        opt = {"source": b} if isinstance(b, str) else b
        feats += border_sides.LOADERS[opt["source"]](opt)
    return feats, border_sides.slice_years(feats), border_sides.alias()


# ------------------------------------------------------------------ research seeds
AUTH_W = {"annexation": 1.0, "occupation": 0.92, "military-administration": 0.88, "puppet": 0.8, "liberated": 0.9,
          "zone-of-occupation": 0.9, "contested": 0.7, "homeland": 0.9, "confederacy": 0.85, "seasonal-range": 0.6,
          "direct": 0.9, "tributary": 0.7, "claimed": 0.5, "sovereign": 0.95}


def research_seeds(alias: dict[str, str], states: list[dict]) -> tuple[list[dict], list[dict]]:
    p = RCACHE / f"{RESEARCH_NAMES[0]}.json" if RESEARCH_NAMES else None
    if p is None or not p.exists():
        return [], []
    cat = json.loads(p.read_text())
    seeds = []
    for c in cat.get("claims", []):
        if c.get("type") != "control" or c.get("verification", {}).get("status") not in ("verified", "partially-verified"):
            continue
        if c.get("authority") in ("ceded", "removed"):
            continue
        pl = c.get("place") or {}
        if pl.get("lon") is None or not (LON0 <= pl["lon"] <= LON1 and LAT0 <= pl["lat"] <= LAT1):
            continue                                           # outside the window: would seed at its edge
        f, t = c.get("from") or {}, c.get("to") or {}
        y0 = dec_year(f"{f.get('year')}-{int(f.get('month') or 1):02d}-{int(f.get('day') or 1):02d}") if f.get("year") else Y0
        y1 = dec_year(f"{t.get('year')}-{int(t.get('month') or 12):02d}-{int(t.get('day') or 28):02d}") if t and t.get("year") else None
        conf = {"high": 1.0, "medium": 0.9, "low": 0.75}.get(c.get("confidence"), 0.85)
        sd = {"side": alias.get(c["polity"], c["polity"]), "lon": pl["lon"], "lat": pl["lat"],
              "w": conf * AUTH_W.get(c.get("authority"), 0.85), "y0": y0, "y1": y1, "id": c["id"]}
        # a dated range (radiocarbon): the claim fades in across its start range and out across its end range
        if (f.get("end") or {}).get("year") is not None and f["end"]["year"] > f["year"]:
            sd["in"] = [y0, float(f["end"]["year"])]
        if t and (t.get("end") or {}).get("year") is not None and t["end"]["year"] > t["year"]:
            sd["y1"] = float(t["end"]["year"])
            sd["out"] = [y1, sd["y1"]]
        seeds.append(sd)
    if SCENE == "europe":
        seeds += front_defender_seeds(states)
    return seeds, cat.get("polities", [])


def front_defender_seeds(states: list[dict]) -> list[dict]:
    """Cited front towns held by their own country's coalition become that country's
    seeds, so an occupier's spread stops at the line instead of crossing it. `states` are the
    scene's border polygons (CShapes for Europe; Cliopatria under the commercial profile)."""
    paths = [RCACHE / f"{n}.json" for n in ("europe-fronts-1914-1945", "europe-fronts-1940-west")]
    claims = [c for p in paths if p.exists() for c in json.loads(p.read_text())["claims"]]
    if not claims:
        return []
    from etl.history.wars import coalition_of
    for f in states:
        shapely.prepare(f["geom"])
    out = []
    for c in claims:
        if c.get("type") != "control" or c.get("verification", {}).get("status") not in ("verified", "partially-verified"):
            continue
        pl, fr, to = c.get("place") or {}, c.get("from") or {}, c.get("to") or {}
        if pl.get("lon") is None or not fr.get("year"):
            continue
        y0 = dec_year(f"{fr['year']}-{int(fr.get('month') or 1):02d}-{int(fr.get('day') or 1):02d}")
        y1 = dec_year(f"{to['year']}-{int(to.get('month') or 12):02d}-{int(to.get('day') or 28):02d}") if to.get("year") else y0 + 1 / 12
        owner = next((f["side"] for f in states if f["y0"] <= y0 < f["y1"] and shapely.contains_xy(f["geom"], pl["lon"], pl["lat"])), None)
        if owner and coalition_of(owner, y0) == c.get("polity"):
            out.append({"side": owner, "lon": pl["lon"], "lat": pl["lat"], "w": 0.95, "y0": y0, "y1": y1, "id": "front:" + c["id"]})
    print("front defender seeds", len(out))
    return out


# ------------------------------------------------------------------ rasters
def _grow(m: np.ndarray, r: int) -> np.ndarray:
    """Binary dilation by a (2r+1)^2 square, numpy only."""
    out = m.copy()
    for _ in range(r):
        g = out.copy()
        g[1:, :] |= out[:-1, :]
        g[:-1, :] |= out[1:, :]
        g[:, 1:] |= out[:, :-1]
        g[:, :-1] |= out[:, 1:]
        out = g
    return out


def coverage(geom, LONS: np.ndarray, LATS: np.ndarray, ramp: float = 1.0):
    """Polygon coverage 0..1 as a clamped signed-distance ramp, cropped to the polygon's bounds.

    coverage = clamp(0.5 + signed_distance / (ramp * cell)). With ramp = 1 the 0.5 isoline
    reconstructs a straight edge at sub-cell precision under bilinear filtering, so edges
    do not staircase; a wider ramp (approximate sources) spreads the edge into a gradient
    of doubt instead of a line. Returns (row slice, col slice, sub-array) or None."""
    shapely.prepare(geom)
    x0, y0, x1, y1 = geom.bounds
    ny, nx = LONS.shape
    pad = int(math.ceil(ramp)) + 1
    c0 = max(0, int((x0 - LON0) / STEP) - pad)
    c1 = min(nx, int((x1 - LON0) / STEP) + pad + 1)
    r0 = max(0, int((LAT1 - y1) / STEP) - pad)
    r1 = min(ny, int((LAT1 - y0) / STEP) + pad + 1)
    if c0 >= c1 or r0 >= r1:
        return None
    lo, la = LONS[r0:r1, c0:c1], LATS[r0:r1, c0:c1]
    inside = shapely.contains_xy(geom, lo, la)
    # cells within the ramp of the boundary: where inside/outside changes nearby
    k = int(math.ceil(ramp)) + 1
    band = _grow(inside, k) & _grow(~inside, k)
    cov = inside.astype(np.float32)
    if band.any():
        bd = geom.boundary
        shapely.prepare(bd)
        d = shapely.distance(bd, shapely.points(lo[band], la[band]))
        sd = np.where(inside[band], d, -d)
        cov[band] = np.clip(0.5 + sd / (ramp * STEP), 0, 1)
    if not cov.any():
        return None
    return (slice(r0, r1), slice(c0, c1), cov)


def friction(LONS: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    H = np.load(SCACHE / "elev.npy")
    ny, nx = LONS.shape
    ky, kx = H.shape[0] / ny, H.shape[1] / nx
    iy = np.minimum((np.arange(ny) * ky + ky / 2).astype(int), H.shape[0] - 1)
    ix = np.minimum((np.arange(nx) * kx + kx / 2).astype(int), H.shape[1] - 1)
    Hs = H[np.ix_(iy, ix)]
    gy, gx = np.gradient(Hs, STEP, STEP)
    slope = np.hypot(gx / 111320, gy / 110540)
    F = (STEP / 0.1) * 0.2 * (1 + 6 * slope)
    F = np.where(Hs > 3000, F * 4, F)
    land = Hs > 0
    F = np.where(land, F, F * 30)
    return F, land


def spread_seed(F: np.ndarray, s: dict, cap: float, gamma: float | None = None):
    """Cost-distance strength around one seed, cropped to the cells it reaches.

    A side's field is the max over its active seeds: multi-source Dijkstra cost
    is the min over sources, and strength falls monotonically with cost, so
    caching one field per seed is exact and lets slices reuse them."""
    ny, nx = F.shape
    ix = min(nx - 1, max(0, int((s["lon"] - LON0) / STEP)))
    iy = min(ny - 1, max(0, int((LAT1 - s["lat"]) / STEP)))
    c0 = (1 - s["w"]) * cap * 0.5
    best = {iy * nx + ix: c0}
    pq = [(c0, iy * nx + ix)]
    D = math.sqrt(2)
    while pq:
        c, i = heapq.heappop(pq)
        if c > best[i] or c >= cap:
            continue
        y, x = divmod(i, nx)
        for dx, dy, dm in ((1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0), (1, 1, D), (1, -1, D), (-1, 1, D), (-1, -1, D)):
            xx, yy = x + dx, y + dy
            if 0 <= xx < nx and 0 <= yy < ny:
                j = yy * nx + xx
                nc = c + F[yy, xx] * dm
                if nc < best.get(j, 1e9):
                    best[j] = nc
                    heapq.heappush(pq, (nc, j))
    idx = np.fromiter(best.keys(), np.int64, len(best))
    cost = np.fromiter(best.values(), np.float64, len(best))
    ys, xs = np.divmod(idx, nx)
    r0, r1, q0, q1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    out = np.zeros((r1 - r0, q1 - q0), np.float32)
    g = CFG.get("research_gamma", 0.6) if gamma is None else gamma
    out[ys - r0, xs - q0] = np.clip(1 - cost / cap, 0, 1) ** g
    return slice(r0, r1), slice(q0, q1), out


def js_num(y: float) -> str:
    """Number formatted the way JavaScript's String() does, so file names match the app's requests."""
    return str(int(y)) if float(y).is_integer() else repr(float(y))


def topk_image(S: dict[int, np.ndarray], meta_r, meta_g, ny: int, nx: int) -> np.ndarray:
    """Top-4 (id, strength) per cell; ids 1-based with 12 bits (low byte + nibble)."""
    img = np.zeros((ny, nx * 3, 4), np.uint8)
    img[:, 2 * nx:, 0] = meta_r
    img[:, 2 * nx:, 1] = meta_g
    if not S:
        return img
    ks = np.array(sorted(S), np.int32)
    stack = np.stack([S[k] for k in ks])                       # (n, ny, nx)
    m = min(4, len(ks))
    order = np.argsort(-stack, axis=0)[:m]                     # strongest first
    vals = np.take_along_axis(stack, order, 0)
    ids = np.where(vals > 1 / 255, ks[order] + 1, 0)
    q = np.round(vals * 255).astype(np.uint8)
    hi = np.zeros((4, ny, nx), np.uint8)
    for e in range(m):
        img[:, :nx, e] = ids[e] & 255
        img[:, nx:2 * nx, e] = np.where(ids[e] > 0, q[e], 0)
        hi[e] = ids[e] >> 8
    img[:, 2 * nx:, 2] = (hi[0] << 4) | hi[1]
    img[:, 2 * nx:, 3] = (hi[2] << 4) | hi[3]
    return img


def active(y0, y1, y: float) -> bool:
    return (y0 is None or y0 <= y + 1e-6) and (y1 is None or y < y1)


def ramp(sd: dict, y: float) -> float:
    """A seed's strength at y: 0 to 1 across its fade-in range, 1 to 0 across its fade-out range."""
    k = 1.0
    if sd.get("in"):
        a, b = sd["in"]
        k = min(k, max(0.0, (y - a) / (b - a)))
    if sd.get("out"):
        a, b = sd["out"]
        k = min(k, max(0.0, (b - y) / (b - a)))
    return k


def main() -> None:
    LONS, LATS = grid(STEP)
    ny, nx = LONS.shape
    feats, years, alias = border_inputs()
    seeds, rpolities = research_seeds(alias, feats)
    for s in seeds:
        for y in (s["y0"], s["y1"], *s.get("in", ()), *s.get("out", ())):
            if y is not None and Y0 < y < Y1 + 1:
                years.append(round(y, 3))
    years = sorted(set(years))
    # merge slices closer than ~45 days: they would only flicker
    merged: list[float] = []
    gap = CFG.get("slice_gap", 0.12)
    for y in years:
        if not merged or y - merged[-1] > gap:
            merged.append(y)
    years = merged
    names: dict[str, str] = {}
    kinds: dict[str, str] = {}
    for f in feats:
        for sd, _ in f["sides"]:
            kinds.setdefault(sd, f.get("kind", "state"))
    for f in feats:
        for sd, _ in f["sides"]:
            names.setdefault(sd, f.get("names", {}).get(sd) or f["name"])
    rnames = {alias.get(p["id"], p["id"]): p.get("name", p["id"]) for p in rpolities}
    research_only = sorted({s["side"] for s in seeds} - set(names))
    for sid in research_only:
        names[sid] = rnames.get(sid, sid)
    sides = sorted(set(names) - set(research_only)) + research_only
    TOPK = len(sides) > 64 or CFG.get("field_format") == "topk"
    if len(sides) > 4095:
        raise SystemExit(f"{len(sides)} sides > 4095")
    six = {s: i for i, s in enumerate(sides)}
    K = len(sides)
    T = math.ceil(K / 4)
    rows = math.ceil((T + 1) / COLS)
    print(f"{SCENE}: grid {nx}x{ny}, {len(feats)} polygons, {len(seeds)} research seeds, {K} sides, {len(years)} slices")

    cov_cache: dict[int, object] = {}
    F, land = friction(LONS)
    cap = CFG.get("research_cap", 7.0)
    spread_cache: dict = {}
    fdir = OUT / "fields"
    fdir.mkdir(parents=True, exist_ok=True)
    for old in fdir.glob("*.png"):
        old.unlink()
    for y in years:
        obs: dict[int, np.ndarray] = {}
        crisp: dict[int, np.ndarray] = {}                 # per side: how crisp its strongest source is here
        for f in feats:
            if not active(f["y0"], f["y1"], y):
                continue
            key = id(f)
            if key not in cov_cache:
                cov_cache[key] = coverage(f["geom"], LONS, LATS, f.get("ramp", 1.0))
            cv = cov_cache[key]
            if cv is None:
                continue
            rs, cs, c = cv
            for side, w in f["sides"]:
                k = six[side]
                if k not in obs:
                    obs[k] = np.zeros((ny, nx), np.float32)
                    crisp[k] = np.zeros((ny, nx), np.float32)
                v = c * w
                win = v > obs[k][rs, cs]
                obs[k][rs, cs] = np.where(win, v, obs[k][rs, cs])
                crisp[k][rs, cs] = np.where(win & (c > 0.02), f["crisp"], crisp[k][rs, cs])
        if not CFG.get("soft_coast"):
            for k in obs:
                obs[k][~land] = 0
        air = dict(obs)
        air_g = np.zeros((ny, nx), np.float32)
        r_occ: dict[int, np.ndarray] = {}
        r_def: dict[int, np.ndarray] = {}
        for side in sorted({s["side"] for s in seeds}):
            act = [s for s in seeds if s["side"] == side and active(s["y0"], s["y1"], y)]
            if not act:
                continue
            k = six[side]
            for dest, group in ((r_occ, [a for a in act if not a["id"].startswith("front:")]),
                                (r_def, [a for a in act if a["id"].startswith("front:")])):
                if not group:
                    continue
                r = np.zeros((ny, nx), np.float32)
                for sd in group:
                    if sd["id"] not in spread_cache:
                        spread_cache[sd["id"]] = spread_seed(F, sd, cap)
                    rs, cs, v = spread_cache[sd["id"]]
                    np.maximum(r[rs, cs], v * ramp(sd, y), out=r[rs, cs])
                r *= land
                if dest is r_def:
                    # a defended front town holds only its own country's land
                    r *= (obs.get(k, 0) >= 0.5)
                dest[k] = r
        for k in set(r_occ) | set(r_def):
            r = r_occ.get(k, np.zeros((ny, nx), np.float32))
            # occupation stops where another country holds a defended front town
            others = [v for d, v in r_def.items() if d != k]
            if others:
                r = r * (1 - np.max(np.stack(others), 0))
            r = np.maximum(r, r_def.get(k, 0))
            air[k] = np.maximum(air.get(k, 0), r * CFG.get("research_peak", 0.97))
            air_g = np.maximum(air_g, r)
        for variant, S, g in (("obs", obs, np.zeros_like(air_g)), ("air", air, air_g)):
            # crispness of whichever side leads each cell (research-only sides: 0 = soft)
            if S:
                ks = sorted(S)
                lead = np.argmax(np.stack([S[k] for k in ks]), 0)
                cr = np.stack([crisp.get(k, np.zeros((ny, nx), np.float32)) for k in ks])
                obs_lead = np.take_along_axis(cr, lead[None], 0)[0]
            else:
                obs_lead = np.zeros((ny, nx), np.float32)
            meta_r = np.round(obs_lead * (1 if CFG.get("soft_coast") else land) * 255).astype(np.uint8)
            meta_g = np.round(g * 255).astype(np.uint8)
            if TOPK:
                img = topk_image(S, meta_r, meta_g, ny, nx)
            else:
                img = np.zeros((ny * rows, nx * COLS, 4), np.uint8)
                for k, arr in S.items():
                    t, ch = divmod(k, 4)
                    r0, c0 = divmod(t, COLS)
                    img[r0 * ny:(r0 + 1) * ny, c0 * nx:(c0 + 1) * nx, ch] = np.round(arr * 255)
                r0, c0 = divmod(T, COLS)
                img[r0 * ny:(r0 + 1) * ny, c0 * nx:(c0 + 1) * nx, 0] = meta_r
                img[r0 * ny:(r0 + 1) * ny, c0 * nx:(c0 + 1) * nx, 1] = meta_g
            Image.fromarray(img, "RGBA").save(fdir / f"{variant}_{js_num(y)}.png", optimize=True)
        print("slice", y, flush=True)

    # base == obs for polygon scenes (no curated modelled layer): alias, don't duplicate
    write_json(OUT / "fields.json", {
        "bbox": [LON0, LAT0, LON1, LAT1], "step": STEP, "width": nx, "height": ny,
        "tiles": T, "cols": COLS, "rows": rows, "format": "topk" if TOPK else "tiled",
        "claim_below": CFG.get("claim_below", 0),
        "sides": [{"id": s, "name": names[s], "index": i, "research": s in research_only,
                   "kind": ("culture" if s not in research_only and re.search(r"hunter|gatherer|foraging|culture|peoples$|bison hunters|fichers", names[s].lower())
                            else kinds.get(s, CFG.get("research_kind", "state") if s in research_only else "state"))}
                  for i, s in enumerate(sides)],
        "slices": years, "variants": ["obs", "air"], "variant_alias": {"base": "obs"},
        "provenance": {"observed": sorted({f['source'] for f in feats}),
                       "air": f"research/{RESEARCH_NAMES[0] if RESEARCH_NAMES else None}.json (verified + partially verified claims)"},
        "research_seeds": seeds,
        "ohm": [{"side": sd, "title": f["name"], "y0": round(f["y0"], 3), "y1": round(f["y1"], 3), "source": f["source"]}
                for f in feats for sd, w in f["sides"] if w >= 0.85 or f.get("claim")],
    })


if __name__ == "__main__":
    main()
