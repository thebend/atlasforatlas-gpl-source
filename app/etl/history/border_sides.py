"""Territory polygons from the worldwide border sources (etl/fetch/borders.py), as sides.

CShapes 2.0 (observed, crisp): every country-period is drawn as its sovereign's territory. A colony,
protectorate, mandate or occupied territory belongs to its `owner` (the GW code CShapes records),
so British Africa reads as Britain; its weight is a little below a state's own ground, and where
CShapes marks a border as not clearly defined (`b_def` = 0, common in 1880s-90s colonies) the edge
is drawn soft.

Cliopatria (observed, coarse): Seshat's polity outlines, year resolution, deliberately one version
of each territory. Rows of a composite empire (MemberOf) are drawn as that empire; everything is
drawn soft and at a lower weight, since the outlines are approximate.

Which rows are the same power across the two sources (and which ids research catalogues may use)
comes from sources/sides.json, an identity table with no geometry.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import unicodedata

from shapely.geometry import shape

from etl.common import CFG, PROTO, SCACHE

Y0, Y1 = CFG["years"]
SIDES = json.loads((PROTO / "sources" / "sides.json").read_text())["sides"]
BY_GW = {g: sid for sid, s in SIDES.items() for g in s["cshapes"]}
BY_CLIO = {n: sid for sid, s in SIDES.items() for n in s["cliopatria"]}
# claim weight by CShapes status: a colony is held less firmly than a state's own land
CSHAPES_START = 1886.0
STATUS_W = {"independent": 1.0, "colony": 0.92, "protectorate": 0.85, "mandate": 0.88, "occupied": 0.85}


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def dec(iso: str) -> float:
    d = dt.date.fromisoformat(iso)
    return d.year + (d - dt.date(d.year, 1, 1)).days / 365.25


def alias() -> dict[str, str]:
    """Research polity id -> side id."""
    return {a: sid for sid, s in SIDES.items() for a in s["aliases"]}


def _load(name: str) -> list[dict]:
    p = SCACHE / "geo" / f"{name}.geojson"
    if not p.exists():
        raise SystemExit(f"{p} missing: run etl.fetch.borders for this scene first")
    return json.loads(p.read_text())["features"]


def cshapes_sources(opt: dict) -> list[dict]:
    rows = [f for f in _load("cshapes2")]
    # an independent row names its own state; dependents take their owner's name
    state_name = {}
    for f in sorted(rows, key=lambda f: f["properties"]["start"]):
        p = f["properties"]
        if p["status"] == "independent":
            state_name.setdefault(p["gwcode"], p["name"])
    drop = set(opt.get("drop", []))              # GW codes another source draws here (e.g. OHM's Israel and Palestine)
    feats = []
    for f in rows:
        p = f["properties"]
        if p["gwcode"] in drop:
            continue
        own = p["gwcode"] if p["status"] == "independent" or p["owner"] is None else p["owner"]
        sid = BY_GW.get(own) or slug(state_name.get(own) or (p["name"] if own == p["gwcode"] else f"gw-{own}"))
        name = SIDES[sid]["name"] if sid in SIDES else state_name.get(own, p["name"])
        w = STATUS_W.get(p["status"], 0.7)
        defined = p.get("b_def", 1) == 1
        feats.append({"side": sid, "name": name, "names": {sid: name}, "y0": dec(p["start"]), "y1": dec(p["end"]) + 1 / 365.25,
                      "geom": shape(f["geometry"]), "sides": [(sid, w)], "crisp": 1.0 if defined else 0.6,
                      "ramp": 1.0 if defined else 2.0, "source": "cshapes2", "kind": "state",
                      "unit": p["name"], "status": p["status"]})
    return feats


def cliopatria_sources(opt: dict) -> list[dict]:
    until = opt.get("until")
    # from CShapes' start, a power CShapes maps (sides.json "cshapes") is drawn from CShapes alone
    defer = opt.get("defer_to_cshapes") and {sid for sid, s in SIDES.items() if s["cshapes"]}
    feats = []
    for f in _load("cliopatria"):
        p = f["properties"]
        y0, y1 = float(p["from"]), float(p["to"]) + 1
        if until is not None:
            if y0 >= until:
                continue
            y1 = min(y1, float(until))
        top = p["member_of"] or p["name"]
        # {"recode": {"Ptolemaic Kingdom": [-323, "Macedonian Empire"]}}: a row Cliopatria misnames, before a year
        rc = opt.get("recode", {}).get(top)
        if rc and y0 < rc[0]:
            top = rc[1]
        sid = BY_CLIO.get(top) or BY_CLIO.get(p["name"]) or slug(top)
        if defer and sid in defer:
            if y0 >= CSHAPES_START:
                continue
            y1 = min(y1, CSHAPES_START)
        name = SIDES[sid]["name"] if sid in SIDES else top
        # {"weights": {"Warring States Japan": 0.3}}: a row drawn faintly, under the research claims that divide it
        w = opt.get("weights", {}).get(top, opt.get("weight", 0.8))
        feats.append({"side": sid, "name": name, "names": {sid: name}, "y0": y0, "y1": y1, "geom": shape(f["geometry"]),
                      "sides": [(sid, w)], "crisp": 0.4, "ramp": 2.5, "source": "cliopatria",
                      "kind": "state", "unit": p["name"]})
    return feats


def _dec_tag(s: str | None, default: float) -> float:
    """An OHM start_date / end_date tag ("2014-03-18", "2014-03", "2014") as a decimal year."""
    if not s:
        return default
    parts = [int(x) for x in s.split("-")[:3]] + [1, 1]
    return dec(f"{parts[0]:04d}-{parts[1]:02d}-{parts[2]:02d}")


def ohm_sources(opt: dict) -> list[dict]:
    """Named OHM relations (etl/fetch/ohm.py), each already assigned to a side by the manifest."""
    feats = []
    for f in _load("ohm"):
        p = f["properties"]
        sid = p["side"]
        name = SIDES[sid]["name"] if sid in SIDES else p["name"]
        feats.append({"side": sid, "name": p["name"], "names": {sid: name}, "y0": _dec_tag(p["start"], Y0 - 1.0),
                      "y1": _dec_tag(p["end"], Y1 + 1.0), "geom": shape(f["geometry"]), "sides": [(sid, p["weight"])],
                      "crisp": 1.0, "source": "ohm", "kind": "state", "unit": p["name"], **({"claim": True} if p["claim"] else {})})
    return feats


def slice_years(feats: list[dict]) -> list[float]:
    """Every date a polygon starts or ends inside the window, where the map changes."""
    ys = {float(Y0)}
    for f in feats:
        for y in (f["y0"], f["y1"]):
            if Y0 < y <= Y1 + 1:
                ys.add(round(y, 3))
    return sorted(ys)


LOADERS = {"cshapes": cshapes_sources, "cliopatria": cliopatria_sources, "ohm": ohm_sources}
