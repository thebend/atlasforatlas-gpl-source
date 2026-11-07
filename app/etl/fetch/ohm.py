"""Named OpenHistoricalMap boundary relations for a scene (observed), where the worldwide datasets are thin.

CShapes ends in 2019 and codes de jure borders; Cliopatria is coarse. A manifest can add specific OHM
relations as a border source, each assigned to a side:
  "borders": [..., {"source": "ohm", "relations": [
      {"rel": 2864022, "side": "palestine", "weight": 0.9, "name": "Palestine"},
      {"rel": 2958257, "side": "russia", "weight": 1.0, "claim": true, "from": "2022-09-30", "name": "..."}]}]
Dates come from the relation's own start_date / end_date tags unless the manifest gives "from" / "to"
(a unit's own boundary used for a later claim over it, e.g. an oblast from the day it was claimed).
Queries are pinned to OHM_DATE with Overpass [date:...] (OHM keeps attic data), so a rebuild sees the
database as it was when the scene was first built; ATLAS_OHM_DATE=latest queries current data (delete
ohm.raw.json to refetch).

Output -> <CACHE>/scenes/<scene>/geo/ohm.geojson (name, side, weight, claim, start, end, relation id).

Run: ATLAS_SCENE=<scene> uv run --project .. python -m etl.fetch.ohm
"""
from __future__ import annotations

import json
import os

import shapely
from shapely.geometry import box, mapping

from etl import net
from etl.common import CFG, LAT0, LAT1, LON0, LON1, SCACHE, SCENE, window_clip, write_json
from etl.fetch.europe.divisions import ohm_build

URL = "https://overpass-api.openhistoricalmap.org/api/interpreter"
OHM_DATE = os.environ.get("ATLAS_OHM_DATE", "2026-10-25T00:00:00Z")
WINDOW = box(LON0 - 1, max(-90, LAT0 - 1), LON1 + 1, min(90, LAT1 + 1))
TOL = CFG["field_step"] / 4


def spec() -> list[dict]:
    return [r for b in CFG.get("borders", []) if isinstance(b, dict) and b.get("source") == "ohm" for r in b["relations"]]


def fetch(ids: list[int]) -> list[dict]:
    raw = SCACHE / "geo" / "ohm.raw.json"
    if raw.exists():
        d = json.loads(raw.read_text())
        if sorted(d.get("ids", [])) == sorted(ids):
            return d["elements"]
    date = f'[date:"{OHM_DATE}"]' if OHM_DATE != "latest" else ""
    q = f"[out:json][timeout:180]{date};rel(id:{','.join(map(str, ids))});out geom;"
    try:     # OHM's shared server: back off, then surface
        els = net.get_json(URL, data={"data": q}, timeout=240, tries=5, backoff=10)["elements"]
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"OHM Overpass failed repeatedly: {e}") from e
    write_json(raw, {"ids": ids, "date": OHM_DATE, "elements": els})
    return els


def main() -> None:
    rels = spec()
    if not rels:
        return
    els = {e["id"]: e for e in fetch([r["rel"] for r in rels])}
    out = []
    for r in rels:
        e = els.get(r["rel"])
        if not e:
            raise SystemExit(f"OHM relation {r['rel']} not found at {OHM_DATE}")
        t = e.get("tags", {})
        g, flag = ohm_build(e)
        if g is None:
            raise SystemExit(f"OHM relation {r['rel']} has no closed ring")
        g = window_clip(shapely.make_valid(g), WINDOW).simplify(TOL)
        out.append({"type": "Feature", "geometry": mapping(shapely.set_precision(g, 1e-4)), "properties": {
            "name": r.get("name") or t.get("name:en") or t.get("name") or f"OHM r{r['rel']}",
            "side": r["side"], "weight": r.get("weight", 0.9), "claim": bool(r.get("claim")),
            "start": r.get("from") or t.get("start_date"), "end": r.get("to") or t.get("end_date"), "source_id": f"ohm:r{r['rel']}",
            "geom_repair": flag or None}})
        print(SCENE, "ohm", r["rel"], out[-1]["properties"]["name"], t.get("start_date"), t.get("end_date"), flush=True)
    write_json(SCACHE / "geo" / "ohm.geojson", {"type": "FeatureCollection", "features": out})


if __name__ == "__main__":
    main()
