"""Fetch OpenHistoricalMap admin boundary relations (levels 2-5, start<=1900) for the North America window.

Polite: one tag query (raw/ohm/admin_tags.json), then geometry in id chunks of 20 ('out geom'), 4 s apart.
Both queries are pinned to OHM_DATE with Overpass [date:...] (OHM keeps attic data), so a rebuild sees the
database as it was when this scene was first built. Set ATLAS_OHM_DATE=latest to query current data instead
(use a fresh ATLAS_CACHE or delete raw/ohm, since cached chunks are reused).
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from .helpers import RAW, log

URL = "https://overpass-api.openhistoricalmap.org/api/interpreter"
UA = "openworld-atlas-prototype/0.1 (+https://github.com/thebend/openworld; low-volume research queries)"
# timestamp_osm_base of the original tag query
OHM_DATE = os.environ.get("ATLAS_OHM_DATE", "2026-10-24T15:24:57Z")
OHM = RAW / "ohm"
CHUNK = 20
PAUSE = 4


def _settings(timeout: int) -> str:
    s = f"[out:json][timeout:{timeout}]"
    if OHM_DATE and OHM_DATE != "latest":
        s += f'[date:"{OHM_DATE}"]'
    return s


def post(q: str) -> bytes:
    data = urllib.parse.urlencode({"data": q}).encode()
    for attempt in range(5):
        try:
            req = urllib.request.Request(URL, data=data, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=180) as r:
                body = r.read()
            d = json.loads(body)
            if d.get("remark") and "error" in d["remark"].lower():
                raise RuntimeError(d["remark"][:300])
            return body
        except urllib.error.HTTPError as ex:
            if ex.code == 400:  # malformed query: retrying will not help
                raise SystemExit(f"Overpass rejected the query: {ex.read()[:500]!r}") from ex
            log("  retry", attempt, ex)
            time.sleep(10 * (attempt + 1))
        except Exception as ex:  # noqa: BLE001
            log("  retry", attempt, ex)
            time.sleep(10 * (attempt + 1))
    raise SystemExit("Overpass query failed")


def tags():
    out = OHM / "admin_tags.json"
    if out.exists():
        return
    OHM.mkdir(parents=True, exist_ok=True)
    q = _settings(100) + '[bbox:7,-170,75,-50];relation["boundary"="administrative"]["start_date"];out tags;'
    out.write_bytes(post(q))
    log("  ohm tags:", len(json.loads(out.read_bytes())["elements"]), "relations")
    time.sleep(PAUSE)


def yr(s):
    try:
        return int(s[:4]) if s and not s.startswith("-") else None
    except ValueError:
        return None


def wanted():
    el = json.load(open(OHM / "admin_tags.json"))["elements"]
    ids = []
    for e in el:
        t = e["tags"]
        s, en = yr(t.get("start_date", "")), yr(t.get("end_date", ""))
        if t.get("admin_level") not in ("2", "3", "4", "5") or s is None or s > 1900:
            continue
        if en is not None and en < 1492:
            continue
        ids.append(e["id"])
    return sorted(ids)


def geometry():
    ids = wanted()
    (OHM / "geom").mkdir(parents=True, exist_ok=True)
    todo = [i for i in range(0, len(ids), CHUNK) if not (OHM / "geom" / f"chunk_{i:05d}.json").exists()]
    log(f"  ohm geometry: {len(ids)} relations, {len(todo)} of {-(-len(ids) // CHUNK)} chunks to fetch")
    for i in todo:
        out = OHM / "geom" / f"chunk_{i:05d}.json"
        q = _settings(150) + ";relation(id:%s);out geom;" % ",".join(map(str, ids[i:i + CHUNK]))
        tmp = out.with_name(out.name + ".part")
        tmp.write_bytes(post(q))
        os.replace(tmp, out)
        log("  chunk", i, out.stat().st_size)
        time.sleep(PAUSE)


ALL = [tags, geometry]
