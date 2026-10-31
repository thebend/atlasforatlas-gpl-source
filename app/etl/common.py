"""Shared grid + IO helpers for the atlas prototype build scripts.

The active scene comes from the ATLAS_SCENE environment variable (default
south-asia); every script reads and writes that scene's folders:
  public/data/<scene>/   served to the app (generated; gitignored)
  .cache/scenes/<scene>/ intermediate and raw data (gitignored)

Everything under public/data and .cache is rebuilt by `etl/rebuild.py`. For testing a
rebuild in isolation, ATLAS_PUBLIC and ATLAS_CACHE redirect the two roots.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]          # repo root
PROTO = ROOT / "app"

SCENE_DIR = PROTO / "scenes"                      # one manifest per scene: scenes/<id>.json


def load_manifests() -> dict[str, dict]:
    """Scene manifests (scenes/*.json), in build order, as the build profile (ATLAS_PROFILE,
    etl/profile.py) builds them. Each holds the window, years, sources, pipeline and the app's
    chapters and card; the frontend reads the same files, through the same profile."""
    from etl import profile                        # the build profile rewrites what it may not ship
    ms = {m["id"]: m for m in (profile.apply(json.loads(p.read_text())) for p in SCENE_DIR.glob("*.json"))}
    # a topic on another period's built data ("base": etl/rebuild.py builds nothing for it) has the rest of that manifest
    ms = {sid: {**ms[m["base"]], "hidden": False, **m} if m.get("base") else m for sid, m in ms.items()}
    return dict(sorted(ms.items(), key=lambda kv: (kv[1].get("order", 999), kv[0])))


MANIFESTS = load_manifests()
# build config per scene: bbox lon0, lat0, lon1, lat1; years; terrain step (deg) and DEM zoom;
# field step (deg); and the scene's other ETL options (manifest "etl")
SCENES = {sid: {"bbox": tuple(float(x) for x in m["bbox"]), "years": tuple(m["years"]), **m.get("etl", {})} for sid, m in MANIFESTS.items()}
# the world base layer (relief, colour, coast) behind every scene; not a scene itself
# pole to pole: Terrarium tiles stop at 85 deg, so base/terrain.py fills the caps from ETOPO1
WORLD = {"bbox": (-180.0, -90.0, 180.0, 90.0), "terrain_step": 0.075, "dem_z": 5, "field_step": 0.5, "years": (-10000, 2025)}
SCENE = os.environ.get("ATLAS_SCENE", "south-asia")
CFG = WORLD if SCENE == "world" else SCENES[SCENE]
MANIFEST = MANIFESTS.get(SCENE, {})
# research catalogues (research/<name>.raw.json); the first is the one the app shows
RESEARCH_NAMES: list[str] = MANIFEST.get("research", [])
LON0, LAT0, LON1, LAT1 = CFG["bbox"]
PUBLIC = Path(os.environ.get("ATLAS_PUBLIC", PROTO / "public"))
OUT = PUBLIC / "data" / SCENE
CACHE = Path(os.environ.get("ATLAS_CACHE", PROTO / ".cache"))
SCACHE = CACHE / "scenes" / SCENE
RESEARCH = PROTO / "research"                      # committed: researcher + verifier output
RCACHE = CACHE / "research"                        # generated: quote checks, merged catalogues
# the central catalogue (etl/catalogue.py): every event, place and research item stored once, which
# periods and tours read as views. A scene's event steps leave their working list in SCACHE for it.
CATALOGUE = PUBLIC / "data" / "catalogue"
SCENE_EVENTS = SCACHE / "events.json"
TOURS = PROTO / "tours"                            # committed: tours/<id>.json, stops that reference the catalogue


def load_tours() -> dict[str, dict]:
    """Tours (tours/*.json) by id. A tour on a period inherits the period's title, card (region and
    themes) and research unless it gives its own; src/lib/tour.ts reads them the same way."""
    out = {}
    for p in sorted(TOURS.glob("*.json")):
        t = json.loads(p.read_text())
        m = MANIFESTS.get(t.get("scene"))
        if m:
            t.setdefault("title", m["title"])
            t.setdefault("research", list(m.get("research", [])))
            if "card" not in t and m.get("card"):
                t["card"] = {"region": m["card"]["region"], "themes": list(m["card"]["themes"])}
        out[p.stem] = t
    return out


# every request the build makes says who is asking by the project's address, never a person's (etl/net.py)
UA = "AtlasForAtlas/0.1 (https://atlasforatlas.com; data build)"


def grid(step: float) -> tuple[np.ndarray, np.ndarray]:
    nx = int(round((LON1 - LON0) / step))
    ny = int(round((LAT1 - LAT0) / step))
    xs = LON0 + (np.arange(nx) + 0.5) * step
    ys = LAT1 - (np.arange(ny) + 0.5) * step            # north -> south
    return np.meshgrid(xs, ys)


def tile_xy(lon: float, lat: float, z: int) -> tuple[float, float]:
    n = 2 ** z
    lat = max(-85.0, min(85.0, lat))
    r = math.radians(lat)
    return (lon + 180) / 360 * n, (1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * n


def write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
    os.replace(tmp, path)
